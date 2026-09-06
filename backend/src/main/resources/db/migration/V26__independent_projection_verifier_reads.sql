-- Read-only original-formula reconciliation runs in the bridge's existing
-- repeatable-read transaction. These are already-public derived projections.
-- No observation, evidence, archive fact or administrative write grant changes.
SET ROLE migration_owner;
GRANT SELECT ON analytics.institution_period_metrics,
    analytics.comparison_cohort,
    analytics.comparison_cohort_member,
    analytics.comparison_publication_hourly
TO migration_bridge;
RESET ROLE;
