-- Narrow read surface for the authenticated administrative run-status API.
-- Public api_read remains unable to inspect ingestion operations, and the
-- administrative role receives no observation or raw-payload access.

GRANT USAGE ON SCHEMA ingest TO api_write_admin;

GRANT SELECT ON
    ingest.collection_run,
    ingest.collection_account_result
TO api_write_admin;

-- Account configuration changes publish a new dataset revision only after all
-- revision-pinned projections are rebuilt in the same transaction. The
-- SECURITY DEFINER function owns those projection tables; the runtime role
-- receives no direct analytics mutation grants.
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
TO api_write_admin;
