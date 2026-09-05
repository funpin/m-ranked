-- Collector contract expansion. V1/V2 remain immutable; this migration makes
-- scheduled, observed and collected instants independently queryable and gives
-- the ingestion role only the catalog writes required to version observed
-- account identities.

ALTER TABLE ingest.collection_run
    ADD COLUMN scheduled_at timestamptz;

UPDATE ingest.collection_run
   SET scheduled_at = started_at
 WHERE scheduled_at IS NULL;

ALTER TABLE ingest.collection_run
    ALTER COLUMN scheduled_at SET DEFAULT transaction_timestamp(),
    ALTER COLUMN scheduled_at SET NOT NULL;

COMMENT ON COLUMN ingest.collection_run.scheduled_at IS
    'UTC scheduler instant; distinct from the actual collector start.';

ALTER TABLE ingest.account_metric_snapshot
    ADD COLUMN collected_at timestamptz;

UPDATE ingest.account_metric_snapshot
   SET collected_at = GREATEST(observed_at, created_at)
 WHERE collected_at IS NULL;

ALTER TABLE ingest.account_metric_snapshot
    ALTER COLUMN collected_at SET DEFAULT transaction_timestamp(),
    ALTER COLUMN collected_at SET NOT NULL;

ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_metric_snapshot_collection_order_ck
    CHECK (collected_at >= observed_at) NOT VALID;

ALTER TABLE ingest.account_metric_snapshot
    VALIDATE CONSTRAINT account_metric_snapshot_collection_order_ck;

CREATE INDEX account_metric_snapshot_collected_brin
    ON ingest.account_metric_snapshot USING brin (collected_at);

COMMENT ON COLUMN ingest.account_metric_snapshot.collected_at IS
    'UTC instant when the target collector received the observation.';

ALTER TABLE ingest.publication_metric_snapshot
    ADD COLUMN collected_at timestamptz;

UPDATE ingest.publication_metric_snapshot
   SET collected_at = GREATEST(observed_at, created_at)
 WHERE collected_at IS NULL;

ALTER TABLE ingest.publication_metric_snapshot
    ALTER COLUMN collected_at SET DEFAULT transaction_timestamp(),
    ALTER COLUMN collected_at SET NOT NULL;

ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_metric_snapshot_collection_order_ck
    CHECK (collected_at >= observed_at) NOT VALID;

ALTER TABLE ingest.publication_metric_snapshot
    VALIDATE CONSTRAINT publication_metric_snapshot_collection_order_ck;

CREATE INDEX publication_metric_snapshot_collected_brin
    ON ingest.publication_metric_snapshot USING brin (collected_at);

COMMENT ON COLUMN ingest.publication_metric_snapshot.collected_at IS
    'UTC instant when the target collector received the observation.';

-- Account presentation/native identifiers are observations owned by the
-- collector pipeline. Administrative fields (institution, enabled, access
-- mode and canonical identity) remain unavailable for collector mutation.
GRANT SELECT, INSERT ON
    catalog.account_identity_history,
    catalog.account_external_identity
TO collector_ingest;

GRANT UPDATE (valid_to) ON catalog.account_identity_history TO collector_ingest;
GRANT UPDATE (valid_to) ON catalog.account_external_identity TO collector_ingest;

GRANT UPDATE (
    current_username,
    current_title,
    current_url,
    updated_at,
    row_version
) ON catalog.platform_account TO collector_ingest;

GRANT USAGE, SELECT ON SEQUENCE
    catalog.account_identity_history_id_seq,
    catalog.account_external_identity_id_seq
TO collector_ingest;
