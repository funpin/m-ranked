-- 0084 — прогноз М-Рейтинга по соцсетям: формула v1 и ночные снимки.
-- Спек: docs/superpowers/specs/2026-10-16-rating-forecast-design.md.
--
-- Таблицы rating.rating_run/rating_result были в схеме с самого начала и
-- пустовали; прогноз — их первый потребитель. Запись — только через функции
-- SECURITY DEFINER (как import_official_rating): прямых прав на DELETE никому
-- не добавляется. Баллы всех 233 вузов базового месяца лежат в
-- rating.official_import.evidence, которую читает только maintenance, поэтому
-- заданию даётся узкая функция чтения.
--
-- Откат:
--   DROP FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz);
--   DROP FUNCTION ops_and_admin.record_rating_forecast(jsonb);
--   DROP FUNCTION rating.official_period_scores(text); DROP FUNCTION rating.official_periods();
--   DELETE FROM rating.rating_run WHERE formula_definition_id IN (SELECT id FROM rating.formula_definition
--     WHERE formula_key='m-rating-social-forecast');
--   DROP INDEX rating.rating_run_formula_window_idx; ALTER TABLE rating.rating_run DROP COLUMN parameters;
--   (строку формулы удаляет только владелец: опубликованная формула неизменна, см. 0014.)
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE rating.rating_run ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}'::jsonb
    CONSTRAINT rating_run_parameters_check CHECK (jsonb_typeof(parameters) = 'object');
CREATE INDEX rating_run_formula_window_idx ON rating.rating_run (formula_definition_id, window_start, as_of DESC);

INSERT INTO rating.formula_definition(formula_key, version, status, effective_from, definition, source_hash, published_at)
VALUES ('m-rating-social-forecast', 1, 'published', '2026-08-01T00:00:00+03:00',
        '{"formulaKey": "m-rating-social-forecast", "version": 1, "timezone": "Europe/Moscow", "weights": {"max": 0.4, "vk": 0.3, "rutube": 0.3}, "posts": {"low": 20, "high": 100}, "viewsPerStudent": {"vk": {"low": 0.1, "high": 3}, "max": {"low": 0.03, "high": 0.5}}, "erv": {"vk": {"low": 0.005, "high": 0.04}, "max": {"low": 0.005, "high": 0.1}}, "rutube": {"minVideos": 5, "logCoefficient": 12, "officialBlend": 0.5}, "matureAfterDays": 3, "earlyBeforeDay": 7, "defaultErrors": {"social": 7, "max": 10, "vk": 9, "rutube": 8}}'::jsonb,
        '86b5a8d3035c9353afe3f166642641694f5d3b379d49e9b765006b740127a5c5', transaction_timestamp());

CREATE FUNCTION rating.official_periods() RETURNS TABLE(period text, fetched_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating'
    AS $$ SELECT period, max(fetched_at) FROM rating.official_import GROUP BY period $$;

CREATE FUNCTION rating.official_period_scores(p_period text)
    RETURNS TABLE(code text, name text, social_score numeric, max_score numeric, vk_score numeric,
                  rutube_score numeric, consolidated_score numeric)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating'
    AS $$
    SELECT item->>'code', item->>'name',
           (item->'scores'->>'social')::numeric, (item->'scores'->>'ok')::numeric,
           (item->'scores'->>'vk')::numeric, (item->'scores'->>'rt')::numeric,
           (item->'scores'->>'consolidated')::numeric
      FROM (SELECT evidence FROM rating.official_import WHERE period = p_period
             ORDER BY fetched_at DESC, id DESC LIMIT 1) latest,
           jsonb_array_elements(latest.evidence->'items') item
     WHERE coalesce(item->>'code', '') <> ''
    $$;

CREATE FUNCTION ops_and_admin.record_rating_forecast(p_payload jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET statement_timeout TO '5min'
    AS $$
DECLARE formula uuid; revision bigint; run uuid; replaced integer;
    snapshot_status text := p_payload->'parameters'->>'status';
    v_window_start timestamptz; moscow_day date;
BEGIN
    IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(p_payload->'results') IS DISTINCT FROM 'array'
        OR jsonb_array_length(p_payload->'results') > 1000
        OR snapshot_status IS NULL OR snapshot_status NOT IN ('running', 'final', 'retrospective') THEN
        RAISE EXCEPTION 'invalid rating forecast' USING ERRCODE = '22023';
    END IF;
    v_window_start := (p_payload->>'windowStart')::timestamptz;
    moscow_day := ((p_payload->>'asOf')::timestamptz AT TIME ZONE 'Europe/Moscow')::date;
    PERFORM pg_advisory_xact_lock(782194602);
    SELECT id INTO formula FROM rating.formula_definition
     WHERE formula_key = p_payload->>'formulaKey' AND version = (p_payload->>'version')::integer
       AND status = 'published';
    IF formula IS NULL THEN RAISE EXCEPTION 'unknown rating formula' USING ERRCODE = '22023'; END IF;
    -- Ревизия — прямо из таблицы: владелец функции — migration_owner, а у него нет
    -- EXECUTE на функцию последней ревизии; таблица ревизий принадлежит ему же.
    SELECT max(id) INTO revision FROM analytics.dataset_revision;
    IF revision IS NULL THEN RAISE EXCEPTION 'no dataset revision' USING ERRCODE = '55000'; END IF;
    -- Снимок суток один: повторный запуск задания заменяет его. Ретроспектива
    -- месяца тоже одна. Итоговый снимок опубликованного месяца неприкосновенен.
    DELETE FROM rating.rating_run old
     WHERE old.formula_definition_id = formula AND old.window_start = v_window_start
       AND old.parameters->>'status' IS DISTINCT FROM 'published'
       AND CASE WHEN snapshot_status = 'retrospective'
                THEN old.parameters->>'status' = 'retrospective'
                ELSE old.parameters->>'status' IN ('running', 'final')
                     AND (old.as_of AT TIME ZONE 'Europe/Moscow')::date = moscow_day END;
    GET DIAGNOSTICS replaced = ROW_COUNT;
    INSERT INTO rating.rating_run(formula_definition_id, dataset_revision_id, as_of, window_start, window_end,
                                  status, started_at, completed_at, input_hash, parameters)
    VALUES (formula, revision, (p_payload->>'asOf')::timestamptz, v_window_start,
            (p_payload->>'windowEnd')::timestamptz, 'succeeded', (p_payload->>'startedAt')::timestamptz,
            greatest(transaction_timestamp(), (p_payload->>'startedAt')::timestamptz),
            p_payload->>'inputHash', p_payload->'parameters')
    RETURNING id INTO run;
    INSERT INTO rating.rating_result(rating_run_id, institution_id, score, rank, quality, explanation)
    SELECT run, (item->>'institutionId')::uuid, (item->>'score')::numeric, (item->>'rank')::integer,
           'estimated', item->'explanation'
      FROM jsonb_array_elements(p_payload->'results') item;
    INSERT INTO ops_and_admin.outbox_event(dataset_revision_id, event_type, aggregate_type, aggregate_id,
                                           affected_tags, payload)
    VALUES (revision, 'rating_forecast.recorded', 'rating_run', run::text, ARRAY['rating-forecast'],
            jsonb_build_object('runId', run, 'status', snapshot_status));
    RETURN jsonb_build_object('runId', run, 'replaced', replaced);
END $$;

CREATE FUNCTION ops_and_admin.finalize_rating_forecast(p_formula_key text, p_window_start timestamptz)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    AS $$
DECLARE keep uuid; removed integer; revision bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(782194602);
    SELECT run.id INTO keep FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = p_formula_key AND run.window_start = p_window_start
       AND run.parameters->>'status' IN ('running', 'final')
     ORDER BY run.as_of DESC LIMIT 1;
    IF keep IS NULL THEN RETURN jsonb_build_object('runId', NULL, 'removed', 0); END IF;
    UPDATE rating.rating_run SET parameters = parameters || '{"status": "published"}'::jsonb WHERE id = keep;
    DELETE FROM rating.rating_run run USING rating.formula_definition formula
     WHERE formula.id = run.formula_definition_id AND formula.formula_key = p_formula_key
       AND run.window_start = p_window_start AND run.id <> keep
       AND run.parameters->>'status' IN ('running', 'final');
    GET DIAGNOSTICS removed = ROW_COUNT;
    -- Ревизия — прямо из таблицы: владелец функции — migration_owner, а у него нет
    -- EXECUTE на функцию последней ревизии; таблица ревизий принадлежит ему же.
    SELECT max(id) INTO revision FROM analytics.dataset_revision;
    INSERT INTO ops_and_admin.outbox_event(dataset_revision_id, event_type, aggregate_type, aggregate_id,
                                           affected_tags, payload)
    VALUES (revision, 'rating_forecast.finalized', 'rating_run', keep::text, ARRAY['rating-forecast'],
            jsonb_build_object('runId', keep, 'removed', removed));
    RETURN jsonb_build_object('runId', keep, 'removed', removed);
END $$;

REVOKE ALL ON FUNCTION rating.official_periods() FROM PUBLIC;
REVOKE ALL ON FUNCTION rating.official_period_scores(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.record_rating_forecast(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rating.official_periods() TO api_write_admin;
GRANT EXECUTE ON FUNCTION rating.official_period_scores(text) TO api_write_admin;
GRANT EXECUTE ON FUNCTION ops_and_admin.record_rating_forecast(jsonb) TO api_write_admin;
GRANT EXECUTE ON FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz) TO api_write_admin;

COMMIT;
