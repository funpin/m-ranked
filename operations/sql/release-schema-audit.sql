-- Read-only inventory before selecting the single in-place release migration.
SELECT jsonb_pretty(jsonb_build_object(
    'contract', (SELECT contract_id FROM ops_and_admin.schema_contract),
    'databaseBytes', pg_database_size(current_database()),
    'purgeOutbox', to_regprocedure('ops_and_admin.purge_delivered_outbox(interval,integer)') IS NOT NULL,
    'purgeRevisions', to_regprocedure('ops_and_admin.purge_old_dataset_revisions(interval,integer)') IS NOT NULL,
    'historyPage', to_regclass('analytics.publication_history_page') IS NOT NULL,
    'historyPageIndexValid', EXISTS (
        SELECT 1 FROM pg_index WHERE indexrelid =
            to_regclass('analytics.publication_history_page_computed_idx') AND indisvalid
    ),
    'siteSummary', to_regclass('analytics.site_summary') IS NOT NULL,
    'pollReceipt', to_regclass('ingest.publication_poll_receipt') IS NOT NULL,
    'pollReceiptIndexValid', EXISTS (
        SELECT 1 FROM pg_index WHERE indexrelid =
            to_regclass('ingest.publication_poll_receipt_observed_idx') AND indisvalid
    ),
    'contextRecheck', to_regclass('analytics.post_anomaly_context_recheck') IS NOT NULL,
    'boundedGrowthDaily', to_regclass('analytics.bounded_poll_growth_daily') IS NOT NULL,
    'boundedReferenceIndexValid', EXISTS (
        SELECT 1 FROM pg_index WHERE indexrelid =
            to_regclass('analytics.bounded_poll_growth_daily_reference_idx') AND indisvalid
    ),
    'boundedRetentionIndexValid', EXISTS (
        SELECT 1 FROM pg_index WHERE indexrelid =
            to_regclass('analytics.bounded_poll_growth_daily_retention_idx') AND indisvalid
    ),
    'receiptDisplayUnit', EXISTS (
        SELECT 1 FROM pg_attribute WHERE attrelid =
            to_regclass('ingest.publication_poll_receipt')
          AND attname = 'views_display_unit' AND NOT attisdropped
    )
)) AS release_schema_inventory;
