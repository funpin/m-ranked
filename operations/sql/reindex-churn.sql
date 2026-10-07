-- Еженедельная перестройка индексов с постоянной сменой ключей (0061).
-- REINDEX CONCURRENTLY не держит долгих блокировок; вне транзакции.
-- Запускает m-ranked-target-reindex.service от владельца схемы.
\set ON_ERROR_STOP off
SET lock_timeout = '10s';
SET statement_timeout = '30min';
REINDEX INDEX CONCURRENTLY analytics.publication_latest_account_idx;
REINDEX INDEX CONCURRENTLY analytics.publication_latest_revision_idx;
REINDEX INDEX CONCURRENTLY analytics.publication_latest_pkey;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_dataset_revision_id_event_type_aggregate_type__key;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_class_pending_idx;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_pkey;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_delivered_gc_idx;
REINDEX INDEX CONCURRENTLY ops_and_admin.outbox_event_pending_idx;
REINDEX INDEX CONCURRENTLY analytics.dataset_revision_committed_idx;
REINDEX INDEX CONCURRENTLY analytics.dataset_revision_pkey;
