-- 0063 — возврат месяцев холодного архива в базу.
--
-- Холодный архив выводится из оборота: история замеров живёт в базе в
-- упакованном виде (0059) и весит в десятки раз меньше. Месяцы, уже ушедшие
-- в Parquet (июль и август 2026), возвращаются. canonical_record каждой строки
-- архива — полная строка снимка (все колонки, отпечатки, evidence) плюс
-- разбивка реакций; по нему строка и восстанавливается.
--
-- Триггер вставки обычно пересчитывает номер исправления и ссылку на
-- предыдущую версию; для восстановления это неверно — строка должна встать
-- ровно такой, какой была. Владелец таблицы под флагом сеанса ingest.restore
-- вставляет как есть; повтор вставки ничего не дублирует. Сверка — побайтно
-- по canonical_record до упаковки (operations/cold_archive/restore.py).
--
-- Откат: прежний триггер из 0059, удалить функцию.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ingest.prepare_immutable_publication_snapshot() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    AS $$
DECLARE previous ingest.publication_metric_snapshot%ROWTYPE;
 packed record; packed_sequence bigint; packed_id bigint; hot_sequence bigint;
BEGIN
 NEW.ingested_xid:=pg_current_xact_id();
 PERFORM ops_and_admin.assert_publication_partition_writable(NEW.published_month);
 -- Восстановление из холодного архива (0063): строка возвращается ровно такой,
 -- какой была, — номер исправления и ссылки не пересчитываются. Флаг сеанса
 -- ставит кто угодно, поэтому проверяется и роль владельца таблицы.
 IF current_setting('ingest.restore', true)='on'
    AND current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class
                       WHERE oid='ingest.publication_metric_snapshot'::regclass) THEN
   RETURN NEW;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation:'||NEW.published_month::text||':'||NEW.publication_id::text||':'||NEW.sampling_bucket::text,0));
 NEW.views_quality:=coalesce(NEW.views_quality,NEW.quality);
 NEW.reactions_quality:=coalesce(NEW.reactions_quality,NEW.quality);
 NEW.comments_quality:=coalesce(NEW.comments_quality,NEW.quality);
 NEW.shares_quality:=coalesce(NEW.shares_quality,NEW.quality);
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket AND source_fingerprint=NEW.source_fingerprint;
 IF FOUND THEN
   previous.metric_evidence:=coalesce(previous.metric_evidence,(SELECT payload FROM ingest.metric_evidence_dictionary WHERE id=previous.metric_evidence_id));
   IF (to_jsonb(previous)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid','metric_evidence_id'])
    IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid','metric_evidence_id']) THEN
     RAISE EXCEPTION 'fingerprint reused for different observation' USING ERRCODE='23505';
   END IF;
   RETURN NULL;
 END IF;
 IF NEW.observed_at < transaction_timestamp() - interval '1 day'
    AND EXISTS (SELECT 1 FROM ingest.publication_metric_history WHERE publication_id=NEW.publication_id) THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('metric-history:'||NEW.publication_id::text,0));
   SELECT bool_or(p.observed_at=NEW.observed_at AND p.views_count IS NOT DISTINCT FROM NEW.views_count
                  AND p.reactions_count IS NOT DISTINCT FROM NEW.reactions_count
                  AND p.comments_count IS NOT DISTINCT FROM NEW.comments_count
                  AND p.shares_count IS NOT DISTINCT FROM NEW.shares_count
                  AND p.quality=NEW.quality AND p.views_quality=NEW.views_quality
                  AND p.reactions_quality=NEW.reactions_quality AND p.comments_quality=NEW.comments_quality
                  AND p.shares_quality=NEW.shares_quality AND p.synthetic=NEW.synthetic
                  AND p.interval_uncertain=NEW.interval_uncertain) AS replay,
          max(p.correction_sequence) AS top
     INTO packed
     FROM ingest.publication_metric_point p
    WHERE p.packed AND p.publication_id=NEW.publication_id AND p.published_month=NEW.published_month
      AND p.sampling_bucket=NEW.sampling_bucket;
   IF packed.replay THEN RETURN NULL; END IF;
   IF packed.top IS NOT NULL THEN
     SELECT p.id INTO packed_id FROM ingest.publication_metric_point p
      WHERE p.packed AND p.publication_id=NEW.publication_id AND p.published_month=NEW.published_month
        AND p.sampling_bucket=NEW.sampling_bucket AND p.correction_sequence=packed.top;
     packed_sequence:=packed.top;
     UPDATE ingest.publication_metric_history SET late_rows=true WHERE publication_id=NEW.publication_id;
   END IF;
 END IF;
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket ORDER BY correction_sequence DESC LIMIT 1;
 hot_sequence:=CASE WHEN FOUND THEN previous.correction_sequence END;
 IF packed_sequence IS NOT NULL AND (hot_sequence IS NULL OR packed_sequence>hot_sequence) THEN
   NEW.correction_sequence:=packed_sequence+1;
   NEW.supersedes_snapshot_id:=packed_id;
 ELSE
   NEW.correction_sequence:=CASE WHEN hot_sequence IS NOT NULL THEN hot_sequence+1 ELSE 0 END;
   NEW.supersedes_snapshot_id:=previous.id;
 END IF;
 NEW.correction_reason:=CASE WHEN NEW.supersedes_snapshot_id IS NOT NULL THEN coalesce(nullif(btrim(NEW.correction_reason),''),'provider_payload_changed') END;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION ingest.restore_archived_snapshots(p_records jsonb)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
SET "TimeZone" TO 'UTC'
AS $$
DECLARE restored integer;
BEGIN
    IF jsonb_typeof(p_records) <> 'array' THEN
        RAISE EXCEPTION 'records must be a JSON array';
    END IF;
    PERFORM set_config('ingest.restore', 'on', true);
    INSERT INTO ingest.publication_metric_snapshot
    SELECT * FROM jsonb_populate_recordset(NULL::ingest.publication_metric_snapshot, p_records)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS restored = ROW_COUNT;
    INSERT INTO ingest.reaction_breakdown (snapshot_published_month, snapshot_id, reaction_key, reaction_count)
    SELECT (record->>'published_month')::date, (record->>'id')::bigint, item.key, item.value::bigint
      FROM jsonb_array_elements(p_records) AS record
     CROSS JOIN LATERAL jsonb_each(coalesce(record->'reaction_breakdown', '{}'::jsonb)) AS item
    ON CONFLICT DO NOTHING;
    PERFORM set_config('ingest.restore', 'off', true);
    RETURN restored;
END $$;

REVOKE ALL ON FUNCTION ingest.restore_archived_snapshots(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ingest.restore_archived_snapshots(jsonb) TO maintenance;

COMMIT;
