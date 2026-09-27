-- Successful per-post reads for a small opt-in cohort. Not a general log.
-- This table starts empty: change-only history cannot be backfilled into reads.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE ingest.publication_poll_receipt (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    cadence_seconds integer NOT NULL,
    observed_bucket bigint NOT NULL,
    observed_at timestamptz NOT NULL,
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id) ON DELETE CASCADE,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    views_quality ingest.observation_quality NOT NULL,
    reactions_quality ingest.observation_quality NOT NULL,
    comments_quality ingest.observation_quality NOT NULL,
    shares_quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean NOT NULL,
    snapshot_written boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT publication_poll_receipt_pkey
        PRIMARY KEY (publication_id, cadence_seconds, observed_bucket),
    CONSTRAINT publication_poll_receipt_cadence_check
        CHECK (cadence_seconds BETWEEN 300 AND 3600),
    CONSTRAINT publication_poll_receipt_bucket_check
        CHECK (observed_bucket >= 0),
    CONSTRAINT publication_poll_receipt_views_check
        CHECK (views_count IS NULL OR views_count >= 0),
    CONSTRAINT publication_poll_receipt_reactions_check
        CHECK (reactions_count IS NULL OR reactions_count >= 0),
    CONSTRAINT publication_poll_receipt_comments_check
        CHECK (comments_count IS NULL OR comments_count >= 0),
    CONSTRAINT publication_poll_receipt_shares_check
        CHECK (shares_count IS NULL OR shares_count >= 0)
);

CREATE INDEX publication_poll_receipt_observed_idx
    ON ingest.publication_poll_receipt (observed_at);

GRANT SELECT, INSERT, DELETE ON ingest.publication_poll_receipt TO collector_ingest;
GRANT SELECT ON ingest.publication_poll_receipt TO analytics_worker;

COMMENT ON TABLE ingest.publication_poll_receipt IS
    'Short-lived successful post reads in a bounded opt-in cohort; absence outside the cohort is unknown, not zero';

COMMIT;
