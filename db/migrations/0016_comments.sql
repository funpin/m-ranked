-- 0016 — комментарии
-- Порождается из каталога эталонной базы; см. db/README.md.

-- ingest.CONSTRAINT publication_baseline_history_check ON publication
COMMENT ON CONSTRAINT publication_baseline_history_check ON ingest.publication IS 'Allows the independent original legacy baseline on forced-incomplete history. Native normalization must not create such a baseline; collector refresh preserves an already stored decision.';

-- ingest.COLUMN publication_metric_snapshot.comments_count
COMMENT ON COLUMN ingest.publication_metric_snapshot.comments_count IS 'Nullable platform observation. MAX comments are stored when exposed; unsupported or unavailable remains NULL.';

-- ingest.COLUMN publication_metric_snapshot.collected_at
COMMENT ON COLUMN ingest.publication_metric_snapshot.collected_at IS 'UTC instant when the target collector received the observation.';

-- ingest.COLUMN publication_metric_snapshot.semantic_fingerprint
COMMENT ON COLUMN ingest.publication_metric_snapshot.semantic_fingerprint IS 'SHA-256 of historical metric/quality/evidence/reaction semantics, excluding poll and run timestamps. NULL only for rows preceding the final schema contract.';

-- ops_and_admin.FUNCTION ensure_publication_legacy_alias(p_publication uuid)
COMMENT ON FUNCTION ops_and_admin.ensure_publication_legacy_alias(p_publication uuid) IS 'Returns or allocates a publication alias from its namespace sequence without a whole-table lock.';

-- ops_and_admin.FUNCTION ensure_publication_metric_partition(p_month date)
COMMENT ON FUNCTION ops_and_admin.ensure_publication_metric_partition(p_month date) IS 'Returns an existing snapshot/reaction partition pair without advisory locks or DDL; serializes only creation or repair of a missing child.';

-- ops_and_admin.FUNCTION public_health_snapshot()
COMMENT ON FUNCTION ops_and_admin.public_health_snapshot() IS 'Public safe operational fields only. Migration bridge runs never fabricate collector freshness. No raw history or arbitrary checkpoint access.';

-- analytics.TABLE legacy_overview_account
COMMENT ON TABLE analytics.legacy_overview_account IS 'Revision-pinned account metadata used by legacy overview cards; rows include disabled accounts outside Telegram exactly as the legacy overview did.';

-- analytics.TABLE legacy_overview_card
COMMENT ON TABLE analytics.legacy_overview_card IS 'Revision-pinned legacy / overview cards. Windows use (start,end], new-publication zero baselines retain platform gates, and all never mixes counters across platforms.';

-- analytics.TABLE legacy_period_policy
COMMENT ON TABLE analytics.legacy_period_policy IS 'Owner-managed append-only configuration: add a new configuration dataset revision and policy row together, then rebuild that revision. Never retrofit a published revision.';

-- ingest.COLUMN account_metric_snapshot.collected_at
COMMENT ON COLUMN ingest.account_metric_snapshot.collected_at IS 'UTC instant when the target collector received the observation.';

-- ingest.COLUMN account_metric_snapshot.semantic_fingerprint
COMMENT ON COLUMN ingest.account_metric_snapshot.semantic_fingerprint IS 'SHA-256 of subscriber value/display/quality semantics, excluding poll, run, collector version and transport timestamps. NULL only for rows preceding the final schema transition.';

-- ingest.COLUMN collection_account_result.semantic_changed
COMMENT ON COLUMN ingest.collection_account_result.semantic_changed IS 'True when this account transaction committed a semantic source-of-truth change; consumed idempotently by run-level revision finalization.';

-- ingest.COLUMN collection_account_result.identity_source_receipt
COMMENT ON COLUMN ingest.collection_account_result.identity_source_receipt IS 'Optional immutable evidence receipt for an identity change committed by this account transaction.';

-- ingest.COLUMN collection_run.scheduled_at
COMMENT ON COLUMN ingest.collection_run.scheduled_at IS 'UTC scheduler instant; distinct from the actual collector start.';

-- ops_and_admin.VIEW schema_contract
COMMENT ON VIEW ops_and_admin.schema_contract IS 'Single runtime database contract. Services validate this identifier; historical migration metadata is not a runtime input.';
