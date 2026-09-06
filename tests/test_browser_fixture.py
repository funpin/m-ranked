from contextlib import closing
import hashlib
from pathlib import Path
import runpy
import sqlite3


def test_overview_status_corpus_keeps_continuation_and_all_platforms(tmp_path):
    producer = Path(__file__).resolve().parents[1] / "frontend/scripts/legacy-fixture.py"
    build = runpy.run_path(str(producer))["build"]
    path = tmp_path / "overview.sqlite"
    manifest = build(path, overview_status_only=True)
    assert manifest["profile"] == "overview-status"
    assert manifest["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["counts"]["institutions"] == 207
    assert manifest["counts"]["channels"] == 206
    assert "overview_over_200" in manifest["coverage"]
    assert "rating_over_200" not in manifest["coverage"]
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        counts = dict(db.execute("SELECT platform,count(*) FROM platform_accounts GROUP BY platform"))
        assert counts == {"telegram": 206, "vk": 206, "max": 206, "rutube": 206}
        # The additional accounts exercise five overview pages per platform
        # without entering the minimum 24-hour comparison cohort.
        assert db.execute("SELECT count(*) FROM posts WHERE published_at='2026-08-01T10:00:00+00:00'").fetchone() == (205,)
        assert manifest["counts"]["reaction_snapshots"] == 618
        assert manifest["counts"]["platform_snapshots"] == 1848
