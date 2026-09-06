"""Import a verified production backup once, preserving later local edits."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import time

import psycopg

sys.path.insert(0, "/app")
state = Path("/state")
source = Path("/source") / os.environ.get("LOCAL_SOURCE_FILE", "source.sqlite")
with source.open("rb") as stream:
    source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
expected_hash = source.with_suffix(".sha256").read_text().split()[0]
if source_hash != expected_hash:
    raise RuntimeError("Selected local source checksum mismatch")
marker = state / "seed-complete.json"
if marker.exists():
    if json.loads(marker.read_text())["sourceSha256"] != source_hash:
        raise RuntimeError("A different backup requires a separate local Docker project")
    print("Local dataset already initialized; preserving data and local edits.")
    sys.exit(0)
if os.environ.get("LOCAL_IMPORT_ENABLED", "false").lower() != "true":
    raise RuntimeError("Further import disabled by user; initialize the retained local dataset first")

for attempt in range(120):
    try:
        with psycopg.connect(os.environ["LOCAL_BOOTSTRAP_DSN"]) as connection:
            count = connection.execute('SELECT count(*) FROM flyway.flyway_schema_history WHERE success AND version = \'29\'').fetchone()[0]
            if count == 1:
                break
    except psycopg.Error:
        pass
    time.sleep(2)
else:
    raise RuntimeError("Flyway V29 did not become ready")

# Legacy period analytics intentionally uses baseline_from_publication even
# after history is forced incomplete. V29 projections implement this too, but
# V1's table constraint rejects the state present in real production data.
# Keep both source facts. This explicit local-only compatibility adjustment is
# not a Flyway migration and does not claim an unmodified release schema.
with sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True) as legacy:
    affected = legacy.execute("SELECT count(*) FROM posts WHERE baseline_from_publication=1 AND history_forced_incomplete=1").fetchone()[0]
if affected:
    with psycopg.connect(os.environ["LOCAL_BOOTSTRAP_DSN"]) as connection:
        connection.execute("ALTER TABLE ingest.publication DROP CONSTRAINT IF EXISTS publication_check1")
        present = connection.execute("SELECT 1 FROM pg_constraint WHERE conrelid='ingest.publication'::regclass AND conname='publication_local_legacy_baseline_check'").fetchone()
        if not present:
            connection.execute("""ALTER TABLE ingest.publication ADD CONSTRAINT publication_local_legacy_baseline_check
                CHECK (NOT synthetic_baseline_allowed OR history_completeness IN ('complete', 'forced_incomplete'))""")
    adjustment = {"localOnly": True, "affectedSourcePosts": affected,
                  "reason": "Preserve independent legacy baseline and forced-incomplete flags",
                  "productionApproved": False}
    (state / "local-schema-adjustment.json").write_text(json.dumps(adjustment, indent=2))
    print(json.dumps(adjustment), flush=True)

print("Importing the selected real-data sample and rebuilding projections...", flush=True)
subprocess.run([
    sys.executable, "-m", "migration.bridge", "import", str(source),
    "--source-namespace", os.environ.get("LOCAL_SOURCE_NAMESPACE", "docker-local-production-copy"), "--snapshot-kind", "s0",
    "--batch-size", "1000", "--report-dir", str(state / "reconciliation"),
    "--stem", "production-copy",
], check=True)
marker.write_text(json.dumps({"sourceSha256": source_hash}, indent=2))
print("Production backup imported locally; all projections are ready.")
