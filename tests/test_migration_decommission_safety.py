from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_SCHEMA = ROOT / "backend/src/main/resources/db/final-schema.sql"
TRANSITION = ROOT / "operations/sql/transition-production-to-final.sql"
DROP_REHEARSAL = ROOT / "operations/sql/decommission-migration-schema-on-restored-copy.sql"


def test_runtime_transition_keeps_protected_mappings_and_history_in_place():
    transition = TRANSITION.read_text()
    assert "DROP SCHEMA migration" not in transition
    assert "flyway_schema_history" not in transition
    assert "DROP TABLE catalog.legacy_entity_alias" not in transition
    assert "DELETE FROM catalog.legacy_entity_alias" not in transition
    assert "entity_scope" in transition
    assert "CREATE FUNCTION analytics.rebuild_serving_projections" in transition


def test_schema_drop_is_an_explicit_fail_closed_disposable_rehearsal():
    sql = DROP_REHEARSAL.read_text()
    assert "mranked.allow_disposable_migration_drop" in sql
    assert "(_restore|_rehearsal|_disposable)" in sql
    assert "storage-publisher-final-2026-09-08-r2" in sql
    assert "to_regclass('flyway.flyway_schema_history')" in sql
    assert "to_regclass('catalog.legacy_entity_alias')" in sql
    assert "DROP SCHEMA migration RESTRICT" in sql
    assert "DROP SCHEMA migration CASCADE" not in sql


def test_hot_serving_entrypoints_do_not_reference_migration_schema():
    final = FINAL_SCHEMA.read_text()
    assert "rebuild_core_projections_v11" in final
    assert "rebuild_core_projections_v9(bigint)" in final
    assert "migration." not in final
