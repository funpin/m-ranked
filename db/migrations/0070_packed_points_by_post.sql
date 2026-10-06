-- 0070 — упакованная часть точек одного поста — поиском по ключу.
--
-- Читатели, обходящие посты по одному, звали packed_* (0068) с
-- ARRAY[post.id]. Условие «publication_id = ANY (ARRAY[x])» в общем плане
-- подготовленного запроса не становится равенством, и таблица упакованной
-- истории просматривалась целиком на каждый пост: 06.10 на 150 упакованных
-- постах — 3,5 млн буферов и 3 с на статистику аккаунта; на всей упакованной
-- истории (~85 тысяч строк) это были бы минуты. Здесь — те же функции для
-- одного поста: «publication_id = p_id», поиск по первичному ключу.
--
-- Откат: DROP FUNCTION ingest.packed_last_valid_at(uuid, timestamptz),
-- ingest.packed_point_at(uuid, timestamptz),
-- ingest.packed_points_between(uuid, timestamptz, timestamptz).
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ingest.packed_last_valid_at(p_id uuid, p_at timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT packed.*
  FROM ingest.publication_metric_history h
 CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                       FROM unnest(h.observed_at, h.codes) WITH ORDINALITY AS u(t, c, o)
                      WHERE u.t <= p_at AND (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) pick
 CROSS JOIN LATERAL ingest.unpack_history(h, pick.i, pick.i) packed
 WHERE h.publication_id = p_id AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION ingest.packed_point_at(p_id uuid, p_at timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT DISTINCT ON (candidate.publication_id) candidate.*
  FROM (
    -- Обычный случай: последняя точка с битом visible находится по двум
    -- массивам, декодируется одна точка.
    SELECT packed.*
      FROM ingest.publication_metric_history h
     CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                           FROM unnest(h.observed_at, h.codes) WITH ORDINALITY AS u(t, c, o)
                          WHERE u.t <= p_at AND (u.c >> 17) & 1 = 1) pick
     CROSS JOIN LATERAL ingest.unpack_history(h, pick.i, pick.i) packed
     WHERE h.publication_id = p_id AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
       AND NOT h.late_rows
    UNION ALL
    -- Есть поздние горячие строки: видимость сверяется с ними, отрезок целиком.
    SELECT packed.*
      FROM ingest.publication_metric_history h
     CROSS JOIN LATERAL (SELECT max(u.o)::integer AS hi FROM unnest(h.observed_at) WITH ORDINALITY AS u(t, o)
                          WHERE u.t <= p_at) slice
     CROSS JOIN LATERAL (
        SELECT p.* FROM ingest.unpack_history(h, 1, slice.hi) p
         WHERE p.visible ORDER BY p.observed_at DESC, p.id DESC LIMIT 1) packed
     WHERE h.publication_id = p_id AND h.first_observed_at <= p_at AND slice.hi IS NOT NULL
       AND h.late_rows
  ) candidate
 ORDER BY candidate.publication_id, candidate.observed_at DESC, candidate.id DESC
$$;

CREATE OR REPLACE FUNCTION ingest.packed_points_between(p_id uuid, p_from timestamptz, p_to timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT p.*
  FROM ingest.publication_metric_history h
 CROSS JOIN LATERAL (SELECT min(u.o)::integer AS lo, max(u.o)::integer AS hi
                       FROM unnest(h.observed_at) WITH ORDINALITY AS u(t, o)
                      WHERE u.t >= p_from AND u.t < p_to) slice
 CROSS JOIN LATERAL ingest.unpack_history(h, slice.lo, slice.hi) p
 WHERE h.publication_id = p_id AND h.last_observed_at >= p_from AND h.first_observed_at < p_to
   AND slice.lo IS NOT NULL
$$;

GRANT EXECUTE ON FUNCTION ingest.packed_last_valid_at(uuid, timestamptz),
    ingest.packed_point_at(uuid, timestamptz),
    ingest.packed_points_between(uuid, timestamptz, timestamptz)
    TO maintenance, api_read, analytics_worker, collector_ingest;

COMMIT;
