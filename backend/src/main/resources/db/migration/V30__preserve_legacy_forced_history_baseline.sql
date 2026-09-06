SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

-- Legacy stores the publication-time baseline decision independently from a
-- later forced-incomplete classification. Preserve both original facts during
-- import: changing either would change historical period calculations.
-- Native collection still creates baselines only for complete history; an
-- existing forced-incomplete baseline may only be retained, never inferred.
ALTER TABLE ingest.publication
    DROP CONSTRAINT publication_check1,
    ADD CONSTRAINT publication_baseline_history_check CHECK (
        NOT synthetic_baseline_allowed
        OR history_completeness IN ('complete', 'forced_incomplete')
    );

COMMENT ON CONSTRAINT publication_baseline_history_check ON ingest.publication IS
'Allows the independent original legacy baseline on forced-incomplete history. Native normalization must not create such a baseline; collector refresh preserves an already stored decision.';

RESET ROLE;
