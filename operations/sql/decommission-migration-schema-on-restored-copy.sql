-- DESTRUCTIVE REHEARSAL ONLY. Never add this file to Flyway or deploy/maintenance.
-- Run as migration_owner against a restored disposable database whose name ends
-- in _restore, _rehearsal, or _disposable, with the explicit session guard:
--   PGOPTIONS='-c mranked.allow_disposable_migration_drop=true' psql ... -f this-file
\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '15min';

DO $guard$
DECLARE
    installed_contract text;
BEGIN
    IF current_setting('mranked.allow_disposable_migration_drop', true)
           IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'disposable migration-drop session guard is absent';
    END IF;
    IF current_database() !~ '(_restore|_rehearsal|_disposable)$' THEN
        RAISE EXCEPTION 'database % is not explicitly named as disposable',
            current_database();
    END IF;
    IF NOT pg_has_role(current_user, 'migration_owner', 'USAGE') THEN
        RAISE EXCEPTION 'current user cannot assume migration_owner';
    END IF;
    IF to_regnamespace('migration') IS NULL THEN
        RAISE EXCEPTION 'migration schema is already absent';
    END IF;
    SELECT contract_id
      INTO installed_contract
      FROM ops_and_admin.schema_contract;
    IF installed_contract IS DISTINCT FROM 'storage-publisher-final-2026-09-08-r3' THEN
        RAISE EXCEPTION 'final runtime schema contract is not installed';
    END IF;
    IF to_regclass('catalog.legacy_entity_alias') IS NULL THEN
        RAISE EXCEPTION 'canonical legacy identifier mapping is absent';
    END IF;
END
$guard$;

SET LOCAL ROLE migration_owner;

-- These compatibility entry points are superseded by the final canonical-only
-- functions. RESTRICT makes an unexpected caller/dependency abort the rehearsal.
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v23(bigint) RESTRICT;
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v17(bigint) RESTRICT;
DROP FUNCTION IF EXISTS analytics.rebuild_core_projections_v16(bigint) RESTRICT;
DROP FUNCTION IF EXISTS analytics.refresh_legacy_exports(bigint) RESTRICT;

-- Catalog dependencies catch views, constraints and other parsed references.
DO $dependency_guard$
DECLARE
    textual_reference_count bigint;
BEGIN
    SELECT count(*)
      INTO textual_reference_count
     FROM pg_proc AS procedure
      JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
     WHERE namespace.nspname <> 'migration'
       AND procedure.prokind IN ('f', 'p')
       AND pg_get_functiondef(procedure.oid) ~* 'migration[.]';

    IF textual_reference_count <> 0 THEN
        RAISE EXCEPTION
          'migration schema still has external function references: %',
          textual_reference_count;
    END IF;
END
$dependency_guard$;

-- Name every retired object. RESTRICT on the grouped table drop permits
-- dependencies within this exact set but aborts on any external dependency.
DROP TABLE
    migration.checkpoint,
    migration.final_delta_checkpoint_20260907,
    migration.identity_map_history,
    migration.import_batch,
    migration.legacy_evidence,
    migration.legacy_export_lexeme,
    migration.legacy_identity_map,
    migration.preserved_canonical_fact,
    migration.preserved_source_decision,
    migration.reconciliation_result,
    migration.source_change_event,
    migration.source_disappearance,
    migration.source_disappearance_decision,
    migration.source_preservation
RESTRICT;

DROP FUNCTION
    migration.guard_identity_map_tip(),
    migration.reject_history_mutation()
RESTRICT;

DROP TYPE
    migration.batch_status,
    migration.reconciliation_status
RESTRICT;

-- The empty schema can now be removed without CASCADE.
DROP SCHEMA migration RESTRICT;

DO $postcondition$
BEGIN
    IF to_regnamespace('migration') IS NOT NULL THEN
        RAISE EXCEPTION 'migration schema remains after drop';
    END IF;
    IF to_regclass('flyway.flyway_schema_history') IS NULL
       OR to_regclass('catalog.legacy_entity_alias') IS NULL THEN
        RAISE EXCEPTION 'protected Flyway or legacy-alias object was lost';
    END IF;
END
$postcondition$;

COMMIT;
