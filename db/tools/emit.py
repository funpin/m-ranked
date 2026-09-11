import json, pathlib, re, collections
S='/private/tmp/claude-501/-Users-akko-Documents-GitHub-m-ranked/64e9323d-5927-4cea-a794-ff75cdf7819d/scratchpad'
OUT=pathlib.Path('/Users/akko/Documents/GitHub/m-ranked/db/migrations')
live=json.loads(pathlib.Path(f'{S}/schema/live.json').read_text())

DROPPED_OBJECTS = ('rebuild_core_projections','rebuild_serving_projections',
                   'latest_fully_published_dataset_revision','refresh_publication_content',
                   'compact_new_metric_evidence','intern_metric_evidence',
                   'compact_metric_evidence_batch','publication_hourly',
                   'comparison_publication_hourly','comparison_metric_point',
                   'projection_state')

# ---------- transformations ----------
def t_fingerprint(s):
    if s['type']=='TABLE' and s['schema']=='ingest' and s['name'].split()[0] in (
            'publication_metric_snapshot','account_metric_snapshot'):
        b=s['body'].replace('source_fingerprint text NOT NULL','source_fingerprint bytea NOT NULL')
        b=re.sub(r"CONSTRAINT (\w*source_fingerprint_check) CHECK \(\(btrim\(source_fingerprint\) <> ''::text\)\)",
                 r'CONSTRAINT \1 CHECK ((octet_length(source_fingerprint) = 32))', b)
        s['body']=b
    return s

def t_outbox(s):
    s['body']=s['body'].replace(
      "revision, 'projection.rebuild.requested', 'projection', 'core',",
      "revision, 'cache.invalidated', 'cache', 'public',")
    return s

def t_guard(s):
    s['body']=s['body'].replace(
"""    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.rebuild_core_projections',0));
    IF NEW.effective_from_revision<=coalesce((SELECT max(dataset_revision_id) FROM analytics.projection_state),0)""",
"""    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.legacy_period_policy',0));
    -- Прежде барьером была последняя опубликованная проекция. Проекций нет,
    -- данные отдаются живыми, поэтому политику нельзя привязать к ревизии
    -- старее последней зафиксированной: её данные уже отданы наружу.
    IF NEW.effective_from_revision<coalesce((SELECT max(id) FROM analytics.dataset_revision),0)""")
    return s

def t_health(s):
    s['body']=s['body'].replace(
"""), required(name) AS (VALUES ('publication_latest'),('publication_hourly'),('publication_history'),('institution_daily_metrics'),
    ('institution_monthly_metrics'),('institution_period_metrics'),('comparison')),
published AS (
    SELECT s.dataset_revision_id, revision.committed_at
      FROM analytics.projection_state s
      JOIN analytics.dataset_revision AS revision
        ON revision.id = s.dataset_revision_id
    WHERE s.status='ready' AND s.projection_name IN (SELECT name FROM required)
    GROUP BY s.dataset_revision_id, revision.committed_at
    HAVING count(*)=(SELECT count(*) FROM required)
    ORDER BY s.dataset_revision_id DESC LIMIT 1
), outbox_class AS (
    SELECT CASE
             WHEN event_type = 'projection.rebuild.requested' THEN 'projectionControl'
             WHEN event_type = 'projection.published' THEN 'projectionLifecycle'
             ELSE 'cacheDelivery'
           END AS class,""",
"""), published AS (
    -- Данные видны сразу после фиксации ревизии: материализованных проекций,
    -- которых нужно было дожидаться, больше нет.
    SELECT revision.id AS dataset_revision_id, revision.committed_at
      FROM analytics.dataset_revision AS revision
     ORDER BY revision.id DESC LIMIT 1
), outbox_class AS (
    SELECT 'cacheDelivery' AS class,""")
    s['body']=s['body'].replace(
"""             WHERE published_at IS NULL
               AND terminal_at IS NULL
               AND event_type <> 'projection.rebuild.requested'
               AND event_type <> 'projection.published'
        )""",
"""             WHERE published_at IS NULL
               AND terminal_at IS NULL
        )""")
    return s

def t_barrier_callers(s):
    s['body']=s['body'].replace('analytics.latest_fully_published_dataset_revision()',
                                'analytics.latest_dataset_revision()')
    return s

NEW_BARRIER = {
 'schema':'analytics', 'type':'FUNCTION', 'name':'latest_dataset_revision()',
 'body':"""-- Без материализованных проекций публиковать нечего: ревизия видна сразу после
-- фиксации. Прежняя latest_fully_published_dataset_revision() возвращала последнюю
-- ревизию, для которой все семь проекций имели статус ready, и была барьером,
-- из-за которого свежие данные не показывались до прогона publisher.
CREATE FUNCTION analytics.latest_dataset_revision() RETURNS TABLE(id bigint, committed_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
SELECT revision.id, revision.committed_at
  FROM analytics.dataset_revision revision
 ORDER BY revision.id DESC
 LIMIT 1
$$;"""}

def t_only(s):
    # pg_dump пишет ONLY, потому что следом создаёт индексы на каждой партиции
    # и подшивает их через ATTACH. Этой механики здесь нет: объявление на
    # родителе должно каскадировать на все партиции, включая будущие.
    if s["type"] in ("CONSTRAINT","CHECK CONSTRAINT","FK CONSTRAINT","INDEX"):
        s["body"]=s["body"].replace("ALTER TABLE ONLY ","ALTER TABLE ").replace(" ON ONLY "," ON ")
    return s

for s in live:
    t_fingerprint(s); t_outbox(s); t_guard(s); t_health(s); t_barrier_callers(s); t_only(s)

# drop comments that name removed functions
before=len(live)
live=[s for s in live if not (s['type']=='COMMENT' and any(d in s['body'] for d in DROPPED_OBJECTS))]
print(f"устаревших комментариев убрано: {before-len(live)}")

# insert the replacement barrier before its first caller
idx=next(i for i,s in enumerate(live)
         if s['type']=='FUNCTION' and s['name'].startswith('anomaly_operational_metrics'))
live.insert(idx, NEW_BARRIER)

# ---------- ordering ----------
VIEWS={'publication_analysis_state_public','publication_anomaly_finding_public',
       'usable_publication_snapshot','visible_institution','visible_platform_account',
       'account_metric_snapshot_active','publication_metric_snapshot_active',
       'publication_metric_snapshot_resolved','visible_publication','schema_contract',
       'official_institution_rating_observation'}
def needs_views(s):
    return s['type']=='FUNCTION' and any(re.search(r'\b'+v+r'\b', s['body']) for v in VIEWS)

DEFAULT_PARTITIONS = {
 'schema':'ingest', 'type':'TABLE', 'name':'default partitions',
 'body':"""-- Страховочные партиции: ловят строки вне объявленных диапазонов,
-- чтобы вставка падала на проверке месяца, а не на отсутствии партиции.
CREATE TABLE ingest.publication_metric_snapshot_default
    PARTITION OF ingest.publication_metric_snapshot DEFAULT;

CREATE TABLE ingest.reaction_breakdown_default
    PARTITION OF ingest.reaction_breakdown DEFAULT;"""}
idx_ing = max(i for i,s in enumerate(live) if s['type']=='TABLE' and s['schema']=='ingest')
live.insert(idx_ing+1, DEFAULT_PARTITIONS)

LAYOUT=[
 ('0001_schemas.sql','схемы',                       lambda s: s['type']=='SCHEMA'),
 ('0002_types.sql','перечисления и домены',         lambda s: s['type']=='TYPE'),
 ('0003_tables_catalog.sql','catalog — справочник учреждений и аккаунтов', lambda s: s['type']=='TABLE' and s['schema']=='catalog'),
 ('0004_tables_ingest.sql','ingest — сырые наблюдения и партиции',         lambda s: s['type']=='TABLE' and s['schema']=='ingest'),
 ('0005_tables_rating.sql','rating — формулы и результаты',                lambda s: s['type']=='TABLE' and s['schema']=='rating'),
 ('0006_tables_analytics.sql','analytics — производные данные и анализ',   lambda s: s['type']=='TABLE' and s['schema']=='analytics'),
 ('0007_tables_ops.sql','ops_and_admin — эксплуатация и аудит',            lambda s: s['type']=='TABLE' and s['schema']=='ops_and_admin'),
 ('0008_identity_columns.sql','identity-колонки',   lambda s: s['type']=='SEQUENCE'),
 ('0009_constraints.sql','ключи, уникальность, CHECK', lambda s: s['type'] in ('CONSTRAINT','CHECK CONSTRAINT')),
 ('0010_indexes.sql','индексы — объявлены на родительских партиционированных таблицах', lambda s: s['type']=='INDEX'),
 ('0011_functions_base.sql','функции, не зависящие от представлений', lambda s: s['type']=='FUNCTION' and not needs_views(s)),
 ('0012_views.sql','представления',                 lambda s: s['type']=='VIEW'),
 ('0013_functions.sql','функции поверх представлений', lambda s: s['type']=='FUNCTION' and needs_views(s)),
 ('0014_triggers.sql','триггеры',                   lambda s: s['type']=='TRIGGER'),
 ('0015_foreign_keys.sql','внешние ключи',          lambda s: s['type']=='FK CONSTRAINT'),
 ('0016_comments.sql','комментарии',                lambda s: s['type']=='COMMENT'),
]

OUT.mkdir(parents=True, exist_ok=True)
# Стираем только те файлы, которые порождает этот скрипт: каталог делят
# grants.py и написанные вручную миграции, и снести их было бы потерей.
OWNED = {name for name, _title, _pred in LAYOUT}
for f in OUT.glob('*.sql'):
    if f.name in OWNED:
        f.unlink()
seen=set(); total=0
for fname,title,pred in LAYOUT:
    part=[s for s in live if pred(s) and id(s) not in seen]
    for s in part: seen.add(id(s))
    L=[f"-- {fname[:4]} — {title}","-- Порождается из каталога эталонной базы; см. db/README.md.",""]
    for s in part:
        L.append(f"-- {s['schema']}.{s['name']}" if s['schema'] not in ('-','') else f"-- {s['name']}")
        L.append(s['body']); L.append("")
    (OUT/fname).write_text("\n".join(L)); total+=len(part)
    print(f"  {fname:30} {len(part):4} объектов")
print(f"\nразмещено {total} из {len(live)}")
