from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3

import pytest

from migration.bridge.fixture import build_golden_fixture
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource, create_online_backup
from migration.bridge.target import PostgresTarget


POSTGRES_DSN = os.environ.get("MRANKED_TEST_POSTGRES_DSN")


@pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="set MRANKED_TEST_POSTGRES_DSN to run PostgreSQL bridge integration",
)
def test_postgres_bridge_repeat_catch_up_delete_gate_and_rollback(tmp_path: Path):
    source_v1 = tmp_path / "golden-v1.db"
    source_v2 = tmp_path / "golden-v2.db"
    source_deleted_live = tmp_path / "golden-deleted-live.db"
    source_final = tmp_path / "golden-s-final.db"
    build_golden_fixture(source_v1, revision=1)
    build_golden_fixture(source_v2, revision=2)
    namespace = "pytest-golden-integration"

    def run(source_path: Path, kind: str):
        source = LegacySource(source_path)
        options = BridgeOptions(
            source=source_path,
            source_namespace=namespace,
            batch_size=2,
        )
        with PostgresTarget(str(POSTGRES_DSN)) as target:
            return BridgeService(
                options, source, target, snapshot_kind=kind
            ).run()

    first_stats, first_report = run(source_v1, "s0")
    assert first_report["gate"] == {
        "status": "pass",
        "critical_mismatches": 0,
    }, first_report["mismatches"]
    assert first_stats.rows_written > 0

    repeat_stats, repeat_report = run(source_v1, "s0")
    assert repeat_report["gate"]["status"] == "pass"
    assert repeat_stats.batch_id == first_stats.batch_id
    assert repeat_stats.rows_written == 0

    catch_up_stats, catch_up_report = run(source_v2, "catch_up")
    assert catch_up_report["gate"]["status"] == "pass"
    assert catch_up_stats.batch_id != first_stats.batch_id

    create_online_backup(source_v2, source_deleted_live)
    # sqlite3.Connection's context manager commits but does not close. Closing
    # is required before LegacySource opens the WAL-mode backup as immutable;
    # otherwise a still-live WAL can hide this simulated hard delete.
    with closing(sqlite3.connect(source_deleted_live)) as connection:
        with connection:
            connection.execute("PRAGMA foreign_keys=ON")
            deleted = connection.execute(
                "DELETE FROM platform_posts WHERE external_id='video-1'"
            ).rowcount
            assert deleted == 1
    # A WAL-mode file is never imported directly. The SQLite Backup API folds
    # its committed WAL into a standalone, checksummed S-final artifact.
    create_online_backup(source_deleted_live, source_final)
    _deleted_stats, deleted_report = run(source_final, "s_final")
    assert deleted_report["gate"]["status"] == "fail"
    assert any(
        mismatch["check"] == "source_rows_missing_since_prior_batch"
        for mismatch in deleted_report["mismatches"]
    )

    rollback_stats, rollback_report = run(source_v2, "catch_up")
    assert rollback_report["gate"]["status"] == "pass"
    assert rollback_stats.rows_written > 0
