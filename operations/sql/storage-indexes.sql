-- Run outside a transaction, one index at a time after approval.
-- Budget: <0.25 GB estimated including index build staging; validate on host.
-- If interrupted, inspect pg_index.indisvalid; IF NOT EXISTS is not repair.
SET lock_timeout='1s';
SET statement_timeout='10min';
SET maintenance_work_mem='32MB';
CREATE INDEX CONCURRENTLY IF NOT EXISTS outbox_event_delivered_gc_idx
 ON ops_and_admin.outbox_event (published_at,id) WHERE published_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS outbox_event_terminal_gc_idx
 ON ops_and_admin.outbox_event (terminal_at,id) WHERE terminal_at IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS raw_payload_external_ref_gc_idx
 ON ingest.raw_payload (external_ref,purge_after) WHERE external_ref IS NOT NULL;
-- Ссылки на ревизии без индекса: проверка внешнего ключа при удалении старых
-- ревизий (0042) иначе просматривала бы эти таблицы целиком на каждую строку.
CREATE INDEX CONCURRENTLY IF NOT EXISTS institution_daily_metrics_revision_idx
 ON analytics.institution_daily_metrics (dataset_revision_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS institution_monthly_metrics_revision_idx
 ON analytics.institution_monthly_metrics (dataset_revision_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS institution_period_metrics_revision_idx
 ON analytics.institution_period_metrics (dataset_revision_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS publication_latest_revision_idx
 ON analytics.publication_latest (dataset_revision_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS comparison_cohort_revision_idx
 ON analytics.comparison_cohort (dataset_revision_id);
