"""SQL прогноза М-Рейтинга: агрегаты ночного задания и чтение снимков."""

# Площадки наших вузов (с действующим кодом m-rating) за месяц по Москве.
# Аккаунт покрывает месяц, если включён и либо был в каталоге с начала месяца,
# либо его догруженная история начинается раньше месяца. Вуз без аккаунтов на
# VK/MAX/Rutube остаётся одной строкой с platform IS NULL.
PLATFORM_MONTH = """
WITH coded AS (
    SELECT code.institution_id, code.external_id AS code, institution.canonical_name AS name
      FROM catalog.institution_external_id code
      JOIN catalog.visible_institution institution ON institution.id = code.institution_id
     WHERE code.namespace = 'm-rating' AND code.valid_to IS NULL
), account AS (
    SELECT account.id, account.institution_id, account.platform::text AS platform,
           account.enabled AND (account.created_at <= %(window_start)s OR EXISTS (
               SELECT 1 FROM ingest.publication earliest
                WHERE earliest.primary_account_id = account.id
                  AND earliest.published_at < %(window_start)s)) AS covered
      FROM catalog.visible_platform_account account
      JOIN coded ON coded.institution_id = account.institution_id
     WHERE account.platform IN ('vk', 'max', 'rutube')
), platform_month AS (
    SELECT account.institution_id, account.platform, bool_and(account.covered) AS covered,
           count(publication.id) AS posts,
           count(latest.views_count) FILTER (WHERE publication.published_at <= %(mature_before)s) AS mature_posts,
           coalesce(sum(latest.views_count) FILTER (WHERE publication.published_at <= %(mature_before)s), 0) AS mature_views,
           coalesce(sum(coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
                        + coalesce(latest.shares_count, 0))
                    FILTER (WHERE publication.published_at <= %(mature_before)s
                              AND latest.views_count IS NOT NULL), 0) AS mature_interactions,
           count(latest.views_count) AS viewed_posts,
           coalesce(sum(latest.views_count), 0) AS views,
           coalesce(sum(coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
                        + coalesce(latest.shares_count, 0)) FILTER (WHERE latest.views_count IS NOT NULL), 0)
               AS interactions
      FROM account
      LEFT JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND publication.published_at >= %(window_start)s AND publication.published_at < %(window_end)s
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id = publication.id
     GROUP BY account.institution_id, account.platform
)
SELECT coded.institution_id::text AS institution_id, coded.code, coded.name, platform_month.platform,
       platform_month.posts, platform_month.mature_posts, platform_month.mature_views,
       platform_month.mature_interactions, platform_month.viewed_posts, platform_month.views,
       platform_month.interactions, platform_month.covered
  FROM coded LEFT JOIN platform_month ON platform_month.institution_id = coded.institution_id
 ORDER BY coded.code, platform_month.platform
"""

# Месяц — один снимок: настоящий прогноз (итоговый, бегущий) важнее ретроспективы.
_BEST_RUN = """
    SELECT DISTINCT ON (run.window_start) run.id, run.as_of, run.window_start, run.parameters, formula.version
      FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = %(formula_key)s {filter}
     ORDER BY run.window_start, (run.parameters->>'status' = 'retrospective'), run.as_of DESC
"""

FORECAST_MONTHS = f"""
SELECT to_char(best.window_start AT TIME ZONE 'Europe/Moscow', 'YYYY-MM') AS month,
       best.parameters->>'status' AS status, best.as_of
  FROM ({_BEST_RUN.format(filter="")}) best
 ORDER BY best.window_start DESC
"""

FORECAST_RUN = _BEST_RUN.format(filter="AND run.window_start = %(window_start)s")

FORECAST_ROWS = """
WITH actual AS (
    SELECT DISTINCT ON (observation.institution_id, observation.category)
           observation.institution_id, observation.category, observation.rank, observation.score
      FROM rating.official_institution_rating_observation observation
     WHERE observation.period = %(period)s AND observation.category IN ('social', 'max', 'vk', 'rutube')
     ORDER BY observation.institution_id, observation.category, observation.fetched_at DESC
)
SELECT result.institution_id::text AS institution_id, alias.legacy_id, institution.canonical_name AS name,
       institution.short_name, result.score, result.rank, result.explanation,
       (SELECT jsonb_object_agg(actual.category, jsonb_build_object('rank', actual.rank, 'score', actual.score))
          FROM actual WHERE actual.institution_id = result.institution_id) AS actual
  FROM rating.rating_result result
  JOIN catalog.institution institution ON institution.id = result.institution_id
  LEFT JOIN catalog.legacy_entity_alias alias
    ON alias.entity_type = 'institutions' AND alias.target_uuid = result.institution_id
 WHERE result.rating_run_id = %(run_id)s
 ORDER BY result.rank, institution.canonical_name
"""

# Прогноз опубликованного месяца против факта — для типичных ошибок следующих снимков.
PUBLISHED_SNAPSHOT_SCORES = f"""
WITH best AS ({_BEST_RUN.format(filter="AND run.window_start = %(window_start)s")})
SELECT result.institution_id::text AS institution_id, category.key AS category,
       (result.explanation->'categories'->category.key->>'score')::float8 AS predicted,
       (SELECT observation.score::float8 FROM rating.official_institution_rating_observation observation
         WHERE observation.institution_id = result.institution_id AND observation.category = category.key
           AND observation.period = %(period)s
         ORDER BY observation.fetched_at DESC LIMIT 1) AS actual
  FROM best
  JOIN rating.rating_result result ON result.rating_run_id = best.id
 CROSS JOIN (VALUES ('social'), ('max'), ('vk'), ('rutube')) AS category(key)
"""
