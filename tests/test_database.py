from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.database import Database
from app.maintenance import archive_and_purge


def _post(db: Database) -> int:
    channel_id = db.add_channel("example")
    now = datetime.now(timezone.utc)
    return db.add_post(
        channel_id, "m:1", [1], None, now, now, 0, True, "text", False
    )


def test_duplicate_snapshot_same_poll_bucket_is_ignored(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    post_id = _post(db)
    measured = datetime(2026, 8, 27, 14, 23, tzinfo=timezone.utc)
    args = (post_id, measured, 360, 2, {"👍": 2}, [], 60, 15, 2.0)
    assert db.insert_snapshot(*args)
    assert not db.insert_snapshot(*args)
    assert len(db.query("SELECT * FROM reaction_snapshots")) == 1


def test_snapshots_are_append_only_and_allow_negative_delta(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    post_id = _post(db)
    first = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
    assert db.insert_snapshot(post_id, first, 0, 57, {"👍": 57}, [], 60, 15, 2.0)
    assert db.insert_snapshot(
        post_id, first + timedelta(hours=1), 3600, 55, {"👍": 55}, [], 60, 15, 2.0
    )
    rows = db.query("SELECT total_reactions, delta_total FROM reaction_snapshots ORDER BY measured_at")
    assert [row["total_reactions"] for row in rows] == [57, 55]
    assert rows[1]["delta_total"] == -2


def test_timely_publication_baseline_sets_initial_growth(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    channel_id = db.add_channel("example")
    published = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
    post_id = db.add_post(
        channel_id, "m:2", [2], None, published,
        published + timedelta(minutes=4), 240, False, "text", False,
    )
    assert db.ensure_publication_baseline(post_id, published, 240, 360)
    assert db.insert_snapshot(
        post_id, published + timedelta(minutes=4), 240, 173,
        {"👍": 173}, [], 5, 15, 2.0, views_count=370,
    )
    rows = db.query(
        "SELECT total_reactions, delta_total, views_count, delta_views, synthetic "
        "FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at",
        (post_id,),
    )
    assert [row["total_reactions"] for row in rows] == [0, 173]
    assert rows[1]["delta_total"] == 173
    assert rows[1]["views_count"] == 370
    assert rows[1]["delta_views"] == 370
    assert rows[0]["synthetic"] == 1


def test_expired_posts_are_archived_before_purge(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    channel_id = db.add_channel("example")
    published = datetime(2026, 7, 1, tzinfo=timezone.utc)
    post_id = db.add_post(
        channel_id, "m:1", [1], None, published,
        published, 0, True, "text", False,
    )
    db.insert_snapshot(post_id, published, 0, 4, {"👍": 4}, [], 5, 15, 2.0)
    settings = SimpleNamespace(retention_days=31, archive_dir=tmp_path / "archives")
    removed = archive_and_purge(
        settings, db, datetime(2026, 8, 28, tzinfo=timezone.utc)
    )
    assert removed == 1
    assert not db.query("SELECT id FROM posts")
    archives = list((tmp_path / "archives").rglob("*.csv.gz"))
    assert len(archives) == 1


def test_delete_channel_removes_its_history(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    channel_id = db.add_channel("example")
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        channel_id, "m:1", [1], None, now, now, 0, True, "text", False
    )
    db.insert_snapshot(post_id, now, 0, 4, {"👍": 4}, [], 5, 15, 2.0)

    assert db.delete_channel(channel_id)
    assert db.channel(channel_id) is None
    assert not db.query("SELECT id FROM posts")
    assert not db.query("SELECT id FROM reaction_snapshots")
