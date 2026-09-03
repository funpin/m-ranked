from datetime import datetime, timezone
import sqlite3

import pytest

from app.backup import create_backup


def _database(path, value: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sample(value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample(value) VALUES(?)", (value,))


def test_create_backup_copies_live_wal_database_and_verifies_it(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backups"
    _database(source, "preserved")

    target = create_backup(
        source,
        destination,
        now=datetime(2026, 9, 1, 0, 15, tzinfo=timezone.utc),
    )

    assert target.name == "reactions-20260901T001500Z.db"
    assert target.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "preserved"

    create_backup(
        source,
        destination,
        now=datetime(2026, 9, 2, 0, 15, tzinfo=timezone.utc),
    )
    assert [path.name for path in destination.glob("reactions-*.db")] == [
        "reactions-20260902T001500Z.db"
    ]


def test_create_backup_rotates_only_scheduled_backups(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backups"
    _database(source, "current")
    manual = destination / "manual-before-release.db"
    destination.mkdir()
    manual.write_bytes(b"manual")

    for day in range(1, 5):
        create_backup(
            source,
            destination,
            keep=3,
            now=datetime(2026, 9, day, tzinfo=timezone.utc),
        )

    assert [path.name for path in sorted(destination.glob("reactions-*.db"))] == [
        "reactions-20260902T000000Z.db",
        "reactions-20260903T000000Z.db",
        "reactions-20260904T000000Z.db",
    ]
    assert manual.read_bytes() == b"manual"


def test_create_backup_rejects_invalid_retention(tmp_path):
    source = tmp_path / "source.db"
    _database(source, "current")
    with pytest.raises(ValueError, match="keep must be positive"):
        create_backup(source, tmp_path / "backups", keep=0)
