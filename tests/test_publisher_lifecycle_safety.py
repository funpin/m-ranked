from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_application_targets_and_collectors_do_not_depend_on_publisher() -> None:
    shadow = _read("operations/systemd/m-ranked-shadow.target")
    target = _read("operations/systemd/m-ranked-target.target")
    collector = _read("operations/systemd/m-ranked-target-collector@.service")

    assert "m-ranked-target-projection-publisher.service" not in shadow
    assert "m-ranked-target-projection-publisher.service" not in target
    assert "m-ranked-target-projection-publisher.service" not in collector


def test_standard_deploy_does_not_control_or_gate_on_publisher() -> None:
    deploy = _read("operations/scripts/deploy-shadow.sh")
    activation = deploy.split('activation_failed=false', 1)[1]

    assert "systemctl restart m-ranked-target-projection-publisher.service" not in activation
    assert "systemctl stop m-ranked-target-projection-publisher.service" not in activation
    assert "is-active --quiet m-ranked-target-projection-publisher.service" not in activation


def test_publisher_service_is_explicit_bounded_oneshot() -> None:
    unit = _read("operations/systemd/m-ranked-target-projection-publisher.service")

    assert "Type=oneshot" in unit
    assert "ExecStartPre=" not in unit
    assert "ExecStart=/opt/m-ranked/current/operations/scripts/projection-publisher.sh --once" in unit
    assert "Restart=no" in unit
    assert "StartLimitIntervalSec=" in unit
    assert "StartLimitBurst=" in unit
    assert "WantedBy=m-ranked-shadow.target" not in unit
    assert "Before=m-ranked-target-collector@" not in unit


def test_two_gib_runtime_has_a_coherent_hard_memory_budget() -> None:
    api = _read("operations/systemd/m-ranked-target-api.service")
    web = _read("operations/systemd/m-ranked-target-web.service")
    collector = _read("operations/systemd/m-ranked-target-collector@.service")
    collector_slice = _read("operations/systemd/m-ranked-target-collectors.slice")
    compose = _read("infra/compose.yaml")
    small = _read("infra/compose.production-small.yaml")

    assert "-Xmx256m" in api and "MemoryMax=384M" in api
    assert "--max-old-space-size=128" in web and "MemoryMax=192M" in web
    assert "MemoryHigh=420M" in collector
    assert "MemoryMax=450M" in collector
    assert "Slice=m-ranked-target-collectors.slice" in collector
    assert "MemoryHigh=650M" in collector_slice
    assert "MemoryMax=700M" in collector_slice
    assert "MemorySwapMax=0" in api
    assert "MemorySwapMax=0" in web
    assert "MemorySwapMax=0" in collector
    assert "MemorySwapMax=0" in collector_slice
    assert "--maxmemory 48mb" in compose
    assert "--maxmemory-policy allkeys-lru" in compose
    assert "mem_limit: 512m" in small
    assert "mem_limit: 80m" in small


def test_heavy_publication_has_lock_capacity_guard_and_no_retry_loop() -> None:
    publisher = _read("operations/scripts/projection-publisher.sh")
    schema = _read("backend/src/main/resources/db/final-schema.sql")
    transition = _read("operations/sql/transition-production-to-final.sql")

    assert 'usage: $0 --once' in publisher
    assert "flock -n 9" in publisher
    assert "pg_table_size" in publisher
    assert "pg_indexes_size" in publisher
    assert "temp_bytes" in publisher
    assert "wal_bytes" in publisher
    assert schema.count("SET statement_timeout TO '2h'") == 6
    assert transition.count("SET statement_timeout = '2h'") == 1
    assert "PROJECTION_CAPACITY_MULTIPLIER" in publisher
    assert "PROJECTION_MIN_FREE_BYTES" in publisher
    assert "::numeric" in publisher
    assert "required_bytes=$((" not in publisher
    assert "old_heap_bytes=" in publisher
    assert "new_heap_bytes=" in publisher
    assert "temp_bytes=" in publisher
    assert "wal_bytes=" in publisher
    assert "analytics.rebuild_serving_projections" in publisher
    assert "analytics.rebuild_core_projections(CAST" not in publisher
    assert "no automatic retry was attempted" in publisher
    assert "while [[" not in publisher
    assert "sleep " not in publisher


def test_fixed_watermark_transition_does_not_lock_out_collectors() -> None:
    transition = _read("operations/sql/transition-production-to-final.sql")

    assert "rebuild_core_projections_v2(bigint)" in transition
    assert "LOCK TABLE analytics.dataset_revision IN SHARE MODE;" in transition
    assert "Captured watermarks do not block dataset revision writers" in transition
    assert "projection.rebuild.requested" in transition


def test_publication_history_and_clean_retention_are_in_the_serving_boundary() -> None:
    schema = _read("backend/src/main/resources/db/final-schema.sql")
    transition = _read("operations/sql/transition-production-to-final.sql")
    detail = _read(
        "backend/src/main/java/org/mranked/query/infrastructure/JdbcDetailQueries.java"
    )

    assert "rebuild_core_projections_v13(p_dataset_revision_id)" in schema
    assert "rebuild_core_projections_v13(p_dataset_revision_id)" in transition
    assert "'publication_metric_snapshot', 90" in schema
    assert "ON CONFLICT (data_class) DO UPDATE" in transition
    assert "h.dataset_revision_id=:revision" in detail
    assert "dataset_revision_id=:revision" in detail


def test_readiness_uses_last_published_revision_not_latest_raw_revision() -> None:
    readiness = _read(
        "backend/src/main/java/org/mranked/operations/infrastructure/JdbcReadinessProbe.java"
    )
    provider = _read(
        "backend/src/main/java/org/mranked/cache/infrastructure/JdbcDatasetRevisionProvider.java"
    )

    assert "latest_revision" not in readiness
    assert "revisionProvider.current()" in readiness
    assert "('publication_history')" in provider
    assert "HAVING count(state.projection_name) = 7" in provider
    assert "ORDER BY revision.id DESC" in provider


def test_admin_writes_queue_publication_instead_of_rebuilding_inline() -> None:
    repository = _read(
        "backend/src/main/java/org/mranked/admin/infrastructure/"
        "JdbcAdminCommandRepository.java"
    )
    transition = _read("operations/sql/transition-production-to-final.sql")

    assert "QUEUE_PROJECTION_SQL" in repository
    assert "'projection.rebuild.requested'" in repository
    assert "rebuild_core_projections(" not in repository
    assert "$patch_admin_publication$" in transition
    assert "ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid)" in transition
    assert "ops_and_admin.import_official_rating(jsonb,text,uuid)" in transition
    assert "'projection.rebuild.requested'" in transition
    assert "admin projection patch anchor is missing" in transition
    assert (
        "FROM PUBLIC, api_write_admin, collector_ingest, migration_bridge, maintenance;"
        in transition
    )
    assert (
        "GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)\n"
        "    TO maintenance, migration_bridge;"
        in transition
    )
