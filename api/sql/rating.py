"""SQL прогноза М-Рейтинга: агрегаты ночного задания и чтение снимков."""

# Площадки наших вузов (с действующим кодом m-rating) за месяц по Москве.
# Аккаунт покрывает месяц, если включён и либо был в каталоге с начала месяца,
# либо его догруженная история начинается раньше месяца. Вуз без аккаунтов на
# VK/MAX/Rutube остаётся одной строкой с platform IS NULL. uploaded_posts — видео
# Rutube, загруженные в окне (источник считает порог по дате загрузки; без неё —
# по дате публикации); у прочих площадок NULL.
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
), uploaded AS (
    SELECT account.institution_id, count(publication.id) AS uploaded_posts
      FROM account
      JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND coalesce(publication.uploaded_at, publication.published_at) >= %(window_start)s
       AND coalesce(publication.uploaded_at, publication.published_at) < %(window_end)s
     WHERE account.platform = 'rutube'
     GROUP BY account.institution_id
)
SELECT coded.institution_id::text AS institution_id, coded.code, coded.name, platform_month.platform,
       platform_month.posts, platform_month.mature_posts, platform_month.mature_views,
       platform_month.mature_interactions, platform_month.viewed_posts, platform_month.views,
       platform_month.interactions, platform_month.covered,
       CASE WHEN platform_month.platform = 'rutube' THEN coalesce(uploaded.uploaded_posts, 0) END AS uploaded_posts
  FROM coded LEFT JOIN platform_month ON platform_month.institution_id = coded.institution_id
  LEFT JOIN uploaded ON uploaded.institution_id = coded.institution_id AND platform_month.platform = 'rutube'
 ORDER BY coded.code, platform_month.platform
"""

# Месяц — один снимок. Сначала последняя версия формулы (решение владельца
# 20.11.2026: прошлые месяцы показываются ею, ретроспективой), внутри версии
# настоящий прогноз (итоговый, бегущий, опубликованный) важнее ретроспективы.
# Опубликованный прогноз прежней версии остаётся в базе: по нему считаются
# типичные ошибки (PUBLISHED_SNAPSHOT_SCORES).
_BEST_RUN = """
    SELECT DISTINCT ON (run.window_start) run.id, run.as_of, run.window_start, run.parameters, formula.version
      FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = %(formula_key)s {filter}
     ORDER BY run.window_start, formula.version DESC, (run.parameters->>'status' = 'retrospective'), run.as_of DESC
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
# Только снимок до публикации (published): ретроспектива посчитана на данных, где
# подбирались пороги, и её ошибка занижена — диапазоны мест вышли бы вдвое уже.
PUBLISHED_SNAPSHOT_SCORES = f"""
WITH best AS ({_BEST_RUN.format(filter="AND run.window_start = %(window_start)s AND run.parameters->>'status' = 'published'")})
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

# ---- М-Рейтинг без накрутки (api.rating_clean) ----

# Размер эпизода сигнала: поля render у разных признаков разные. Крупнейшее из
# них — оценка снизу числа реакций или просмотров, пришедших пакетом.
_SIGNAL_SIZE = """greatest(
    coalesce((s->'render'->>'episodeGrowth')::numeric, 0),
    CASE WHEN s->>'metric' = 'reactions' THEN coalesce((s->'render'->>'episodeReactions')::numeric, 0)
         ELSE coalesce((s->'render'->>'episodeViews')::numeric, 0) END,
    coalesce((s->'render'->>'burstLower')::numeric, 0),
    coalesce((s->'render'->>'burst')::numeric, 0),
    CASE WHEN s->'render'->>'kind' = 'lead'
         THEN coalesce((s->'render'->>'reactionsDelta')::numeric - (s->'render'->>'expected')::numeric, 0)
         ELSE coalesce((s->'render'->>'actual')::numeric - (s->'render'->>'expected')::numeric, 0) END,
    coalesce((s->'render'->>'slope')::numeric
             * ((s->'render'->>'endAge')::numeric - (s->'render'->>'startAge')::numeric) / 3600, 0))"""

# Накрутка по постам VK и MAX наших вузов за месяц: у поста уровня 3 —
# крупнейший эпизод каждой метрики (сила не ниже 0.7; пробел в замерах и
# списание площадкой не считаются), по просмотрам — и волны/всплески без отклика.
# Зрелые посты — как в PLATFORM_MONTH, чтобы вычитать из того же подмножества.
PLATFORM_INFLATION = f"""
WITH coded AS (
    SELECT code.institution_id, code.external_id AS code
      FROM catalog.institution_external_id code
      JOIN catalog.visible_institution institution ON institution.id = code.institution_id
     WHERE code.namespace = 'm-rating' AND code.valid_to IS NULL
), post AS (
    SELECT coded.code, account.platform::text AS platform,
           publication.published_at <= %(mature_before)s AS mature,
           latest.views_count AS views,
           coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
               + coalesce(latest.shares_count, 0) AS interactions,
           coalesce(state.discounted_views, 0) AS wave_views,
           CASE WHEN state.level = 3 THEN state.signals END AS signals
      FROM catalog.visible_platform_account account
      JOIN coded ON coded.institution_id = account.institution_id
      JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND publication.published_at >= %(window_start)s AND publication.published_at < %(window_end)s
      JOIN analytics.publication_latest latest
        ON latest.publication_id = publication.id AND latest.views_count IS NOT NULL
      LEFT JOIN analytics.post_anomaly_state state ON state.publication_id = publication.id
     WHERE account.platform IN ('vk', 'max')
), sized AS (
    SELECT post.code, post.platform, post.mature,
           least(greatest(post.wave_views, coalesce(pack.views, 0)), post.views) AS removed_views,
           least(coalesce(pack.reactions, 0), post.interactions) AS removed_reactions
      FROM post
      LEFT JOIN LATERAL (
          SELECT max({_SIGNAL_SIZE}) FILTER (WHERE s->>'metric' = 'views') AS views,
                 max({_SIGNAL_SIZE}) FILTER (WHERE s->>'metric' = 'reactions') AS reactions
            FROM jsonb_array_elements(post.signals) s
           WHERE (s->>'strength')::numeric >= 0.7
             AND coalesce(s->'render'->>'kind', '') NOT IN ('gap', 'write_off')
      ) pack ON post.signals IS NOT NULL
)
SELECT code, platform,
       count(*) FILTER (WHERE mature) AS mature_posts,
       coalesce(sum(removed_views) FILTER (WHERE mature), 0)::bigint AS mature_views,
       coalesce(sum(removed_reactions) FILTER (WHERE mature), 0)::bigint AS mature_reactions,
       coalesce(sum(removed_views), 0)::bigint AS views,
       coalesce(sum(removed_reactions), 0)::bigint AS reactions
  FROM sized GROUP BY code, platform
"""

# «Умная» накрутка: ровность отклика внутри дня публикации (разброс log реакций
# сверх пуассоновского, по постам с ≥3 реакциями) и хвост из account_tail_profile
# на конец месяца. Ровность по итоговым реакциям совпадает с ровностью к 72 часам
# (ранговая корреляция 0.98 на октябре 2026), поэтому история не распаковывается.
ACCOUNT_SMART = """
WITH coded AS (
    SELECT code.institution_id, code.external_id AS code
      FROM catalog.institution_external_id code
      JOIN catalog.visible_institution institution ON institution.id = code.institution_id
     WHERE code.namespace = 'm-rating' AND code.valid_to IS NULL
), account AS (
    SELECT account.id, coded.code, account.platform::text AS platform
      FROM catalog.visible_platform_account account
      JOIN coded ON coded.institution_id = account.institution_id
     WHERE account.platform IN ('vk', 'max')
), post AS (
    SELECT account.id AS account_id, publication.published_at <= %(mature_before)s AS mature,
           (publication.published_at AT TIME ZONE 'Europe/Moscow')::date AS day,
           latest.reactions_count AS reactions,
           coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
               + coalesce(latest.shares_count, 0) AS interactions
      FROM account
      JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND publication.published_at >= %(window_start)s AND publication.published_at < %(window_end)s
      JOIN analytics.publication_latest latest
        ON latest.publication_id = publication.id AND latest.views_count IS NOT NULL
), grouped AS (
    SELECT account_id, reactions, ln(reactions) AS log_r,
           count(*) OVER day_group AS n, avg(ln(reactions)) OVER day_group AS day_mean
      FROM post WHERE reactions >= 3
    WINDOW day_group AS (PARTITION BY account_id, day)
), evenness AS (
    SELECT account_id, count(*) FILTER (WHERE n >= 2) AS residuals,
           sqrt(greatest(0, avg((log_r - day_mean) ^ 2 * n / (n - 1)) FILTER (WHERE n >= 2)
                            - avg(1.0 / reactions) FILTER (WHERE n >= 2))) AS evenness
      FROM grouped GROUP BY account_id
), totals AS (
    SELECT account_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY reactions) AS median_reactions,
           coalesce(sum(interactions) FILTER (WHERE mature), 0)::bigint AS mature_interactions,
           coalesce(sum(interactions), 0)::bigint AS interactions
      FROM post GROUP BY account_id
), tail AS (
    SELECT DISTINCT ON (profile.account_id) profile.account_id, profile.metrics
      FROM analytics.account_tail_profile profile
      JOIN account ON account.id = profile.account_id
     WHERE profile.computed_for >= (%(window_start)s AT TIME ZONE 'Europe/Moscow')::date
       AND profile.computed_for < (%(window_end)s AT TIME ZONE 'Europe/Moscow')::date
       AND profile.metrics ? 'ratio'
     ORDER BY profile.account_id, profile.computed_for DESC
)
SELECT account.code, account.platform, evenness.residuals, evenness.evenness::float8 AS evenness,
       totals.median_reactions::float8 AS median_reactions, totals.mature_interactions, totals.interactions,
       (tail.metrics->>'ratio')::float8 AS tail_ratio,
       (tail.metrics->'cohort'->>'p90')::float8 AS tail_p90,
       (tail.metrics->'cohort'->>'median')::float8 AS tail_median,
       (tail.metrics->>'lateReactions')::float8 AS late_reactions,
       (tail.metrics->>'earlyReactions')::float8 AS early_reactions,
       (tail.metrics->>'lateViews')::float8 AS late_views,
       (tail.metrics->>'earlyRate')::float8 AS early_rate
  FROM account
  JOIN totals ON totals.account_id = account.id
  LEFT JOIN evenness ON evenness.account_id = account.id
  LEFT JOIN tail ON tail.account_id = account.id
"""

# Снимок месяца без накрутки. В отличие от прогноза опубликованный месяц
# считается от официальных баллов (ретроспектива) — она важнее ночных снимков,
# сделанных до публикации от прогноза.
_CLEAN_BEST_RUN = """
    SELECT DISTINCT ON (run.window_start) run.id, run.as_of, run.window_start, run.parameters, formula.version
      FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = %(formula_key)s {filter}
     ORDER BY run.window_start, (run.parameters->>'status' = 'retrospective') DESC, formula.version DESC,
              run.as_of DESC
"""

CLEAN_MONTHS = f"""
SELECT to_char(best.window_start AT TIME ZONE 'Europe/Moscow', 'YYYY-MM') AS month,
       best.parameters->>'status' AS status, best.as_of
  FROM ({_CLEAN_BEST_RUN.format(filter="")}) best
 ORDER BY best.window_start DESC
"""

CLEAN_RUN = _CLEAN_BEST_RUN.format(filter="AND run.window_start = %(window_start)s")
