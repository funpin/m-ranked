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
    previous_publication_count,
    previous_total_views, previous_median_views,
    previous_total_reactions, previous_median_reactions,
    previous_total_comments, previous_median_comments,
    previous_total_shares, previous_median_shares,
    computed_as_of)
WITH params AS (
    SELECT (SELECT max(committed_at) FROM analytics.dataset_revision) AS as_of
), periods(period, duration) AS (
    VALUES ('3h', interval '3 hours'),
           ('1d', interval '1 day'),
           ('7d', interval '7 days'),
           ('30d', interval '30 days')
), overview_growth AS MATERIALIZED (
       -- Прирост за окно считается от значения на его границе. Если снимка
       -- до начала окна нет, сравнивать не с чем, и весь накопленный за всю
       -- жизнь публикации счётчик нельзя выдавать за прирост суток: так пост,
       -- вышедший год назад и впервые измеренный сегодня, приносил в «за сутки»
       -- миллионы просмотров. Исключение одно — публикация вышла внутри окна:
       -- тогда всё, что она набрала, действительно набрано в этом окне.
SELECT period.period,
       params.as_of,
       latest.platform_account_id,
       latest.institution_id,
       latest.platform::text AS platform,
       -- PostgreSQL greatest(NULL, 0) возвращает 0: недоступный счётчик
       -- нужно отсеять до ветки нового поста, иначе он превращается в
       -- измеренный ноль и завышает покрытие, особенно в общем разрезе.
       CASE WHEN latest.views_count IS NULL OR latest.views_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.views_count IS NOT NULL
              THEN greatest(latest.views_count - opening.views_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration
              THEN greatest(latest.views_count, 0)
            ELSE NULL END AS views_count,
       CASE WHEN latest.reactions_count IS NULL OR latest.reactions_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.reactions_count IS NOT NULL
              THEN greatest(latest.reactions_count - opening.reactions_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration
              THEN greatest(latest.reactions_count, 0)
            ELSE NULL END AS reactions_count,
       CASE WHEN latest.comments_count IS NULL OR latest.comments_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.comments_count IS NOT NULL
              THEN greatest(latest.comments_count - opening.comments_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration
              THEN greatest(latest.comments_count, 0)
            ELSE NULL END AS comments_count,
       CASE WHEN latest.shares_count IS NULL OR latest.shares_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.shares_count IS NOT NULL
              THEN greatest(latest.shares_count - opening.shares_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration
              THEN greatest(latest.shares_count, 0)
            ELSE NULL END AS shares_count,
       -- Прошлое окно той же длины: от значения на два окна назад до значения
       -- на границе текущего. Считать нечего, когда наблюдений на дальней
       -- границе ещё нет — тогда сравнивать не с чем, и здесь пусто.
       opening.observed_at IS NOT NULL AS has_previous,
       CASE WHEN opening.views_count IS NULL THEN NULL
            WHEN earlier.views_count IS NOT NULL
              THEN greatest(opening.views_count - earlier.views_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration - period.duration
              THEN greatest(opening.views_count, 0)
            ELSE NULL END AS previous_views,
       CASE WHEN opening.reactions_count IS NULL THEN NULL
            WHEN earlier.reactions_count IS NOT NULL
              THEN greatest(opening.reactions_count - earlier.reactions_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration - period.duration
              THEN greatest(opening.reactions_count, 0)
            ELSE NULL END AS previous_reactions,
       CASE WHEN opening.comments_count IS NULL THEN NULL
            WHEN earlier.comments_count IS NOT NULL
              THEN greatest(opening.comments_count - earlier.comments_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration - period.duration
              THEN greatest(opening.comments_count, 0)
            ELSE NULL END AS previous_comments,
       CASE WHEN opening.shares_count IS NULL THEN NULL
            WHEN earlier.shares_count IS NOT NULL
              THEN greatest(opening.shares_count - earlier.shares_count, 0)
            WHEN publication.published_at >= params.as_of - period.duration - period.duration
              THEN greatest(opening.shares_count, 0)
            ELSE NULL END AS previous_shares
  FROM analytics.publication_latest latest
  JOIN catalog.visible_platform_account account ON account.id = latest.platform_account_id
  JOIN catalog.visible_institution institution ON institution.id = latest.institution_id
  JOIN ingest.publication publication ON publication.id = latest.publication_id
 CROSS JOIN params
 CROSS JOIN periods period
  -- Открывающее значение: последний снимок до начала окна. Месяц публикации
  -- передаётся явно, иначе поиск пойдёт по всем партициям снимков.
  -- Все версии, как по сырой таблице. Горячая точка — по таблице снимков в
  -- партиции месяца поста, упакованная (0059) — из массивов поста; берётся
  -- более поздняя. Общая функция publication_last_valid_at ищет то же в 5–10
  -- раз дольше, а внутри LATERAL ещё и не встраивается: 06.10 сводка на ней
  -- не укладывалась в десять минут против прежних 30 секунд.
  LEFT JOIN LATERAL (
      SELECT candidate.views_count, candidate.reactions_count,
             candidate.comments_count, candidate.shares_count,
             candidate.observed_at
        FROM (
          (SELECT snapshot.views_count, snapshot.reactions_count, snapshot.comments_count,
                  snapshot.shares_count, snapshot.observed_at, snapshot.id
             FROM ingest.publication_metric_snapshot snapshot
            WHERE snapshot.published_month = date_trunc('month', publication.published_at)::date
              AND snapshot.publication_id = latest.publication_id
              AND snapshot.observed_at <= params.as_of - period.duration
              AND NOT snapshot.synthetic
              AND snapshot.quality <> 'invalid'
            ORDER BY snapshot.observed_at DESC, snapshot.id DESC
            LIMIT 1)
          UNION ALL
          -- Упакованная: последняя несинтетическая валидная точка по битам кодов
          -- (как в publication_last_valid_at), декодируется одна.
          SELECT packed.views_count, packed.reactions_count, packed.comments_count,
                 packed.shares_count, packed.observed_at, packed.id
            FROM ingest.publication_metric_history history
           CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                                 FROM unnest(history.observed_at, history.codes) WITH ORDINALITY AS u(t, c, o)
                                WHERE u.t <= params.as_of - period.duration AND (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) pick
           CROSS JOIN LATERAL ingest.unpack_history(history, pick.i, pick.i) packed
           WHERE history.publication_id = latest.publication_id
             AND history.first_observed_at <= params.as_of - period.duration AND pick.i IS NOT NULL
             -- Упакованные точки старше всех горячих, кроме поздних строк:
             -- нашлась горячая — массивы не распаковываются.
             AND (history.late_rows OR NOT EXISTS (
                   SELECT 1 FROM ingest.publication_metric_snapshot hot
                    WHERE hot.published_month = date_trunc('month', publication.published_at)::date
                      AND hot.publication_id = latest.publication_id
                      AND hot.observed_at <= params.as_of - period.duration
                      AND NOT hot.synthetic AND hot.quality <> 'invalid'))
        ) candidate
       ORDER BY candidate.observed_at DESC, candidate.id DESC
       LIMIT 1
  ) opening ON true
  -- Дальняя граница прошлого окна. Поиск тот же и по тому же индексу, только
  -- отступ вдвое больше.
  LEFT JOIN LATERAL (
      SELECT candidate.views_count, candidate.reactions_count,
             candidate.comments_count, candidate.shares_count
        FROM (
          (SELECT snapshot.views_count, snapshot.reactions_count, snapshot.comments_count,
                  snapshot.shares_count, snapshot.observed_at, snapshot.id
             FROM ingest.publication_metric_snapshot snapshot
            WHERE snapshot.published_month = date_trunc('month', publication.published_at)::date
              AND snapshot.publication_id = latest.publication_id
              AND snapshot.observed_at <= params.as_of - period.duration - period.duration
              AND NOT snapshot.synthetic
              AND snapshot.quality <> 'invalid'
            ORDER BY snapshot.observed_at DESC, snapshot.id DESC
            LIMIT 1)
          UNION ALL
          -- Упакованная: последняя несинтетическая валидная точка по битам кодов
          -- (как в publication_last_valid_at), декодируется одна.
          SELECT packed.views_count, packed.reactions_count, packed.comments_count,
                 packed.shares_count, packed.observed_at, packed.id
            FROM ingest.publication_metric_history history
           CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                                 FROM unnest(history.observed_at, history.codes) WITH ORDINALITY AS u(t, c, o)
                                WHERE u.t <= params.as_of - period.duration - period.duration AND (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) pick
           CROSS JOIN LATERAL ingest.unpack_history(history, pick.i, pick.i) packed
           WHERE history.publication_id = latest.publication_id
             AND history.first_observed_at <= params.as_of - period.duration - period.duration AND pick.i IS NOT NULL
             -- Упакованные точки старше всех горячих, кроме поздних строк:
             -- нашлась горячая — массивы не распаковываются.
             AND (history.late_rows OR NOT EXISTS (
                   SELECT 1 FROM ingest.publication_metric_snapshot hot
                    WHERE hot.published_month = date_trunc('month', publication.published_at)::date
                      AND hot.publication_id = latest.publication_id
                      AND hot.observed_at <= params.as_of - period.duration - period.duration
                      AND NOT hot.synthetic AND hot.quality <> 'invalid'))
        ) candidate
       ORDER BY candidate.observed_at DESC, candidate.id DESC
       LIMIT 1
  ) earlier ON true
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
       count(*) FILTER (WHERE growth.has_previous)::bigint,
       sum(growth.previous_views)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.previous_views)
             FILTER (WHERE growth.previous_views IS NOT NULL)::numeric, 0),
       sum(growth.previous_reactions)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.previous_reactions)
             FILTER (WHERE growth.previous_reactions IS NOT NULL)::numeric, 0),
       sum(growth.previous_comments)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.previous_comments)
             FILTER (WHERE growth.previous_comments IS NOT NULL)::numeric, 0),
       sum(growth.previous_shares)::numeric,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY growth.previous_shares)
             FILTER (WHERE growth.previous_shares IS NOT NULL)::numeric, 0),
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
