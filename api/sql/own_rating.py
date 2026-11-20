"""SQL «Нашего рейтинга»: аккаунты всех видимых вузов за окно месяца.

Одна строка на аккаунт: покрытие окна сбором, посты и дни с публикациями,
просмотры и взаимодействия зрелых постов, пакеты на постах, ровность отклика
и хвостовой профиль. Площадку и баллы складывает api.own_rating.
"""
from .rating import _SIGNAL_SIZE

# Rutube — по дате загрузки видео (как в М-Рейтинге и формуле), прочие — по дате
# публикации. Загрузка не позже публикации, поэтому published_at >= window_start
# ограничивает и видео: так обе ветки идут по publication_account_published_idx.
# Покрытие: аккаунт собирается с начала окна, если добавлен раньше или его
# история догружена до начала окна; иначе — с даты добавления.
OWN_ACCOUNTS = f"""
WITH account AS (
    SELECT account.id, account.institution_id, account.platform::text AS platform,
           CASE WHEN account.created_at <= %(window_start)s OR EXISTS (
                    SELECT 1 FROM ingest.publication earliest
                     WHERE earliest.primary_account_id = account.id
                       AND earliest.published_at < %(window_start)s)
                THEN %(window_start)s ELSE account.created_at END AS covered_from
      FROM catalog.visible_platform_account account
      JOIN catalog.visible_institution institution ON institution.id = account.institution_id
     WHERE account.enabled AND account.platform IN ('telegram', 'vk', 'max', 'rutube')
), publication AS (
    SELECT account.id AS account_id, publication.id, publication.published_at,
           CASE WHEN account.platform = 'rutube' THEN coalesce(publication.uploaded_at, publication.published_at)
                ELSE publication.published_at END AS counted_at
      FROM account
      JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND publication.published_at >= %(window_start)s
       AND (account.platform = 'rutube' OR publication.published_at < %(window_end)s)
), post AS (
    SELECT publication.account_id, publication.counted_at,
           publication.published_at <= %(mature_before)s AS mature,
           latest.views_count AS views, latest.reactions_count AS reactions,
           coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
               + coalesce(latest.shares_count, 0) AS interactions,
           coalesce(state.discounted_views, 0) AS wave_views,
           CASE WHEN state.level = 3 THEN state.signals END AS signals
      FROM publication
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id = publication.id
      LEFT JOIN analytics.post_anomaly_state state ON state.publication_id = publication.id
     WHERE publication.counted_at >= %(window_start)s AND publication.counted_at < %(window_end)s
), sized AS (
    -- Пакет поста: крупнейший эпизод каждой метрики (сигналы силы ≥ 0.7 у постов
    -- уровня 3, без пробелов в замерах и списаний площадкой), по просмотрам — и
    -- волны/всплески без отклика. NULL-размер — это 0, а не весь пост.
    SELECT post.*,
           CASE WHEN post.views IS NULL THEN 0
                ELSE least(greatest(post.wave_views, coalesce(pack.views, 0)), post.views) END AS pack_views,
           CASE WHEN post.views IS NULL THEN 0
                ELSE least(coalesce(pack.reactions, 0), post.interactions) END AS pack_reactions
      FROM post
      LEFT JOIN LATERAL (
          SELECT max({_SIGNAL_SIZE}) FILTER (WHERE s->>'metric' = 'views') AS views,
                 max({_SIGNAL_SIZE}) FILTER (WHERE s->>'metric' = 'reactions') AS reactions
            FROM jsonb_array_elements(post.signals) s
           WHERE (s->>'strength')::numeric >= 0.7
             AND coalesce(s->'render'->>'kind', '') NOT IN ('gap', 'write_off')
      ) pack ON post.signals IS NOT NULL
), totals AS (
    SELECT account_id, count(*) AS posts,
           count(DISTINCT (counted_at AT TIME ZONE 'Europe/Moscow')::date) AS active_days,
           count(views) FILTER (WHERE mature) AS mature_posts,
           coalesce(sum(views) FILTER (WHERE mature), 0)::bigint AS mature_views,
           coalesce(sum(interactions) FILTER (WHERE mature AND views IS NOT NULL), 0)::bigint AS mature_interactions,
           coalesce(sum(pack_views) FILTER (WHERE mature), 0)::bigint AS mature_pack_views,
           coalesce(sum(pack_reactions) FILTER (WHERE mature), 0)::bigint AS mature_pack_reactions,
           count(views) AS viewed_posts,
           coalesce(sum(views), 0)::bigint AS views,
           coalesce(sum(interactions) FILTER (WHERE views IS NOT NULL), 0)::bigint AS interactions,
           coalesce(sum(pack_views), 0)::bigint AS pack_views,
           coalesce(sum(pack_reactions), 0)::bigint AS pack_reactions,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY reactions) AS median_reactions
      FROM sized GROUP BY account_id
), grouped AS (
    -- Ровность отклика: разброс log реакций внутри дня публикации сверх
    -- пуассоновского, по постам с ≥ 3 реакциями (как в «М-Рейтинге без накрутки»).
    SELECT account_id, reactions, ln(reactions) AS log_r,
           count(*) OVER day_group AS n, avg(ln(reactions)) OVER day_group AS day_mean
      FROM post WHERE reactions >= 3
    WINDOW day_group AS (PARTITION BY account_id, (counted_at AT TIME ZONE 'Europe/Moscow')::date)
), evenness AS (
    SELECT account_id, count(*) FILTER (WHERE n >= 2) AS residuals,
           sqrt(greatest(0, avg((log_r - day_mean) ^ 2 * n / (n - 1)) FILTER (WHERE n >= 2)
                            - avg(1.0 / reactions) FILTER (WHERE n >= 2))) AS evenness
      FROM grouped GROUP BY account_id
), tail AS (
    -- Хвостовые профили своих дат: сколько их, сколько со статусом 2 и средняя
    -- доля поздних реакций сверх медианного хвоста площадки.
    SELECT profile.account_id, count(*) AS profiles, count(*) FILTER (WHERE profile.status = 2) AS confident,
           avg(greatest(0, (profile.metrics->>'lateReactions')::float8
                           - (profile.metrics->>'lateViews')::float8 * (profile.metrics->>'earlyRate')::float8
                             * (profile.metrics->'cohort'->>'median')::float8)
               / nullif((profile.metrics->>'lateReactions')::float8 + (profile.metrics->>'earlyReactions')::float8, 0))
               AS late_share
      FROM analytics.account_tail_profile profile
      JOIN account ON account.id = profile.account_id
     WHERE profile.computed_for >= (%(window_start)s AT TIME ZONE 'Europe/Moscow')::date
       AND profile.computed_for < (%(window_end)s AT TIME ZONE 'Europe/Moscow')::date
       AND profile.status IS NOT NULL
     GROUP BY profile.account_id
)
SELECT account.institution_id::text AS institution_id, account.id::text AS account_id, account.platform,
       greatest(0, extract(epoch FROM %(window_end)s - greatest(account.covered_from, %(window_start)s)) / 86400)::float8
           AS covered_days,
       coalesce(totals.posts, 0) AS posts, coalesce(totals.active_days, 0) AS active_days,
       coalesce(totals.mature_posts, 0) AS mature_posts, coalesce(totals.mature_views, 0) AS mature_views,
       coalesce(totals.mature_interactions, 0) AS mature_interactions,
       coalesce(totals.mature_pack_views, 0) AS mature_pack_views,
       coalesce(totals.mature_pack_reactions, 0) AS mature_pack_reactions,
       coalesce(totals.viewed_posts, 0) AS viewed_posts, coalesce(totals.views, 0) AS views,
       coalesce(totals.interactions, 0) AS interactions, coalesce(totals.pack_views, 0) AS pack_views,
       coalesce(totals.pack_reactions, 0) AS pack_reactions,
       totals.median_reactions::float8 AS median_reactions,
       coalesce(evenness.residuals, 0) AS residuals, evenness.evenness::float8 AS evenness,
       coalesce(tail.profiles, 0) AS profiles, coalesce(tail.confident, 0) AS confident, tail.late_share
  FROM account
  LEFT JOIN totals ON totals.account_id = account.id
  LEFT JOIN evenness ON evenness.account_id = account.id
  LEFT JOIN tail ON tail.account_id = account.id
 ORDER BY account.institution_id, account.platform, account.id
"""

# Все видимые вузы — и без аккаунтов: у них все площадки «нет аккаунта».
OWN_INSTITUTIONS = """
SELECT institution.id::text AS institution_id, institution.canonical_name AS name
  FROM catalog.visible_institution institution
 ORDER BY institution.canonical_name
"""

# Снимок месяца: последняя версия формулы, внутри неё настоящий снимок (бегущий,
# итог в работе или закрытый — свежий) важнее ретроспективы.
_OWN_BEST_RUN = """
    SELECT DISTINCT ON (run.window_start) run.id, run.as_of, run.window_start, run.parameters, formula.version,
           formula.definition
      FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = %(formula_key)s {filter}
     ORDER BY run.window_start, formula.version DESC, (run.parameters->>'status' = 'retrospective'), run.as_of DESC
"""

OWN_MONTHS = f"""
SELECT to_char(best.window_start AT TIME ZONE 'Europe/Moscow', 'YYYY-MM') AS month,
       best.parameters->>'status' AS status, best.as_of
  FROM ({_OWN_BEST_RUN.format(filter="")}) best
 ORDER BY best.window_start DESC
"""

OWN_RUN = _OWN_BEST_RUN.format(filter="AND run.window_start = %(window_start)s")

OWN_ROWS = """
SELECT result.institution_id::text AS institution_id, alias.legacy_id, institution.canonical_name AS name,
       institution.short_name, result.score, result.rank, result.explanation
  FROM rating.rating_result result
  JOIN catalog.institution institution ON institution.id = result.institution_id
  LEFT JOIN catalog.legacy_entity_alias alias
    ON alias.entity_type = 'institutions' AND alias.target_uuid = result.institution_id
 WHERE result.rating_run_id = %(run_id)s
 ORDER BY result.rank, institution.canonical_name
"""
