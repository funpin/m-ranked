-- The public activity-rating query needs only the account audience counter and
-- publication routing identity. Keep raw payload, fingerprints, run IDs and all
-- publication metric snapshots outside the api_read role.

SET ROLE migration_owner;

GRANT SELECT (
    id,
    platform_account_id,
    observed_at,
    subscriber_count,
    quality,
    collected_at
) ON ingest.account_metric_snapshot TO api_read;

GRANT SELECT (
    id,
    publication_id,
    external_id,
    role,
    public_url
) ON ingest.publication_identity TO api_read;

RESET ROLE;
