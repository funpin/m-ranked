"""Select every tenth publication per account, keeping its entire history."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

root = Path(__file__).resolve().parents[2]
source = root / "data/local-review/source.sqlite"
destination = root / "data/local-review/sample-10.sqlite"
if destination.exists():
    raise FileExistsError(destination)
with source.open("rb") as stream:
    source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
if source_hash != source.with_suffix(".sha256").read_text().split()[0]:
    raise RuntimeError("Original production backup checksum mismatch")
shutil.copy2(source, destination)
try:
    with sqlite3.connect(destination) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for posts, account, snapshots, foreign_key in (
            ("posts", "channel_id", "reaction_snapshots", "post_id"),
            ("platform_posts", "platform_account_id", "platform_snapshots", "platform_post_id"),
        ):
            connection.execute(f"""CREATE TEMP TABLE keep_{posts} AS
                SELECT id FROM (SELECT id, row_number() OVER
                (PARTITION BY {account} ORDER BY published_at DESC, id DESC) AS position FROM {posts})
                WHERE (position-1)%10=0""")
            connection.execute(f"DELETE FROM {snapshots} WHERE {foreign_key} NOT IN (SELECT id FROM keep_{posts})")
            if posts == "posts":
                connection.execute("DELETE FROM post_messages WHERE post_id NOT IN (SELECT id FROM keep_posts)")
            connection.execute(f"DELETE FROM {posts} WHERE id NOT IN (SELECT id FROM keep_{posts})")
        connection.commit()
        connection.execute("VACUUM")
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                  for table in ("institutions", "channels", "platform_accounts", "posts", "platform_posts", "reaction_snapshots", "platform_snapshots")}
    os.utime(destination, (source.stat().st_atime, source.stat().st_mtime))
    destination.chmod(0o600)
    with destination.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    destination.with_suffix(".sha256").write_text(checksum + "  sample-10.sqlite\n")
    manifest = {"sourceSha256": source_hash, "sha256": checksum, "rows": counts,
                "selection": "Newest publication and every tenth thereafter per account; complete snapshot history retained",
                "originalSnapshots": 3666730, "sampleSnapshots": counts["reaction_snapshots"] + counts["platform_snapshots"]}
    destination.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
except BaseException:
    # Leave the failed artifact for diagnosis; never mutate the original backup.
    raise
