-- 0060 — срок хранения квитанций приёма переноса.
--
-- Приёмник хранил квитанцию каждого конверта вечно: ~70 тысяч в сутки, около
-- килобайта со строкой событий и индексами — ~80 МБ в сутки, 1,1 ГБ к
-- октябрю. Метрики к тому же суммировали всю таблицу на каждом шаге.
--
-- Квитанция нужна, пока конверт может прийти повторно. Сервер 1 повторяет
-- только неподтверждённый конверт, а подтверждённый удаляет из своей очереди
-- через 26 часов (COLLECTOR_TRANSFER_SENDER_RETENTION_HOURS) и больше не шлёт.
-- Повтор применённого конверта возможен, только если потерялось само
-- подтверждение, — тогда первая же повторная попытка в пределах часов найдёт
-- квитанцию. Поэтому применённые квитанции старше окна (по умолчанию 7 суток)
-- удаляются вместе с событиями, а их счётчики сворачиваются по производителю.
-- Карантинные и неприменённые не трогаются никогда.
--
-- Откат: удалить функцию и таблицу свёртки; удалённые квитанции не
-- восстанавливаются, данные в рабочих таблицах от них не зависят.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS ops_and_admin.transfer_inbox_rollup (
    producer_id text PRIMARY KEY,
    applied_through_cursor bigint NOT NULL,
    receipts bigint NOT NULL,
    records bigint NOT NULL,
    accepted bigint NOT NULL,
    duplicates bigint NOT NULL,
    deferred bigint NOT NULL,
    rejected bigint NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE INDEX IF NOT EXISTS transfer_inbox_applied_at_idx
    ON ops_and_admin.transfer_inbox (applied_at) WHERE state = 'applied';

CREATE OR REPLACE FUNCTION ops_and_admin.prune_transfer_inbox(p_before timestamptz, p_limit integer)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog', 'ops_and_admin'
SET lock_timeout TO '5s'
AS $$
DECLARE removed integer;
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100000 THEN
        RAISE EXCEPTION 'limit must be between 1 and 100000';
    END IF;
    WITH victims AS MATERIALIZED (
        SELECT receipt_id, producer_id, last_cursor, record_count, accepted_count, duplicate_count,
               deferred_count, rejected_count
          FROM ops_and_admin.transfer_inbox
         WHERE state = 'applied' AND applied_at < p_before
         ORDER BY applied_at LIMIT p_limit
           FOR UPDATE SKIP LOCKED
    ), events AS (
        DELETE FROM ops_and_admin.transfer_inbox_event event USING victims
         WHERE event.receipt_id = victims.receipt_id
    ), receipts AS (
        DELETE FROM ops_and_admin.transfer_inbox inbox USING victims
         WHERE inbox.receipt_id = victims.receipt_id
        RETURNING victims.*
    ), totals AS (
        INSERT INTO ops_and_admin.transfer_inbox_rollup AS rollup (
            producer_id, applied_through_cursor, receipts, records, accepted, duplicates, deferred, rejected)
        SELECT producer_id, max(last_cursor), count(*), sum(record_count), sum(accepted_count),
               sum(duplicate_count), sum(deferred_count), sum(rejected_count)
          FROM receipts GROUP BY producer_id
        ON CONFLICT (producer_id) DO UPDATE SET
            applied_through_cursor = greatest(rollup.applied_through_cursor, excluded.applied_through_cursor),
            receipts = rollup.receipts + excluded.receipts, records = rollup.records + excluded.records,
            accepted = rollup.accepted + excluded.accepted, duplicates = rollup.duplicates + excluded.duplicates,
            deferred = rollup.deferred + excluded.deferred, rejected = rollup.rejected + excluded.rejected,
            updated_at = transaction_timestamp()
        RETURNING 1
    )
    SELECT count(*) INTO removed FROM receipts;
    RETURN removed;
END $$;

REVOKE ALL ON FUNCTION ops_and_admin.prune_transfer_inbox(timestamptz, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.prune_transfer_inbox(timestamptz, integer)
    TO collector_ingest, outbox_worker, maintenance;
GRANT SELECT ON ops_and_admin.transfer_inbox_rollup TO collector_ingest, outbox_worker, maintenance, storage_observer;

COMMIT;
