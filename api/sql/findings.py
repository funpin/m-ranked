# api/sql/findings.py
"""«Находки»: посты выше нормы своего аккаунта.

Норма — медиана значения на одном и том же возрасте поста (1, 3, 6, 12 или
24 часа) по постам аккаунта за 30 дней до as_of, без постов с действующим
уровнем аномалии 2–3. Пост сравнивается на самой поздней своей точке не
старше суток: у молодого поста это 6 или 12 часов, и норма берётся на том же
часу. Значения на фиксированных часах лежат готовыми в
analytics.publication_checkpoint, поэтому снимки запрос не читает — кроме
разбивки реакций последнего снимка, и только для строк страницы.

Тот же расчёт идёт для комментариев и репостов (если площадка их отдаёт):
при сортировке «Обсуждаемые» или «Репостят» «выше нормы» означает выше нормы
по этому показателю.
"""
from __future__ import annotations

from ..statistics_capabilities import INTERACTION_COMPONENTS, PLATFORM_METRIC_CAPABILITIES
from .statistics import SEARCH_PREDICATE


def _capability(platform: str) -> str:
    """Флаги «площадка отдаёт показатель» выражениями по самой площадке.

    Раньше флаги приходили соединением с VALUES-таблицей возможностей; на нём
    планировщик оценивал 328 аккаунтов как 7 строк и читал контрольные точки
    поштучно по индексу: сотни тысяч блоков вместо десятка тысяч.
    """
    def supported(metric: str) -> str:
        platforms = ",".join(f"'{name}'" for name, metrics in PLATFORM_METRIC_CAPABILITIES.items()
                             if metric in metrics)
        return f"({platform}) IN ({platforms})" if platforms else "false"
    flags = ",".join(f"{supported(metric)} AS {metric}_supported" for metric in INTERACTION_COMPONENTS)
    return f"CROSS JOIN LATERAL (SELECT {flags}) capability"

_INTERACTIONS = """
CASE WHEN (NOT capability.reactions_supported OR checkpoint.reactions_count IS NULL)
       AND (NOT capability.comments_supported OR checkpoint.comments_count IS NULL)
       AND (NOT capability.shares_supported OR checkpoint.shares_count IS NULL)
  THEN NULL
  ELSE (CASE WHEN capability.reactions_supported THEN coalesce(checkpoint.reactions_count,0) ELSE 0 END)
     + (CASE WHEN capability.comments_supported THEN coalesce(checkpoint.comments_count,0) ELSE 0 END)
     + (CASE WHEN capability.shares_supported THEN coalesce(checkpoint.shares_count,0) ELSE 0 END)
END::bigint
"""

# Действующий уровень — как на панели сравнения: ручная перепроверка
# понижает сохранённый уровень, пока анализ поста не обновился.
def _level(window_start: str) -> str:
    """Соединение с анализом аномалий. Окно по published_at состояния (оно
    повторяет дату поста) даёт планировщику верную оценку числа строк, и он
    строит хэш вместо десятков тысяч поисков по индексу. Запас в двое суток
    прощает уточнённую позже дату поста."""
    return f"""
LEFT JOIN analytics.post_anomaly_state state ON state.publication_id=publication.id
 AND state.analyzed_at IS NOT NULL AND state.published_at>{window_start}-interval '2 days'
LEFT JOIN analytics.post_anomaly_context_recheck recheck ON recheck.publication_id=publication.id
 AND recheck.source_analyzed_at=state.analyzed_at AND recheck.source_level=state.level
 AND state.review_status='unreviewed'
"""

# Нормы аккаунтов за 30 дней не зависят от фильтров страницы и меняются
# медленно: их считает отдельный запрос сразу для всех аккаунтов, а маршрут
# держит результат в кэше процесса и передаёт в FINDINGS параметром.
NORMS = f"""
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,
           %(as_of)s::timestamptz-make_interval(days=>%(norm_days)s) AS norm_cutoff
), posts AS MATERIALIZED (
    -- Уровень анализа — на пост, до контрольных точек: иначе соединение с
    -- анализом шло бы по каждой точке (сотни тысяч поисков на проде).
    SELECT publication.id AS publication_id,publication.published_at,account.id AS account_id,
           account.platform::text AS platform
      FROM params
      JOIN ingest.visible_publication publication
        ON publication.published_at>params.norm_cutoff AND publication.published_at<=params.as_of
      JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id AND account.enabled
      {_level('params.norm_cutoff')}
     WHERE coalesce(recheck.effective_level,state.level,0)<2
), points AS (
    SELECT posts.account_id,checkpoint.hour_offset,checkpoint.views_count AS views,
           CASE WHEN capability.comments_supported THEN checkpoint.comments_count END AS comments,
           CASE WHEN capability.shares_supported THEN checkpoint.shares_count END AS shares,
           {_INTERACTIONS} AS interactions
      FROM params
      JOIN posts ON true
      {_capability("posts.platform")}
      JOIN analytics.publication_checkpoint checkpoint ON checkpoint.publication_id=posts.publication_id
       AND checkpoint.hour_offset<=24
       AND posts.published_at+checkpoint.hour_offset*interval '1 hour'<=params.as_of
)
SELECT account_id,hour_offset,
       count(interactions)::integer AS interaction_sample,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY interactions) AS interaction_norm,
       count(views)::integer AS view_sample,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY views) AS view_norm,
       count(comments)::integer AS comment_sample,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY comments) AS comment_norm,
       count(shares)::integer AS share_sample,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY shares) AS share_norm
  FROM points
 GROUP BY account_id,hour_offset
"""

FINDINGS = f"""
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,
           %(as_of)s::timestamptz-make_interval(days=>%(period_days)s) AS cutoff
), accounts AS MATERIALIZED (
    SELECT account.id AS account_id,account.platform::text AS platform,account.institution_id,
           account.current_username,account.current_title,
           institution.canonical_name AS institution_canonical_name,
           institution.short_name AS institution_short_name,
           institution_alias.legacy_id AS institution_legacy_id
      FROM catalog.visible_platform_account account
      JOIN catalog.visible_institution institution ON institution.id=account.institution_id
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=institution.id AND alias.entity_type='institutions'
           ORDER BY alias.legacy_id LIMIT 1) institution_alias ON true
     WHERE account.enabled
       AND (%(platform)s='all' OR account.platform::text=%(platform)s)
       AND (%(institution_legacy_id)s::bigint IS NULL
            OR institution_alias.legacy_id=%(institution_legacy_id)s::bigint)
), published AS MATERIALIZED (
    -- Уровень считается на пост, а не на каждую его точку: так соединения с
    -- анализом идут по ~25 тыс. постам, а не по ~130 тыс. точкам.
    -- Только посты периода: нормы уже посчитаны отдельно (NORMS).
    SELECT publication.id AS publication_id,publication.published_at,accounts.account_id,
           accounts.platform,publication.publication_type::text AS publication_type,
           coalesce(recheck.effective_level,state.level) AS level
      FROM params
      JOIN ingest.visible_publication publication
        ON publication.published_at>params.cutoff AND publication.published_at<=params.as_of
      JOIN accounts ON accounts.account_id=publication.primary_account_id
      {_level('params.cutoff')}
), measured AS MATERIALIZED (
    SELECT published.publication_id,published.account_id,checkpoint.hour_offset,
           checkpoint.views_count AS views,checkpoint.reactions_count AS reactions,
           CASE WHEN capability.comments_supported THEN checkpoint.comments_count END AS comments,
           CASE WHEN capability.shares_supported THEN checkpoint.shares_count END AS shares,
           {_INTERACTIONS} AS interactions,published.level
      FROM params
      JOIN published ON true
      {_capability("published.platform")}
      JOIN analytics.publication_checkpoint checkpoint ON checkpoint.publication_id=published.publication_id
       AND checkpoint.hour_offset<=24
       -- Точка «из будущего» относительно as_of ещё не наступила для этой ревизии.
       AND published.published_at+checkpoint.hour_offset*interval '1 hour'<=params.as_of
), norms AS (
    SELECT * FROM jsonb_to_recordset(%(norms)s::jsonb) AS norms(
        account_id uuid,hour_offset integer,interaction_sample integer,interaction_norm double precision,
        view_sample integer,view_norm double precision,comment_sample integer,comment_norm double precision,
        share_sample integer,share_norm double precision)
), latest_point AS (
    -- Самая поздняя непустая точка не старше суток. Пустая строка на 24-м
    -- часу (сбор пропустил этот час) не скрывает значение на 12-м.
    SELECT DISTINCT ON (publication_id) publication_id,hour_offset,views,reactions,comments,shares,interactions
      FROM measured
     WHERE views IS NOT NULL OR interactions IS NOT NULL
     ORDER BY publication_id,hour_offset DESC
), candidates AS (
    -- Всё о посте уже есть в published: ни публикации, ни анализ повторно не
    -- читаются. Псевдоним publication и поле id нужны SEARCH_PREDICATE.
    SELECT publication.publication_id,publication.published_at,publication.publication_type,
           accounts.*,publication.level
      FROM (SELECT published.*,published.publication_id AS id FROM published) publication
      JOIN accounts ON accounts.account_id=publication.account_id
      JOIN catalog.visible_platform_account account ON account.id=accounts.account_id
      JOIN catalog.visible_institution institution ON institution.id=accounts.institution_id
     WHERE (cardinality(%(types)s::text[])=0
            OR CASE WHEN publication.publication_type IN ('text','photo','album','video')
                    THEN publication.publication_type ELSE 'other' END = ANY(%(types)s::text[]))
       AND {SEARCH_PREDICATE}
), scored AS (
    SELECT candidates.*,point.hour_offset AS age_hours,point.views,point.reactions,point.comments,
           point.shares,point.interactions,norms.interaction_norm,norms.view_norm,
           norms.comment_norm,norms.share_norm,
           coalesce(norms.interaction_sample,0) AS norm_sample,
           CASE WHEN norms.interaction_sample>=%(min_sample)s AND point.interactions IS NOT NULL
                THEN point.interactions::numeric
                     /greatest(norms.interaction_norm,%(interaction_floor)s)::numeric END AS interaction_index,
           CASE WHEN norms.view_sample>=%(min_sample)s AND point.views IS NOT NULL
                THEN point.views::numeric/greatest(norms.view_norm,%(view_floor)s)::numeric END AS view_index,
           CASE WHEN norms.comment_sample>=%(min_sample)s AND point.comments IS NOT NULL
                THEN point.comments::numeric/greatest(norms.comment_norm,%(comment_floor)s)::numeric END AS comment_index,
           CASE WHEN norms.share_sample>=%(min_sample)s AND point.shares IS NOT NULL
                THEN point.shares::numeric/greatest(norms.share_norm,%(share_floor)s)::numeric END AS share_index,
           CASE WHEN point.interactions IS NOT NULL AND point.views>0
                THEN point.interactions::numeric*100/point.views END AS erv,
           coalesce(point.hour_offset<24
                    AND candidates.published_at+interval '24 hours'>(SELECT as_of FROM params),
                    false) AS preliminary
      FROM candidates
      LEFT JOIN latest_point point ON point.publication_id=candidates.publication_id
      LEFT JOIN norms ON norms.account_id=candidates.account_id AND norms.hour_offset=point.hour_offset
), eligible AS (
    SELECT scored.*,
           (%(mode)s='institution' OR CASE %(sort)s
              WHEN 'comment_index' THEN comment_index>=%(min_index)s AND comments>=%(min_comments)s
              WHEN 'share_index' THEN share_index>=%(min_index)s AND shares>=%(min_shares)s
              ELSE interaction_index>=%(min_index)s AND interactions>=%(min_interactions)s
            END) AS above_norm
      FROM scored
), visible AS (
    SELECT eligible.*,
           CASE %(sort)s WHEN 'view_index' THEN view_index
             WHEN 'comment_index' THEN comment_index
             WHEN 'share_index' THEN share_index
             WHEN 'interactions24' THEN interactions::numeric
             WHEN 'views24' THEN views::numeric
             WHEN 'erv24' THEN erv
             WHEN 'published_at' THEN extract(epoch FROM published_at)::numeric
             ELSE interaction_index END AS sort_value
      FROM eligible
     WHERE above_norm AND (NOT %(exclude_anomalies)s OR coalesce(level,0)<2)
), ranked AS (
    SELECT visible.*,
           row_number() OVER(ORDER BY
             CASE WHEN %(direction)s='desc' THEN sort_value END DESC NULLS LAST,
             CASE WHEN %(direction)s='asc' THEN sort_value END ASC NULLS LAST,
             published_at DESC,publication_id DESC) AS rank,
           row_number() OVER(PARTITION BY institution_id ORDER BY
             CASE WHEN %(direction)s='desc' THEN sort_value END DESC NULLS LAST,
             CASE WHEN %(direction)s='asc' THEN sort_value END ASC NULLS LAST,
             published_at DESC,publication_id DESC) AS institution_rank,
           count(*) OVER(PARTITION BY institution_id)::integer AS institution_finding_count,
           count(*) OVER()::integer AS total
      FROM visible
), page AS (
    SELECT * FROM ranked
     WHERE (%(group)s='none' AND rank<=%(cap)s) OR (%(group)s='institution' AND institution_rank<=3)
), post_curve AS (
    -- Как пост набирал взаимодействия по часам — только для строк страницы.
    SELECT measured.publication_id,
           jsonb_object_agg(measured.hour_offset::text,measured.interactions) AS post_curve
      FROM measured JOIN page ON page.publication_id=measured.publication_id
     WHERE measured.interactions IS NOT NULL
     GROUP BY measured.publication_id
), norm_curve AS (
    SELECT norms.account_id,
           jsonb_object_agg(norms.hour_offset::text,norms.interaction_norm) AS norm_curve
      FROM norms
     WHERE norms.interaction_sample>=%(min_sample)s
       AND norms.account_id IN (SELECT account_id FROM page)
     GROUP BY norms.account_id
), summary AS (
    -- Посты, которые попали бы в выдачу, если бы не аномалия 2–3.
    SELECT count(*) FILTER (WHERE %(exclude_anomalies)s AND above_norm AND level>=2)::integer AS hidden_anomalous FROM eligible
)
SELECT page.*,summary.hidden_anomalous,identity.external_id,identity.public_url,
       post_curve.post_curve,norm_curve.norm_curve,reactions.top_reactions
  FROM summary
  LEFT JOIN page ON true
  LEFT JOIN post_curve ON post_curve.publication_id=page.publication_id
  LEFT JOIN norm_curve ON norm_curve.account_id=page.account_id
  LEFT JOIN analytics.publication_latest latest ON latest.publication_id=page.publication_id
  -- Топ реакций последнего снимка: разбивка приходит с точкой — горячей или
  -- упакованной (0059). Наружу идут только метки и счётчики.
  LEFT JOIN LATERAL (
      SELECT jsonb_agg(jsonb_build_object('reaction',top.reaction_key,'count',top.reaction_count)
                       ORDER BY top.reaction_count DESC,top.reaction_key) AS top_reactions
        FROM (SELECT breakdown.reaction_key,breakdown.reaction_count
                FROM ingest.publication_point_by_id(
                       page.publication_id, date_trunc('month',page.published_at AT TIME ZONE 'UTC')::date,
                       (latest.source_snapshot_refs->>'reactions')::bigint) point
               CROSS JOIN LATERAL (SELECT item.key AS reaction_key, item.value::bigint AS reaction_count
                                     FROM jsonb_each(point.reaction_breakdown) item) breakdown
               WHERE breakdown.reaction_count>0 AND length(breakdown.reaction_key)<=200
                 AND breakdown.reaction_key!~'[[:cntrl:]]' AND breakdown.reaction_key!~'://'
               ORDER BY breakdown.reaction_count DESC,breakdown.reaction_key
               LIMIT %(top_reactions)s) top
  ) reactions ON true
  LEFT JOIN LATERAL (
      SELECT value.external_id,value.public_url FROM ingest.publication_identity value
       WHERE value.publication_id=page.publication_id AND value.role='primary'
       ORDER BY value.id LIMIT 1) identity ON true
 ORDER BY page.rank
"""

INSTITUTIONS = """
SELECT DISTINCT ON (institution.id) alias.legacy_id,institution.short_name,institution.canonical_name
  FROM catalog.visible_institution institution
  JOIN catalog.visible_platform_account account ON account.institution_id=institution.id AND account.enabled
  JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
 ORDER BY institution.id,alias.legacy_id
"""
