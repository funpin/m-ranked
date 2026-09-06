"""Publish only committed local data after the user stops an import."""
import json
import os
from pathlib import Path
import time

import psycopg

started = time.monotonic()
with psycopg.connect(os.environ["LOCAL_BOOTSTRAP_DSN"]) as connection:
    batch_id, source_hash = connection.execute("SELECT id,source_sha256 FROM migration.import_batch ORDER BY started_at DESC LIMIT 1").fetchone()
    revision = connection.execute("SELECT max(id) FROM analytics.dataset_revision").fetchone()[0]
    snapshots = connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot").fetchone()[0]
    platforms = dict(connection.execute("""SELECT a.platform::text,count(*)
        FROM ingest.publication_metric_snapshot s JOIN ingest.publication p ON p.id=s.publication_id
        JOIN catalog.platform_account a ON a.id=p.primary_account_id GROUP BY 1""").fetchall())
    connection.execute("UPDATE ingest.collection_run SET status='partial',completed_at=clock_timestamp() WHERE correlation_id=%s", (batch_id,))
    connection.execute("""UPDATE migration.import_batch SET status='cancelled',finished_at=clock_timestamp(),
        rows_read=(SELECT coalesce(sum(rows_processed),0) FROM migration.checkpoint WHERE batch_id=%s),
        error_summary='User stopped local import; only committed data retained for UI review'
        WHERE id=%s""", (batch_id, batch_id))
    print(f"Building projections from {snapshots} already loaded snapshots; no source import is running.", flush=True)
    projections = connection.execute("SELECT analytics.rebuild_core_projections(%s)", (revision,)).fetchone()[0]
    result = {"sourceSha256": source_hash, "mode": "user-stopped-partial", "importComplete": False,
              "loadedSnapshots": snapshots, "platformSnapshots": platforms, "revision": revision,
              "projections": projections, "fullSourceReconciliation": "not-run-partial-dataset",
              "productionApproved": False}
result["seconds"] = round(time.monotonic() - started, 2)
Path("/state/partial-dataset.json").write_text(json.dumps(result, indent=2))
Path("/state/seed-complete.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2), flush=True)
