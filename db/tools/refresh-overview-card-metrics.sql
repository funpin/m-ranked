-- Пересчёт витрины карточек обзора.
--
-- Дорогая часть — поиск значений на границах окон — делается один раз на
-- публикацию для всех четырёх периодов, а не на каждую пару «публикация и
-- период» и не на каждый разрез площадок. Дальше строки пар сворачиваются в
-- пять разрезов: телеграм считается по каналу, остальные и общий — по вузу.
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
-- План — сотни тысяч мелких подзапросов, компиляция JIT им не окупается. На
-- копии базы 17.11.2026 этот запрос с jit = off идёт 12,5 с вместо 14,5 с
-- (тёплый кэш) и 18,3 с вместо 22,5 с (холодный), прежний — 47 с вместо
-- 55 с. У ролей api_read и analytics_worker JIT выключен давно, у роли
-- обслуживания — нет.
SET LOCAL jit = off;

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
), periods(period, duration, opening_k, earlier_k) AS (
    -- opening_k и earlier_k — номера двух границ периода среди восьми: начала
    -- окна (as_of − окно) и начала прошлого окна (as_of − два окна).
    VALUES ('3h', interval '3 hours', 1, 2),
           ('1d', interval '1 day', 3, 4),
           ('7d', interval '7 days', 5, 6),
           ('30d', interval '30 days', 7, 8)
), boundary(k, at, window_start) AS (
    -- Те же выражения границ, что и прежде у каждой пары. Граница нужна
    -- публикации, когда та попадает в окно её периода (window_start).
    SELECT period.opening_k, params.as_of - period.duration, params.as_of - period.duration
      FROM params CROSS JOIN periods period
    UNION ALL
    SELECT period.earlier_k, params.as_of - period.duration - period.duration, params.as_of - period.duration
      FROM params CROSS JOIN periods period
), boundaries AS (
    SELECT array_agg(boundary.at ORDER BY boundary.k) AS at FROM boundary
), overview_growth AS MATERIALIZED (
       -- Прирост за окно считается от значения на его границе. Если снимка
       -- до начала окна нет, сравнивать не с чем, и весь накопленный за всю
       -- жизнь публикации счётчик нельзя выдавать за прирост суток: так пост,
       -- вышедший год назад и впервые измеренный сегодня, приносил в «за сутки»
       -- миллионы просмотров. Исключение одно — публикация вышла внутри окна:
       -- тогда всё, что она набрала, действительно набрано в этом окне.
       --
       -- Значения на границах ищутся один раз на публикацию для всех её
       -- периодов (до восьми границ) и складываются в массивы по номеру
       -- границы; пары «публикация и период» берут из них свои два элемента.
       -- Всё идёт потоком, без промежуточных наборов: прежде каждая пара искала
       -- свои границы сама и разворачивала упакованные массивы поста до восьми
       -- раз.
SELECT period.period,
       post.as_of,
       post.platform_account_id,
       post.institution_id,
       post.platform,
       -- PostgreSQL greatest(NULL, 0) возвращает 0: недоступный счётчик
       -- нужно отсеять до ветки нового поста, иначе он превращается в
       -- измеренный ноль и завышает покрытие, особенно в общем разрезе.
       CASE WHEN post.views_count IS NULL OR post.views_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.views_count IS NOT NULL
              THEN greatest(post.views_count - opening.views_count, 0)
            WHEN post.published_at >= post.as_of - period.duration
              THEN greatest(post.views_count, 0)
            ELSE NULL END AS views_count,
       CASE WHEN post.reactions_count IS NULL OR post.reactions_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.reactions_count IS NOT NULL
              THEN greatest(post.reactions_count - opening.reactions_count, 0)
            WHEN post.published_at >= post.as_of - period.duration
              THEN greatest(post.reactions_count, 0)
            ELSE NULL END AS reactions_count,
       CASE WHEN post.comments_count IS NULL OR post.comments_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.comments_count IS NOT NULL
              THEN greatest(post.comments_count - opening.comments_count, 0)
            WHEN post.published_at >= post.as_of - period.duration
              THEN greatest(post.comments_count, 0)
            ELSE NULL END AS comments_count,
       CASE WHEN post.shares_count IS NULL OR post.shares_quality IN ('invalid','suspected_reset') THEN NULL
            WHEN opening.shares_count IS NOT NULL
              THEN greatest(post.shares_count - opening.shares_count, 0)
            WHEN post.published_at >= post.as_of - period.duration
              THEN greatest(post.shares_count, 0)
            ELSE NULL END AS shares_count,
       -- Прошлое окно той же длины: от значения на два окна назад до значения
       -- на границе текущего. Считать нечего, когда наблюдений на дальней
       -- границе ещё нет — тогда сравнивать не с чем, и здесь пусто.
       opening.observed_at IS NOT NULL AS has_previous,
       CASE WHEN opening.views_count IS NULL THEN NULL
            WHEN earlier.views_count IS NOT NULL
              THEN greatest(opening.views_count - earlier.views_count, 0)
            WHEN post.published_at >= post.as_of - period.duration - period.duration
              THEN greatest(opening.views_count, 0)
            ELSE NULL END AS previous_views,
       CASE WHEN opening.reactions_count IS NULL THEN NULL
            WHEN earlier.reactions_count IS NOT NULL
              THEN greatest(opening.reactions_count - earlier.reactions_count, 0)
            WHEN post.published_at >= post.as_of - period.duration - period.duration
              THEN greatest(opening.reactions_count, 0)
            ELSE NULL END AS previous_reactions,
       CASE WHEN opening.comments_count IS NULL THEN NULL
            WHEN earlier.comments_count IS NOT NULL
              THEN greatest(opening.comments_count - earlier.comments_count, 0)
            WHEN post.published_at >= post.as_of - period.duration - period.duration
              THEN greatest(opening.comments_count, 0)
            ELSE NULL END AS previous_comments,
       CASE WHEN opening.shares_count IS NULL THEN NULL
            WHEN earlier.shares_count IS NOT NULL
              THEN greatest(opening.shares_count - earlier.shares_count, 0)
            WHEN post.published_at >= post.as_of - period.duration - period.duration
              THEN greatest(opening.shares_count, 0)
            ELSE NULL END AS previous_shares
  FROM (
     -- Строка публикации со значениями на всех её границах. OFFSET 0 держит
     -- её отдельным узлом: поиск идёт раз на публикацию, а не на пару, и
     -- строки с массивами не материализуются для перебора периодов.
     SELECT params.as_of, latest.observed_at, latest.platform_account_id, latest.institution_id,
            latest.platform::text AS platform, publication.published_at,
            latest.views_count, latest.views_quality, latest.reactions_count, latest.reactions_quality,
            latest.comments_count, latest.comments_quality, latest.shares_count, latest.shares_quality,
            hot.views_count AS hot_views_count,
            hot.reactions_count AS hot_reactions_count,
            hot.comments_count AS hot_comments_count,
            hot.shares_count AS hot_shares_count,
            hot.observed_at AS hot_observed_at,
            hot.id AS hot_id,
            history.late_rows,
            packed.i AS packed_i,
            packed.views_count AS packed_views_count,
            packed.reactions_count AS packed_reactions_count,
            packed.comments_count AS packed_comments_count,
            packed.shares_count AS packed_shares_count,
            packed.observed_at AS packed_observed_at,
            packed.id AS packed_id
       FROM analytics.publication_latest latest
       JOIN catalog.visible_platform_account account ON account.id = latest.platform_account_id
       JOIN catalog.visible_institution institution ON institution.id = latest.institution_id
       JOIN ingest.publication publication ON publication.id = latest.publication_id
       -- Упакованная строка поста приходит хеш-соединением с чтением таблицы
       -- подряд, а не поиском по ключу на каждую публикацию: так и TOAST её
       -- массивов читается ближе к порядку хранения. Подзапрос за OFFSET 0 не
       -- даёт планировщику выбрать поиск по ключу — он недооценивает число
       -- публикаций в окне (14 тыс. вместо 81 тыс.). На холодном кэше копии
       -- 17.11 поиск по ключу читал массивы 285 тыс. страниц с 7,3 с ожидания
       -- диска, соединение — 203 тыс. и 1,3 с.
       LEFT JOIN (SELECT * FROM ingest.publication_metric_history OFFSET 0) history
              ON history.publication_id = latest.publication_id
      CROSS JOIN params
      CROSS JOIN boundaries
  -- Горячее значение на каждой нужной границе: последний снимок не позже
  -- неё. Месяц публикации передаётся явно, иначе поиск пойдёт по всем
  -- партициям снимков. Все версии, как по сырой таблице. Найденная строка
  -- заодно отвечает, есть ли горячая точка до границы. Общая функция
  -- publication_last_valid_at ищет то же в 5–10 раз дольше, а внутри LATERAL
  -- ещё и не встраивается: 06.10 сводка на ней не укладывалась в десять
  -- минут против прежних 30 секунд.
 CROSS JOIN LATERAL (
     SELECT array_agg(snapshot.views_count ORDER BY boundary.k) AS views_count,
            array_agg(snapshot.reactions_count ORDER BY boundary.k) AS reactions_count,
            array_agg(snapshot.comments_count ORDER BY boundary.k) AS comments_count,
            array_agg(snapshot.shares_count ORDER BY boundary.k) AS shares_count,
            array_agg(snapshot.observed_at ORDER BY boundary.k) AS observed_at,
            array_agg(snapshot.id ORDER BY boundary.k) AS id,
            bool_or(latest.observed_at > boundary.window_start AND snapshot.id IS NULL) AS gap
       FROM boundary
       LEFT JOIN LATERAL (
           SELECT snapshot.views_count, snapshot.reactions_count, snapshot.comments_count,
                  snapshot.shares_count, snapshot.observed_at, snapshot.id
             FROM ingest.publication_metric_snapshot snapshot
            WHERE latest.observed_at > boundary.window_start
              AND snapshot.published_month = date_trunc('month', publication.published_at)::date
              AND snapshot.publication_id = latest.publication_id
              AND snapshot.observed_at <= boundary.at
              AND NOT snapshot.synthetic
              AND snapshot.quality <> 'invalid'
            ORDER BY snapshot.observed_at DESC, snapshot.id DESC
            LIMIT 1
       ) snapshot ON true
 ) hot
  -- Упакованная история (0059): последняя несинтетическая валидная точка не
  -- позже каждой границы — то же, что max(ordinality) по битам кодов в
  -- publication_last_valid_at, — и её значения. Упакованные точки старше
  -- всех горячих, кроме поздних строк: публикация, у которой горячая точка
  -- есть на всех нужных границах, массивы не трогает.
  -- Каждый массив детостится один раз на публикацию (срез [1:n] за OFFSET 0 —
  -- одна развёрнутая копия, дальше обращения по номеру) и не превращается в
  -- строки: unnest 47 млн элементов стоил дороже самой распаковки. Массивы
  -- упаковки отсортированы по (observed_at, id) — так их пишет
  -- compact_publication_history, и на этом же держится packed_points_between,
  -- — поэтому число точек не позже границы находит двоичный поиск
  -- width_bucket. Последняя из них почти всегда валидна: синтетическая точка
  -- бывает одна на пост и стоит первой, тогда номер ищется перебором начала
  -- массива. Значения — те же элементы массивов, что отдаёт unpack_history,
  -- без преобразований; остальные её поля здесь не нужны.
  LEFT JOIN LATERAL (
      SELECT pick.i,
             ARRAY(SELECT arrays.views_count[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS views_count,
             ARRAY(SELECT arrays.reactions_count[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS reactions_count,
             ARRAY(SELECT arrays.comments_count[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS comments_count,
             ARRAY(SELECT arrays.shares_count[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS shares_count,
             ARRAY(SELECT arrays.observed_at[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS observed_at,
             ARRAY(SELECT arrays.snapshot_id[chosen.i] FROM unnest(pick.i) WITH ORDINALITY AS chosen(i, k)
                    ORDER BY chosen.k) AS id
        FROM (
           SELECT history.observed_at[1:history.point_count] AS observed_at,
                  history.codes[1:history.point_count] AS codes,
                  history.snapshot_id[1:history.point_count] AS snapshot_id,
                  history.views_count[1:history.point_count] AS views_count,
                  history.reactions_count[1:history.point_count] AS reactions_count,
                  history.comments_count[1:history.point_count] AS comments_count,
                  history.shares_count[1:history.point_count] AS shares_count
            WHERE history.publication_id IS NOT NULL
              AND (history.late_rows OR hot.gap)
           OFFSET 0
       ) arrays
        -- Номера точек на всех восьми границах одним агрегатом: он ссылается
        -- на развёрнутые массивы, и планировщик не может поставить перебор
        -- границ снаружи и пересобирать срезы на каждую.
       CROSS JOIN LATERAL (
           SELECT array_agg(CASE WHEN history.first_observed_at > point.at OR reach.last = 0 THEN NULL
                                 WHEN (arrays.codes[reach.last] >> 16) & 1 = 0 AND arrays.codes[reach.last] & 7 <> 6
                                   THEN reach.last
                                 ELSE (SELECT max(u.o)::integer
                                         FROM unnest(arrays.codes[1:reach.last]) WITH ORDINALITY AS u(c, o)
                                        WHERE (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) END
                            ORDER BY point.k) AS i
             FROM unnest(boundaries.at) WITH ORDINALITY AS point(at, k)
            CROSS JOIN LATERAL (SELECT width_bucket(point.at, arrays.observed_at) AS last) reach
       ) pick
      OFFSET 0
  ) packed ON true
      -- Самое длинное окно — 30 дней: публикации вне него не нужны ни одному
      -- периоду, и их границы не ищутся.
      WHERE latest.observed_at > params.as_of - (SELECT max(duration) FROM periods)
        AND latest.observed_at <= params.as_of
        AND NOT latest.synthetic
        AND latest.quality <> 'invalid'
     OFFSET 0
  ) post
  -- Периоды перебираются внутри строки публикации (OFFSET 0 и ссылка на неё):
  -- иначе планировщик ставит их снаружи и четырежды перечитывает с диска
  -- материализованные строки публикаций вместе с массивами.
 CROSS JOIN LATERAL (
     SELECT periods.* FROM periods
      WHERE post.observed_at > post.as_of - periods.duration
     OFFSET 0
 ) period
  -- Значение на границе: горячая точка, а упакованная — только когда горячей
  -- до границы нет или у поста есть поздние строки и упакованная позже
  -- (по observed_at, затем номеру снимка — как прежний ORDER BY … LIMIT 1).
 CROSS JOIN LATERAL (
     SELECT
            post.packed_i[period.opening_k] IS NOT NULL
            AND (post.hot_id[period.opening_k] IS NULL
                 OR post.late_rows
                    AND (post.packed_observed_at[period.opening_k], post.packed_id[period.opening_k])
                        > (post.hot_observed_at[period.opening_k], post.hot_id[period.opening_k])) AS opening_packed,
            post.packed_i[period.earlier_k] IS NOT NULL
            AND (post.hot_id[period.earlier_k] IS NULL
                 OR post.late_rows
                    AND (post.packed_observed_at[period.earlier_k], post.packed_id[period.earlier_k])
                        > (post.hot_observed_at[period.earlier_k], post.hot_id[period.earlier_k])) AS earlier_packed
 ) source
 CROSS JOIN LATERAL (
     SELECT
            CASE WHEN source.opening_packed THEN post.packed_views_count[period.opening_k]
                 ELSE post.hot_views_count[period.opening_k] END AS views_count,
            CASE WHEN source.opening_packed THEN post.packed_reactions_count[period.opening_k]
                 ELSE post.hot_reactions_count[period.opening_k] END AS reactions_count,
            CASE WHEN source.opening_packed THEN post.packed_comments_count[period.opening_k]
                 ELSE post.hot_comments_count[period.opening_k] END AS comments_count,
            CASE WHEN source.opening_packed THEN post.packed_shares_count[period.opening_k]
                 ELSE post.hot_shares_count[period.opening_k] END AS shares_count,
            CASE WHEN source.opening_packed THEN post.packed_observed_at[period.opening_k]
                 ELSE post.hot_observed_at[period.opening_k] END AS observed_at
 ) opening
 CROSS JOIN LATERAL (
     SELECT
            CASE WHEN source.earlier_packed THEN post.packed_views_count[period.earlier_k]
                 ELSE post.hot_views_count[period.earlier_k] END AS views_count,
            CASE WHEN source.earlier_packed THEN post.packed_reactions_count[period.earlier_k]
                 ELSE post.hot_reactions_count[period.earlier_k] END AS reactions_count,
            CASE WHEN source.earlier_packed THEN post.packed_comments_count[period.earlier_k]
                 ELSE post.hot_comments_count[period.earlier_k] END AS comments_count,
            CASE WHEN source.earlier_packed THEN post.packed_shares_count[period.earlier_k]
                 ELSE post.hot_shares_count[period.earlier_k] END AS shares_count
 ) earlier
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
