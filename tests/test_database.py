from datetime import datetime, timedelta, timezone
import sqlite3
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
        {"👍": 173}, [], 5, 15, 2.0, comments_count=12, views_count=370,
    )
    rows = db.query(
        "SELECT total_reactions, delta_total, comments_count, delta_comments, "
        "views_count, delta_views, synthetic "
        "FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at",
        (post_id,),
    )
    assert [row["total_reactions"] for row in rows] == [0, 173]
    assert rows[1]["delta_total"] == 173
    assert rows[0]["comments_count"] == 0
    assert rows[1]["comments_count"] == 12
    assert rows[1]["delta_comments"] == 12
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
    assert not db.list_platform_accounts()
    assert not db.list_institutions()


def test_telegram_channel_is_linked_to_platform_account(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    channel_id = db.add_channel("example")
    channel = db.channel(channel_id)
    assert channel["institution_id"] is not None
    assert channel["platform_account_id"] is not None

    institutions = db.list_institutions()
    accounts = db.list_platform_accounts(int(channel["institution_id"]))
    assert len(institutions) == 1
    assert len(accounts) == 1
    assert accounts[0]["platform"] == "telegram"
    assert accounts[0]["external_key"] == "example"

    vk_id = db.add_platform_account(
        int(channel["institution_id"]), "vk", "university", "university",
        "University VK", "https://vk.com/university",
    )
    assert vk_id != int(channel["platform_account_id"])
    assert {row["platform"] for row in db.list_platform_accounts()} == {"telegram", "vk"}


def test_channel_can_be_linked_to_named_institution_and_names_are_editable(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("Полное название", "Короткое")
    channel_id = db.add_channel("named_channel", institution_id=institution_id)

    channel = db.list_channels_with_institutions()[0]
    assert int(channel["id"]) == channel_id
    assert int(channel["institution_id"]) == institution_id
    assert channel["institution_name"] == "Полное название"
    assert channel["institution_short_name"] == "Короткое"
    assert len(db.list_institutions()) == 1

    assert db.update_institution(institution_id, "Новое полное", "Новое короткое")
    updated = db.list_channels_with_institutions()[0]
    assert updated["institution_name"] == "Новое полное"
    assert updated["institution_short_name"] == "Новое короткое"


def test_existing_channel_is_moved_without_leaving_placeholder_institution(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    channel_id = db.add_channel("move_me")
    target_id = db.add_institution("Целевой вуз", "ЦВ")

    assert db.add_channel("move_me", institution_id=target_id) == channel_id
    channel = db.channel(channel_id)
    assert int(channel["institution_id"]) == target_id
    assert [row["name"] for row in db.list_institutions()] == ["Целевой вуз"]


def test_platform_migration_backfills_existing_channel_once(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                title TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL,
                last_seen_message_id INTEGER NOT NULL DEFAULT 0,
                last_checked_at TEXT,
                last_error TEXT,
                subscriber_count INTEGER,
                subscriber_count_display TEXT,
                subscriber_measured_at TEXT,
                m_rating_tg_rank INTEGER,
                m_rating_tg_score REAL,
                m_rating_period TEXT,
                m_rating_measured_at TEXT
            );
            INSERT INTO channels(
                telegram_id, username, title, enabled, added_at,
                subscriber_count, subscriber_count_display
            ) VALUES(123, 'legacy', 'Legacy University', 1,
                     '2026-08-01T00:00:00+00:00', 1000, '1K');
        """)
    db = Database(path)
    db.migrate()
    before = (
        len(db.list_institutions()), len(db.list_platform_accounts()),
        db.query("SELECT max(version) version FROM schema_migrations")[0]["version"],
    )
    db.migrate()
    after = (
        len(db.list_institutions()), len(db.list_platform_accounts()),
        db.query("SELECT max(version) version FROM schema_migrations")[0]["version"],
    )
    assert before == after == (1, 1, 7)
    account = db.list_platform_accounts()[0]
    assert account["native_id"] == "123"
    assert account["subscriber_count"] == 1000
