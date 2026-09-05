from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import UUID

import pytest

import operations.reverse_sync.journal as journal_module
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.model import JournalState, canonical_json


UTC = timezone.utc
FIXED_NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def _state() -> JournalState:
    return JournalState(
        status="stopped",
        source_namespace="pytest/journal-temporal",
        operator="pytest",
        ticket="TEST-JOURNAL-UTC",
        started_at=FIXED_NOW,
        rollback_deadline=FIXED_NOW + timedelta(hours=24),
        s_final_batch_id=UUID("f34650c5-4161-44d6-9e5a-09d7f25c0874"),
        s_final_source_sha256="b" * 64,
        plan_digest="c" * 64,
        drained_at=FIXED_NOW + timedelta(hours=1),
        verified_at=FIXED_NOW + timedelta(hours=2),
        stopped_at=FIXED_NOW + timedelta(hours=3),
    )


@pytest.mark.parametrize(
    "field",
    [
        "started_at",
        "rollback_deadline",
        "drained_at",
        "verified_at",
        "stopped_at",
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [
        datetime(2026, 9, 4, 12),
        datetime(2026, 9, 4, 15, tzinfo=timezone(timedelta(hours=3))),
    ],
    ids=("naive", "non-utc"),
)
def test_save_state_rejects_every_non_utc_timestamp_before_writing(
    tmp_path: Path,
    field: str,
    invalid: datetime,
) -> None:
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()

    with pytest.raises(ValueError, match="UTC"):
        journal.save_state(replace(_state(), **{field: invalid}), "stopped")

    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM sync_state").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM journal_event").fetchone()[0] == 0


@pytest.mark.parametrize(
    "invalid_now",
    [
        datetime(2026, 9, 4, 12),
        datetime(2026, 9, 4, 15, tzinfo=timezone(timedelta(hours=3))),
    ],
    ids=("naive", "non-utc"),
)
def test_generated_event_binding_and_checkpoint_times_fail_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_now: datetime,
) -> None:
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    monkeypatch.setattr(journal_module, "utc_now", lambda: invalid_now)

    with pytest.raises(ValueError, match="UTC"):
        journal.save_state(_state(), "stopped")
    with pytest.raises(ValueError, match="UTC"):
        journal.record_alias(
            "reaction_snapshots",
            UUID("11111111-1111-4111-8111-111111111111"),
            101,
        )
    with pytest.raises(ValueError, match="UTC"):
        journal.record_applied((2,), "d" * 64)

    with sqlite3.connect(journal.path) as connection:
        counts = {
            table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in (
                "sync_state",
                "alias_reservation",
                "applied_revision",
                "journal_event",
            )
        }
        applied_meta = int(
            connection.execute(
                """SELECT count(*) FROM journal_meta
                    WHERE key IN ('last_applied_at','last_applied_plan_digest')"""
            ).fetchone()[0]
        )
    assert counts == {
        "sync_state": 0,
        "alias_reservation": 0,
        "applied_revision": 0,
        "journal_event": 0,
    }
    assert applied_meta == 0


@pytest.mark.parametrize(
    ("mutation", "expected_field"),
    [
        ("state", "journal datetime"),
        ("alias", "alias reservation timestamp"),
        ("event", "journal event timestamp"),
        ("checkpoint", "applied checkpoint timestamp"),
    ],
)
def test_integrity_rejects_persisted_non_utc_temporal_data(
    tmp_path: Path,
    mutation: str,
    expected_field: str,
) -> None:
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    journal.save_state(_state(), "stopped")
    journal.record_alias(
        "reaction_snapshots",
        UUID("11111111-1111-4111-8111-111111111111"),
        101,
    )
    journal.record_applied((2,), "d" * 64)
    bad_timestamp = "2026-09-04T15:00:00+03:00"

    with sqlite3.connect(journal.path) as connection:
        if mutation == "state":
            payload = json.loads(
                str(
                    connection.execute(
                        "SELECT payload FROM sync_state WHERE singleton=1"
                    ).fetchone()[0]
                )
            )
            payload["startedAt"] = bad_timestamp
            connection.execute(
                "UPDATE sync_state SET payload=? WHERE singleton=1",
                (canonical_json(payload),),
            )
        elif mutation == "alias":
            connection.execute(
                "UPDATE alias_reservation SET reserved_at=?",
                (bad_timestamp,),
            )
        elif mutation == "event":
            connection.execute(
                "UPDATE journal_event SET occurred_at=?",
                (bad_timestamp,),
            )
        else:
            connection.execute(
                "UPDATE journal_meta SET value=? WHERE key='last_applied_at'",
                (bad_timestamp,),
            )

    with pytest.raises(ValueError, match=expected_field):
        journal.integrity()


def test_every_write_connection_enforces_durable_pragmas(tmp_path: Path) -> None:
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()

    with journal.connect(write=True) as connection:
        actual: dict[str, Any] = {
            "journal_mode": str(
                connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).casefold(),
            "synchronous": int(
                connection.execute("PRAGMA synchronous").fetchone()[0]
            ),
            "foreign_keys": int(
                connection.execute("PRAGMA foreign_keys").fetchone()[0]
            ),
            "busy_timeout": int(
                connection.execute("PRAGMA busy_timeout").fetchone()[0]
            ),
        }

    assert actual == {
        "journal_mode": "wal",
        "synchronous": 2,
        "foreign_keys": 1,
        "busy_timeout": 30_000,
    }


def test_write_and_integrity_fail_closed_if_wal_mode_was_removed(
    tmp_path: Path,
) -> None:
    journal = ReverseSyncJournal(tmp_path / "journal.sqlite")
    journal.initialize()
    with sqlite3.connect(journal.path, isolation_level=None) as connection:
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"

    with pytest.raises(RuntimeError, match="WAL mode"):
        with journal.connect(write=True):
            pytest.fail("non-WAL journal accepted a write transaction")
    with pytest.raises(RuntimeError, match="WAL mode"):
        journal.integrity()
