from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_backup(
    source: str | Path,
    destination_dir: str | Path,
    *,
    keep: int = 7,
    now: datetime | None = None,
) -> Path:
    """Create and verify a transactionally consistent online SQLite backup."""
    source_path = Path(source).resolve()
    destination = Path(destination_dir).resolve()
    if keep <= 0:
        raise ValueError("keep must be positive")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    destination.mkdir(parents=True, exist_ok=True)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    filename = f"reactions-{moment.strftime('%Y%m%dT%H%M%SZ')}.db"
    target = destination / filename
    temporary = destination / f".{filename}.tmp"
    temporary_sidecars = (
        Path(f"{temporary}-wal"),
        Path(f"{temporary}-shm"),
    )
    if target.exists():
        raise FileExistsError(target)
    if temporary.exists():
        temporary.unlink()

    source_uri = f"{source_path.as_uri()}?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=60) as source_conn:
            with sqlite3.connect(temporary) as backup_conn:
                source_conn.backup(backup_conn, pages=4096, sleep=0.05)
                # A WAL source carries its persistent journal mode into the
                # destination.  Backups are intentionally standalone files.
                backup_conn.execute("PRAGMA journal_mode=DELETE")
                check = backup_conn.execute("PRAGMA quick_check").fetchone()
                if check is None or check[0] != "ok":
                    raise RuntimeError(f"backup integrity check failed: {check!r}")
        os.chmod(temporary, 0o600)
        _fsync_file(temporary)
        os.replace(temporary, target)
        _fsync_directory(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
        for sidecar in temporary_sidecars:
            if sidecar.exists():
                sidecar.unlink()

    backups = sorted(destination.glob("reactions-????????T??????Z.db"))
    for expired in backups[:-keep]:
        expired.unlink()
    if len(backups) > keep:
        _fsync_directory(destination)
    return target


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Create a verified online backup of the m-ranked SQLite database",
    )
    command.add_argument("source", type=Path)
    command.add_argument("destination", type=Path)
    command.add_argument("--keep", type=int, default=7)
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    target = create_backup(args.source, args.destination, keep=args.keep)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
