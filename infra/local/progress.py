"""Publish aggregate import progress without exposing a database connection."""
import json
import os
from pathlib import Path
import sqlite3
import time

import psycopg

source = Path("/source") / os.environ.get("LOCAL_SOURCE_FILE", "source.sqlite")
with sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True) as legacy:
    total = sum(legacy.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ("reaction_snapshots", "platform_snapshots"))
destination = Path("/progress/progress.jsonl")
first_count = None
started = time.monotonic()
while True:
    try:
        with psycopg.connect(os.environ["BRIDGE_DATABASE_URL"], connect_timeout=5) as connection:
            count = int(connection.execute("SELECT coalesce(sum(rows_processed),0) FROM migration.checkpoint WHERE stream_name IN ('reaction_snapshots','platform_snapshots')").fetchone()[0])
            batch = connection.execute("SELECT status::text FROM migration.import_batch ORDER BY started_at DESC LIMIT 1").fetchone()
        if first_count is None:
            first_count = count
            started = time.monotonic()
        elapsed = time.monotonic() - started
        rate = (count - first_count) / elapsed if elapsed > 0 else 0
        complete = Path("/import/seed-complete.json").exists()
        seed = "exited 0" if complete else "exited 1" if batch and batch[0] == "failed" else "running 0"
        status = {"time": time.strftime("%H:%M:%S"), "snapshots": count, "total": total,
                  "percent": round(count / total * 100, 1) if total else 100,
                  "rowsPerSecond": round(rate), "seed": seed}
        if rate > 0:
            status["remainingImportMinutes"] = round((total - count) / rate / 60)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(status) + "\n")
        temporary.replace(destination)
        print(json.dumps(status), flush=True)
    except psycopg.Error as error:
        print("Waiting for import database: " + type(error).__name__, flush=True)
    time.sleep(30)
