-- 0066 — последняя точка поста для приёма — по ключу, а не по полной строке.
--
-- publication_latest_point (0059) брала горячую точку как «ORDER BY observed_at DESC LIMIT 1» прямо из
-- представления точек. Колонки представления — evidence без разбивки (чтение
-- TOAST), разбивка реакций (подзапрос) и видимость — вычисляются ниже
-- сортировки, то есть для каждой горячей строки поста, а не для одной
-- выбранной: на проде 06.10 последняя точка поста с ~700 горячими строками
-- читалась 2,3 с (520 чтений с диска), и приём замеров встал. Прежний код
-- читал из представления две колонки, и лишнее планировщик отбрасывал.
--
-- Теперь горячая часть идёт по таблице снимков: индекс (publication_id,
-- observed_at DESC, id DESC), видимость — та же проверка преемника в бакете,
-- что в представлении; полная строка собирается одна — по ключу. Пакет из
-- 100 постов на проде — 0,35 с вместо минуты с лишним.
--
-- Откат: определение функции из 0059.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ingest.publication_latest_point(p_publication_id uuid, p_published_month date,
                                                           p_synthetic boolean DEFAULT NULL)
RETURNS SETOF ingest.publication_metric_point
LANGUAGE plpgsql STABLE PARALLEL SAFE
-- Вызывается из LATERAL по пакету постов на каждый пакет переноса. План
-- кэшируется на сессию: месяц везде — параметр, партиции отсекаются при
-- запуске; горячая строка собирается из таблицы по ключу теми же
-- выражениями, что ветка горячих строк представления точек, — разворачивать
-- представление (UNION, подзапросы по всем партициям) на каждый пост
-- стоило ~150 мс одного планирования. Общий план — принудительно: по оценке
-- он дороже частного (партиции отсекаются только при запуске), и без этого
-- plpgsql перепланировал бы каждый вызов (~60–120 мс).
SET plan_cache_mode = force_generic_plan
AS $$
DECLARE
    v_id bigint;
BEGIN
    SELECT s.id INTO v_id
      FROM ingest.publication_metric_snapshot s
     WHERE s.publication_id = p_publication_id AND s.published_month = p_published_month
       AND (p_synthetic IS NULL OR s.synthetic = p_synthetic)
       AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                        WHERE successor.published_month = p_published_month
                          AND successor.publication_id = p_publication_id
                          AND successor.sampling_bucket = s.sampling_bucket
                          AND successor.correction_sequence > s.correction_sequence)
     ORDER BY s.observed_at DESC, s.id DESC LIMIT 1;

    RETURN QUERY
    SELECT candidate.* FROM (
        SELECT s.published_month, s.id, s.publication_id, s.collection_run_id, s.observed_at, s.age_seconds,
               s.sampling_bucket, s.views_count, s.reactions_count, s.comments_count, s.shares_count, s.quality,
               s.interval_uncertain, s.synthetic, s.metric_semantics_version, s.capability_version,
               s.source_fingerprint, s.created_at, s.collected_at, s.ingested_xid, s.correction_sequence,
               s.supersedes_snapshot_id, s.correction_reason, s.views_quality, s.reactions_quality,
               s.comments_quality, s.shares_quality,
               COALESCE(s.metric_evidence, evidence.payload) - 'reaction_breakdown',
               s.semantic_fingerprint, true, false,
               COALESCE(COALESCE(s.metric_evidence, evidence.payload) -> 'reaction_breakdown',
                        (SELECT jsonb_object_agg(r.reaction_key, r.reaction_count ORDER BY r.reaction_key)
                           FROM ingest.reaction_breakdown r
                          WHERE r.snapshot_published_month = p_published_month AND r.snapshot_id = s.id),
                        '{}'::jsonb)
          FROM ingest.publication_metric_snapshot s
          LEFT JOIN ingest.metric_evidence_dictionary evidence ON evidence.id = s.metric_evidence_id
         WHERE v_id IS NOT NULL AND s.published_month = p_published_month AND s.id = v_id
        UNION ALL
        SELECT p.*
          FROM ingest.publication_metric_history h
         CROSS JOIN LATERAL (SELECT max(u.o)::integer AS i FROM unnest(h.codes) WITH ORDINALITY AS u(c, o)
                              WHERE (u.c >> 17) & 1 = 1
                                AND (p_synthetic IS NULL OR ((u.c >> 16) & 1 = 1) = p_synthetic)) found
         CROSS JOIN LATERAL ingest.unpack_history(h, found.i, found.i) p
         WHERE v_id IS NULL AND h.publication_id = p_publication_id AND h.published_month = p_published_month
           AND found.i IS NOT NULL AND NOT h.late_rows
        UNION ALL
        SELECT p.*
          FROM ingest.publication_metric_history h
         CROSS JOIN LATERAL ingest.unpack_history(h, 1, h.point_count) p
         WHERE h.publication_id = p_publication_id AND h.published_month = p_published_month AND h.late_rows
           AND p.visible AND (p_synthetic IS NULL OR p.synthetic = p_synthetic)
    ) candidate
     ORDER BY candidate.observed_at DESC, candidate.id DESC LIMIT 1;
END
$$;

COMMIT;
