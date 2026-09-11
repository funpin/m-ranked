-- Minimal privileges for the bounded source-backed public API.
-- This script grants no write, sequence, DDL, or raw credential access.
BEGIN;

GRANT SELECT ON TABLE analytics.usable_publication_snapshot TO api_read;
GRANT SELECT ON TABLE ingest.account_metric_snapshot_active TO api_read;
GRANT SELECT ON TABLE ingest.collection_account_result TO api_read;
GRANT SELECT ON TABLE ingest.collection_run TO api_read;
GRANT SELECT ON TABLE ingest.reaction_breakdown TO api_read;
GRANT EXECUTE ON FUNCTION analytics.observation_quality_rank(ingest.observation_quality) TO api_read;
GRANT EXECUTE ON FUNCTION analytics.observation_quality_from_rank(integer) TO api_read;

COMMIT;
