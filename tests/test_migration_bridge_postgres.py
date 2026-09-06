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


@pytest.mark.skipif(not POSTGRES_DSN, reason="requires disposable PostgreSQL")
def test_snapshot_batch_failure_resumes_committed_checkpoint(tmp_path: Path):
    source_path = tmp_path / "interrupted.db"
    build_golden_fixture(source_path)
    options = BridgeOptions(source_path, "pytest-interrupted-snapshots", batch_size=2,
                            verify_projections=True, verify_identity_history=True)

    class InterruptedBridge(BridgeService):
        attempts = 0

        def _import_snapshot(self, *args, **kwargs):
            writes = super()._import_snapshot(*args, **kwargs)
            self.attempts += 1
            if self.attempts == 3:
                raise RuntimeError("simulated interruption after snapshot writes")
            return writes

    with PostgresTarget(str(POSTGRES_DSN)) as target:
        interrupted = InterruptedBridge(options, LegacySource(source_path), target,
                                        snapshot_kind="s0")
        with pytest.raises(RuntimeError, match="simulated interruption"):
            interrupted.run()
        assert target.checkpoint(interrupted.batch_id, "platform_snapshots")[1:] == (2, False)
        assert target.fetchone(
            "SELECT count(*) FROM migration.legacy_identity_map WHERE source_namespace=%s "
            "AND source_table='platform_snapshots' AND target_type='publication_metric_snapshot'",
            (interrupted.source_namespace_uuid,),
        ) == (2,)

    with PostgresTarget(str(POSTGRES_DSN)) as target:
        stats, report = BridgeService(options, LegacySource(source_path), target,
                                      snapshot_kind="s0").run()
        assert stats.batch_id == interrupted.batch_id
        assert report["gate"]["status"] == "pass", report["mismatches"]
        retry_stats, retry_report = BridgeService(options, LegacySource(source_path), target,
                                                  snapshot_kind="s0").run()
        assert retry_report["gate"]["status"] == "pass"
        assert retry_stats.rows_written == 0


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
    # SQLite REAL values can require 17 significant decimal digits. Passing a
    # Python float directly through PostgreSQL float8 -> numeric loses the last
    # digits and must fail the independent exact-score reconciliation.
    for path in (source_v1, source_v2):
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute("UPDATE channels SET m_rating_tg_score=68.75625056695634")
                connection.execute("UPDATE institutions SET m_rating_tg_score=68.75625056695634 WHERE m_rating_tg_score IS NOT NULL")
                # Production contained a later forced-incomplete classification
                # alongside an independently retained publication-time baseline.
                connection.execute("UPDATE posts SET history_complete=0, history_forced_incomplete=1")
                assert connection.execute("SELECT baseline_from_publication FROM posts").fetchone() == (1,)
    namespace = "pytest-golden-integration"

    def run(source_path: Path, kind: str):
        source = LegacySource(source_path)
        options = BridgeOptions(
            source=source_path,
            source_namespace=namespace,
            batch_size=2,
        )
        with PostgresTarget(str(POSTGRES_DSN)) as target:
            service = BridgeService(
                options, source, target, snapshot_kind=kind
            )
            result = service.run()
            assert target.fetchone(
                "SELECT history_completeness::text,synthetic_baseline_allowed "
                "FROM ingest.publication WHERE id=%s",
                (service._publication_uuid("posts", 1),),
            ) == ("forced_incomplete", True)
            return result

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
