-- 0067 — горячие точки оконных функций — из таблицы, а не через представление.
--
-- publication_points_between, publication_point_at и publication_last_valid_at
-- (0059) брали горячие строки из представления точек. Его видимость —
-- проверка преемника в бакете — коррелирует по месяцу строки, и для массива
-- постов планировщик оценивал точечную проверку как проход по всем
-- партициям, а потому строил хеш-антисоединение со всей таблицей снимков
-- (15 млн строк): 06.10 сводка «Обзора» упёрлась в десятиминутный таймаут,
-- воркер анализа — в свой. А там, где функция не встраивается (массив
-- передан подзапросом), представление считало и тяжёлые колонки — evidence
-- из TOAST и разбивку — для каждой горячей строки, нужны они вызывающему
-- или нет.
--
-- Теперь горячая ветка читает таблицу снимков. В проверке преемника —
-- явное «publication_id = ANY (p_ids)»: внутренняя сторона сводится к
-- строкам тех же постов. Одна точка на пост (point_at, last_valid_at)
-- выбирается по индексу (publication_id, observed_at DESC, id DESC) только
-- ключом, полная строка собирается одна. Колонки — те же выражения, что в
-- ветке горячих строк представления (0059).
--
-- Откат: определения функций из 0059.
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
  FROM ingest.publication_metric_snapshot s
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
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id FROM ingest.publication_metric_snapshot s
         WHERE s.publication_id = ids.publication_id AND s.observed_at <= p_at
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
     CROSS JOIN LATERAL (
        SELECT s.published_month, s.id FROM ingest.publication_metric_snapshot s
         WHERE s.publication_id = ids.publication_id AND s.observed_at <= p_at
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

COMMIT;
