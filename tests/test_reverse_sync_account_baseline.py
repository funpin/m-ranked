import sqlite3
from pathlib import Path

import pytest

from migration.bridge.fixture import build_golden_fixture
from operations.reverse_sync.cli import _result_exit_code
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.sqlite_target import LegacySqliteTarget


def test_discovered_native_id_does_not_change_s_final_identity_across_restarts(tmp_path: Path):
    path = tmp_path / "legacy.sqlite"
    build_golden_fixture(path)
    target = LegacySqliteTarget(path, "account-baseline-test", min_free_bytes=0)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE platform_accounts SET native_id=NULL WHERE platform='max'")
        account_id = connection.execute("SELECT id FROM platform_accounts WHERE platform='max'").fetchone()[0]
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    journal.bind_account_baseline(target.capture_account_baseline())
    for revision in (10, 11, 11):
        restarted = LegacySqliteTarget(path, "account-baseline-test", min_free_bytes=0)
        restarted.account_identity_baseline = ReverseSyncJournal(journal.path).account_baseline()
        with restarted.connect(write=True) as connection:
            legacy = connection.execute("SELECT * FROM platform_accounts WHERE id=?", (account_id,)).fetchone()
            restarted._assert_canonical_account_identity(legacy, {
                "platform": "max", "canonical_external_id": "beta_max",
            })
            connection.execute("UPDATE platform_accounts SET native_id='200',username=?,title=? WHERE id=?",
                               (f"new_username_{revision}", f"Title {revision}", account_id))
    with target.connect() as connection:
        legacy = connection.execute("SELECT * FROM platform_accounts WHERE id=?", (account_id,)).fetchone()
        with pytest.raises(RuntimeError, match="canonical account"):
            restarted._assert_canonical_account_identity(legacy, {
                "platform": "max", "canonical_external_id": "200",
            })
    with pytest.raises(RuntimeError, match="baseline changed"):
        journal.bind_account_baseline(target.capture_account_baseline())


def test_expired_rollback_status_cannot_be_green_even_when_caught_up():
    assert _result_exit_code("status", {"lagRevisionCount": 0, "windowExpired": True}) == 1
