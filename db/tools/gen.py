import json, pathlib, re, collections
S='/private/tmp/claude-501/-Users-akko-Documents-GitHub-m-ranked/64e9323d-5927-4cea-a794-ff75cdf7819d/scratchpad'
OUT=pathlib.Path('/Users/akko/Documents/GitHub/m-ranked/db/migrations')
kept=json.loads(pathlib.Path(f'{S}/schema/kept.json').read_text())

DROP_TABLES={'analytics.publication_hourly','analytics.comparison_publication_hourly',
             'analytics.comparison_metric_point','analytics.projection_state',
             'flyway.flyway_schema_history'}
DROP_FUNCS={'analytics.rebuild_core_projections','analytics.rebuild_core_projections_v2',
            'analytics.rebuild_core_projections_v5','analytics.rebuild_core_projections_v6',
            'analytics.rebuild_core_projections_v9','analytics.rebuild_core_projections_v11',
            'analytics.rebuild_core_projections_v13','analytics.rebuild_serving_projections',
            'analytics.latest_fully_published_dataset_revision','analytics.refresh_publication_content',
            'ingest.compact_new_metric_evidence','ingest.intern_metric_evidence',
            'ops_and_admin.compact_metric_evidence_batch',
            'ops_and_admin.drop_publication_metric_partition'}
DROP_TRIGGERS={'zz_compact_metric_evidence'}

def qual(s):
    if s['type']=='SCHEMA': return s['name']
    if s['type']=='FUNCTION': return f"{s['schema']}.{s['name'].split('(')[0]}"
    if s['type']=='TRIGGER': return f"{s['schema']}.{s['name'].split()[0]}"
    return f"{s['schema']}.{s['name'].split()[0]}"

TGT=re.compile(r'(?:CREATE (?:UNIQUE )?INDEX \S+ ON (?:ONLY )?|ALTER TABLE (?:ONLY )?|CREATE TRIGGER [\s\S]*?\bON )([a-z_]+\.[a-z_0-9]+)')
def target(s):
    m=TGT.search(s['body']); return m.group(1) if m else ''

dropped=collections.Counter()
def drop(s):
    q=qual(s)
    if s['schema']=='flyway' or q=='flyway': dropped['flyway']+=1; return True
    if s['type']=='TABLE' and q in DROP_TABLES: dropped['table']+=1; return True
    if s['type']=='FUNCTION' and q in DROP_FUNCS: dropped['function']+=1; return True
    if s['type']=='TRIGGER' and s['name'].split()[-1] in DROP_TRIGGERS: dropped['trigger']+=1; return True
    if target(s) in DROP_TABLES: dropped['dep_'+s['type'].replace(' ','_')]+=1; return True
    if s['type']=='SEQUENCE' and q.replace('_id_seq','') in DROP_TABLES: dropped['sequence']+=1; return True
    return False

live=[s for s in kept if not drop(s)]
print("REMOVED:", dict(dropped), "total", sum(dropped.values()))
print("LIVE:", len(live))
for t,c in collections.Counter(s['type'] for s in live).most_common(): print(f"   {t:20} {c}")
pathlib.Path(f'{S}/schema/live.json').write_text(json.dumps(live, ensure_ascii=False, indent=1))
