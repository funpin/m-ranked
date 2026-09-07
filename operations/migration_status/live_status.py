"""Publish exact PostgreSQL measurement and host-disk statistics."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


def atomic_write(path: Path, payload: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".live-status-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_status(connection, disk_path: Path) -> dict:
    row = connection.execute(
        """SELECT count(*)::bigint AS database_rows,
                  pg_database_size(current_database())::bigint AS database_bytes
             FROM ingest.publication_metric_snapshot"""
    ).fetchone()
    usage = shutil.disk_usage(disk_path)
    used = usage.total - usage.free
    return {
        "databaseRows": int(row[0]),
        "databaseSizeGiB": round(int(row[1]) / (1024 ** 3), 2),
        "diskUsedPercent": round(used * 100 / usage.total, 2),
        "diskUsedGiB": round(used / (1024 ** 3), 2),
        "diskTotalGiB": round(usage.total / (1024 ** 3), 2),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def publish_once(output: Path, disk_path: Path) -> None:
    import psycopg

    with psycopg.connect(
        os.environ["MRANKED_STATUS_DATABASE_URL"],
        connect_timeout=5,
        options="-c statement_timeout=30000",
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        atomic_write(output, build_status(connection, disk_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--disk-path", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 10:
        raise SystemExit("interval must be at least 10 seconds")
    while True:
        try:
            publish_once(args.output, args.disk_path)
        except Exception as error:
            print(f"live status unavailable: {type(error).__name__}", flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
