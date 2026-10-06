-- 0068 — оконные функции ищут горячие точки в партиции месяца поста.
--
-- В 0067 горячая ветка искала строки поста по publication_id без месяца:
-- индекс (publication_id, observed_at DESC, id DESC) у каждой партиции свой,
-- и последняя точка поста искалась во всех ~50 партициях на каждый вызов.
-- Прежние читатели задавали месяц явно — сводка «Обзора» по 0067 так и
-- упиралась в десятиминутный таймаут. Месяц однозначно следует из даты
-- публикации (то же выражение, что в ingest.assert_publication_snapshot_month): для
-- одной точки на пост — месяц этого поста, для окна точек — набор месяцев
-- постов массива, им же ограничена проверка преемника.
--
-- Отдельно — packed_*: только упакованная часть тех же функций.
--
-- Откат: определения функций из 0067.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ingest.publication_points_between(p_ids uuid[], p_from timestamptz, p_to timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT s.published_month, s.id, s.publication_id, s.collection_run_id, s.observed_at, s.age_seconds,
       s.sampling_bucket, s.views_count, s.reactions_count, s.comments_count, s.shares_count, s.quality,
       s.interval_uncertain, s.synthetic, s.metric_semantics_version, s.capability_version,
       s.source_fingerprint, s.created_at, s.collected_at, s.ingested_xid, s.correction_sequence,
       s.supersedes_snapshot_id, s.correction_reason, s.views_quality, s.reactions_quality,
       s.comments_quality, s.shares_quality,
       COALESCE(s.metric_evidence, evidence.payload) - 'reaction_breakdown',
       s.semantic_fingerprint,
       NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                    WHERE successor.publication_id = ANY (p_ids)
                      AND successor.published_month = ANY (months.list)
                      AND successor.published_month = s.published_month
                      AND successor.publication_id = s.publication_id
                      AND successor.sampling_bucket = s.sampling_bucket
                      AND successor.correction_sequence > s.correction_sequence),
       false,
       COALESCE(COALESCE(s.metric_evidence, evidence.payload) -> 'reaction_breakdown',
                (SELECT jsonb_object_agg(r.reaction_key, r.reaction_count ORDER BY r.reaction_key)
                   FROM ingest.reaction_breakdown r
                  WHERE r.snapshot_published_month = s.published_month AND r.snapshot_id = s.id),
                '{}'::jsonb)
  FROM (SELECT ARRAY(SELECT DISTINCT date_trunc('month', pub.published_at AT TIME ZONE 'UTC')::date
                                         FROM ingest.publication pub WHERE pub.id = ANY (p_ids)) AS list) months
  JOIN ingest.publication_metric_snapshot s ON s.published_month = ANY (months.list)
  LEFT JOIN ingest.metric_evidence_dictionary evidence ON evidence.id = s.metric_evidence_id
 WHERE s.publication_id = ANY (p_ids) AND s.observed_at >= p_from AND s.observed_at < p_to
UNION ALL
SELECT p.*
  FROM ingest.publication_metric_history h
 CROSS JOIN LATERAL (SELECT min(u.o)::integer AS lo, max(u.o)::integer AS hi
                       FROM unnest(h.observed_at) WITH ORDINALITY AS u(t, o)
                      WHERE u.t >= p_from AND u.t < p_to) slice
 CROSS JOIN LATERAL ingest.unpack_history(h, slice.lo, slice.hi) p
 WHERE h.publication_id = ANY (p_ids) AND h.last_observed_at >= p_from AND h.first_observed_at < p_to
   AND slice.lo IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION ingest.publication_last_valid_at(p_ids uuid[], p_at timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT DISTINCT ON (candidate.publication_id) candidate.*
  FROM (
    SELECT hot.* FROM unnest(p_ids) AS ids(publication_id)
      JOIN ingest.publication pub ON pub.id = ids.publication_id
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id FROM ingest.publication_metric_snapshot s
         WHERE s.published_month = date_trunc('month', pub.published_at AT TIME ZONE 'UTC')::date
           AND s.publication_id = ids.publication_id AND s.observed_at <= p_at
           AND NOT s.synthetic AND s.quality <> 'invalid'
         ORDER BY s.observed_at DESC, s.id DESC LIMIT 1) pick
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id, s.publication_id, s.collection_run_id, s.observed_at, s.age_seconds,
               s.sampling_bucket, s.views_count, s.reactions_count, s.comments_count, s.shares_count, s.quality,
               s.interval_uncertain, s.synthetic, s.metric_semantics_version, s.capability_version,
               s.source_fingerprint, s.created_at, s.collected_at, s.ingested_xid, s.correction_sequence,
               s.supersedes_snapshot_id, s.correction_reason, s.views_quality, s.reactions_quality,
               s.comments_quality, s.shares_quality,
               COALESCE(s.metric_evidence, evidence.payload) - 'reaction_breakdown',
               s.semantic_fingerprint,
               NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                                    WHERE successor.published_month = s.published_month
                                      AND successor.publication_id = s.publication_id
                                      AND successor.sampling_bucket = s.sampling_bucket
                                      AND successor.correction_sequence > s.correction_sequence),
               false,
               COALESCE(COALESCE(s.metric_evidence, evidence.payload) -> 'reaction_breakdown',
                        (SELECT jsonb_object_agg(r.reaction_key, r.reaction_count ORDER BY r.reaction_key)
                           FROM ingest.reaction_breakdown r
                          WHERE r.snapshot_published_month = s.published_month AND r.snapshot_id = s.id),
                        '{}'::jsonb)
          FROM ingest.publication_metric_snapshot s
          LEFT JOIN ingest.metric_evidence_dictionary evidence ON evidence.id = s.metric_evidence_id
         WHERE s.published_month = pick.published_month AND s.id = pick.id) hot
    UNION ALL
    SELECT packed.*
      FROM ingest.publication_metric_history h
     CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                           FROM unnest(h.observed_at, h.codes) WITH ORDINALITY AS u(t, c, o)
                          WHERE u.t <= p_at AND (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) pick
     CROSS JOIN LATERAL ingest.unpack_history(h, pick.i, pick.i) packed
     WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
  ) candidate
 ORDER BY candidate.publication_id, candidate.observed_at DESC, candidate.id DESC
$$;

CREATE OR REPLACE FUNCTION ingest.publication_point_at(p_ids uuid[], p_at timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT DISTINCT ON (candidate.publication_id) candidate.*
  FROM (
    SELECT hot.* FROM unnest(p_ids) AS ids(publication_id)
      JOIN ingest.publication pub ON pub.id = ids.publication_id
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id FROM ingest.publication_metric_snapshot s
         WHERE s.published_month = date_trunc('month', pub.published_at AT TIME ZONE 'UTC')::date
           AND s.publication_id = ids.publication_id AND s.observed_at <= p_at
           AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                            WHERE successor.published_month = s.published_month
                              AND successor.publication_id = s.publication_id
                              AND successor.sampling_bucket = s.sampling_bucket
                              AND successor.correction_sequence > s.correction_sequence)
         ORDER BY s.observed_at DESC, s.id DESC LIMIT 1) pick
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id, s.publication_id, s.collection_run_id, s.observed_at, s.age_seconds,
               s.sampling_bucket, s.views_count, s.reactions_count, s.comments_count, s.shares_count, s.quality,
               s.interval_uncertain, s.synthetic, s.metric_semantics_version, s.capability_version,
               s.source_fingerprint, s.created_at, s.collected_at, s.ingested_xid, s.correction_sequence,
               s.supersedes_snapshot_id, s.correction_reason, s.views_quality, s.reactions_quality,
               s.comments_quality, s.shares_quality,
               COALESCE(s.metric_evidence, evidence.payload) - 'reaction_breakdown',
               s.semantic_fingerprint,
               true,
               false,
               COALESCE(COALESCE(s.metric_evidence, evidence.payload) -> 'reaction_breakdown',
                        (SELECT jsonb_object_agg(r.reaction_key, r.reaction_count ORDER BY r.reaction_key)
                           FROM ingest.reaction_breakdown r
                          WHERE r.snapshot_published_month = s.published_month AND r.snapshot_id = s.id),
                        '{}'::jsonb)
          FROM ingest.publication_metric_snapshot s
          LEFT JOIN ingest.metric_evidence_dictionary evidence ON evidence.id = s.metric_evidence_id
         WHERE s.published_month = pick.published_month AND s.id = pick.id) hot
    UNION ALL
    -- Обычный случай: последняя точка с битом visible находится по двум
    -- массивам, декодируется одна точка.
    SELECT packed.*
      FROM ingest.publication_metric_history h
     CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                           FROM unnest(h.observed_at, h.codes) WITH ORDINALITY AS u(t, c, o)
                          WHERE u.t <= p_at AND (u.c >> 17) & 1 = 1) pick
     CROSS JOIN LATERAL ingest.unpack_history(h, pick.i, pick.i) packed
     WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
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
     WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND slice.hi IS NOT NULL
       AND h.late_rows
  ) candidate
 ORDER BY candidate.publication_id, candidate.observed_at DESC, candidate.id DESC
$$;

-- Только упакованная часть тех же функций — для читателей, которые горячую
-- точку берут своим запросом с месяцем поста (прежний быстрый путь по
-- таблице снимков), а упакованную — отсюда, не трогая партиций.
CREATE OR REPLACE FUNCTION ingest.packed_last_valid_at(p_ids uuid[], p_at timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT packed.*
  FROM ingest.publication_metric_history h
 CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i
                       FROM unnest(h.observed_at, h.codes) WITH ORDINALITY AS u(t, c, o)
                      WHERE u.t <= p_at AND (u.c >> 16) & 1 = 0 AND u.c & 7 <> 6) pick
 CROSS JOIN LATERAL ingest.unpack_history(h, pick.i, pick.i) packed
 WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION ingest.packed_point_at(p_ids uuid[], p_at timestamptz)
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
     WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND pick.i IS NOT NULL
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
     WHERE h.publication_id = ANY (p_ids) AND h.first_observed_at <= p_at AND slice.hi IS NOT NULL
       AND h.late_rows
  ) candidate
 ORDER BY candidate.publication_id, candidate.observed_at DESC, candidate.id DESC
$$;

CREATE OR REPLACE FUNCTION ingest.packed_points_between(p_ids uuid[], p_from timestamptz, p_to timestamptz)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
SELECT p.*
  FROM ingest.publication_metric_history h
 CROSS JOIN LATERAL (SELECT min(u.o)::integer AS lo, max(u.o)::integer AS hi
                       FROM unnest(h.observed_at) WITH ORDINALITY AS u(t, o)
                      WHERE u.t >= p_from AND u.t < p_to) slice
 CROSS JOIN LATERAL ingest.unpack_history(h, slice.lo, slice.hi) p
 WHERE h.publication_id = ANY (p_ids) AND h.last_observed_at >= p_from AND h.first_observed_at < p_to
   AND slice.lo IS NOT NULL
$$;

GRANT EXECUTE ON FUNCTION ingest.packed_last_valid_at(uuid[], timestamptz),
    ingest.packed_point_at(uuid[], timestamptz),
    ingest.packed_points_between(uuid[], timestamptz, timestamptz)
    TO maintenance, api_read, analytics_worker, collector_ingest;

COMMIT;
