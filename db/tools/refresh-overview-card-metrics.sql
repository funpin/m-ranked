-- Пересчёт витрины карточек обзора.
--
-- Дорогая часть — поиск значения на начало окна — делается один раз на пару
-- «публикация и период», а не на каждый разрез площадок. Дальше те же строки
-- сворачиваются в пять разрезов: телеграм считается по каналу, остальные и
-- общий — по вузу.
--
-- Замена содержимого идёт одной транзакцией обычными DELETE и INSERT: читатели
-- продолжают видеть прежний снимок и ничего не ждут, а TRUNCATE ради тысячи
-- строк забирал бы исключительную блокировку.
--
-- Промежуточный набор держится в общем выражении, а не во временной таблице:
-- роли обслуживания не выдано право создавать временные таблицы, и ради
-- одного запроса расширять её полномочия незачем.
BEGIN;

SET LOCAL statement_timeout = '10min';
SET LOCAL synchronous_commit = off;

DELETE FROM analytics.overview_card_metrics;

INSERT INTO analytics.overview_card_metrics (
    scope_platform, entity_id, period, publication_count,
    views_samples, total_views, median_views,
    reactions_samples, total_reactions, median_reactions,
    comments_samples, total_comments, median_comments,
    shares_samples, total_shares, median_shares,
    computed_as_of)
WITH params AS (
    SELECT (SELECT max(committed_at) FROM analytics.dataset_revision) AS as_of
), periods(period, duration) AS (
    VALUES ('3h', interval '3 hours'),
           ('1d', interval '1 day'),
           ('7d', interval '7 days'),
           ('30d', interval '30 days')
), overview_growth AS MATERIALIZED (
SELECT period.period,
       params.as_of,
       latest.platform_account_id,
       latest.institution_id,
       latest.platform::text AS platform,
       CASE WHEN latest.views_quality IN ('invalid','suspected_reset') THEN NULL
            ELSE greatest(latest.views_count - coalesce(opening.views_count, 0), 0) END AS views_count,
       CASE WHEN latest.reactions_quality IN ('invalid','suspected_reset') THEN NULL
            ELSE greatest(latest.reactions_count - coalesce(opening.reactions_count, 0), 0) END AS reactions_count,
       CASE WHEN latest.comments_quality IN ('invalid','suspected_reset') THEN NULL
            ELSE greatest(latest.comments_count - coalesce(opening.comments_count, 0), 0) END AS comments_count,
       CASE WHEN latest.shares_quality IN ('invalid','suspected_reset') THEN NULL
            ELSE greatest(latest.shares_count - coalesce(opening.shares_count, 0), 0) END AS shares_count
  FROM analytics.publication_latest latest
  JOIN catalog.visible_platform_account account ON account.id = latest.platform_account_id
  JOIN catalog.visible_institution institution ON institution.id = latest.institution_id
  JOIN ingest.publication publication ON publication.id = latest.publication_id
 CROSS JOIN params
 CROSS JOIN periods period
  -- Открывающее значение: последний снимок до начала окна. Месяц публикации
  -- передаётся явно, иначе поиск пойдёт по всем партициям снимков.
  LEFT JOIN LATERAL (
      SELECT snapshot.views_count, snapshot.reactions_count,
             snapshot.comments_count, snapshot.shares_count
        FROM ingest.publication_metric_snapshot snapshot
       WHERE snapshot.published_month = date_trunc('month', publication.published_at)::date
         AND snapshot.publication_id = latest.publication_id
         AND snapshot.observed_at <= params.as_of - period.duration
         AND NOT snapshot.synthetic
         AND snapshot.quality <> 'invalid'
       ORDER BY snapshot.observed_at DESC, snapshot.id DESC
       LIMIT 1
  ) opening ON true
 WHERE latest.observed_at > params.as_of - period.duration
   AND latest.observed_at <= params.as_of
   AND NOT latest.synthetic
   AND latest.quality <> 'invalid'
)
SELECT scope.scope_platform, scope.entity_id, growth.period,
       count(*)::bigint,
       count(*) FILTER (WHERE growth.views_count IS NOT NULL)::integer,
       sum(growth.views_count)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.views_count)
             FILTER (WHERE growth.views_count IS NOT NULL)::numeric, 0),
       count(*) FILTER (WHERE growth.reactions_count IS NOT NULL)::integer,
       sum(growth.reactions_count)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.reactions_count)
             FILTER (WHERE growth.reactions_count IS NOT NULL)::numeric, 0),
       count(*) FILTER (WHERE growth.comments_count IS NOT NULL)::integer,
       sum(growth.comments_count)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.comments_count)
             FILTER (WHERE growth.comments_count IS NOT NULL)::numeric, 0),
       count(*) FILTER (WHERE growth.shares_count IS NOT NULL)::integer,
       sum(growth.shares_count)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.shares_count)
             FILTER (WHERE growth.shares_count IS NOT NULL)::numeric, 0),
       max(growth.as_of)
  FROM overview_growth growth
  -- Телеграм на экране разбит по каналам, остальные площадки и общий
  -- режим — по вузам. Одна строка прироста попадает в два разреза.
 CROSS JOIN LATERAL (VALUES
     ('all'::text, growth.institution_id),
     (growth.platform, CASE WHEN growth.platform = 'telegram'
                            THEN growth.platform_account_id ELSE growth.institution_id END)
 ) AS scope(scope_platform, entity_id)
 GROUP BY scope.scope_platform, scope.entity_id, growth.period;

COMMIT;
