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


def test_platform_account_controls_keep_telegram_state_in_sync(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    channel_id = db.add_channel("university", institution_id=institution_id)
    channel = db.channel(channel_id)
    account_id = int(channel["platform_account_id"])
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        channel_id, "m:1", [1], None, now, now, 0, True, "text", False,
    )
    db.insert_snapshot(post_id, now, 0, 4, {"👍": 4}, [], 5, 15, 2.0)

    assert db.set_platform_account_enabled(account_id, False)
    assert not db.platform_account(account_id)["enabled"]
    assert not db.channel(channel_id)["enabled"]
    assert db.set_platform_account_enabled(account_id, True)
    assert db.platform_account(account_id)["enabled"]
    assert db.channel(channel_id)["enabled"]

    assert db.delete_platform_account(account_id)
    assert db.platform_account(account_id) is None
    assert db.channel(channel_id) is None
    assert not db.query("SELECT id FROM posts")
    assert not db.query("SELECT id FROM reaction_snapshots")
    assert int(db.list_institutions()[0]["id"]) == institution_id


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


def test_platform_posts_store_raw_cross_network_metrics(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(
        institution_id, "vk", "university", "university",
        "University", "https://vk.com/university",
    )
    published = datetime(2026, 8, 30, 8, tzinfo=timezone.utc)
    measured = published + timedelta(hours=1)
    post_id = db.upsert_platform_post(
        account_id, "-42_7", published, measured, "photo",
        "https://vk.com/wall-42_7", {"id": 7},
    )
    assert db.insert_platform_snapshot(
        post_id, measured, 3600, 5,
        views_count=100, reactions_count=5, comments_count=2,
        shares_count=1, raw={"likes": 5},
    )
    assert not db.insert_platform_snapshot(
        post_id, measured, 3600, 5,
        views_count=100, reactions_count=5, comments_count=2,
        shares_count=1, raw={"likes": 5},
    )
    row = db.query("SELECT * FROM platform_snapshots")[0]
    assert (row["views_count"], row["reactions_count"]) == (100, 5)
    assert (row["comments_count"], row["shares_count"]) == (2, 1)
    assert db.list_platform_accounts(platform="vk", enabled_only=True)[0]["id"] == account_id


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


def test_institution_stores_all_social_m_rating_slices(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("Университет", "У")
    measured_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
    db.update_institution_m_rating(
        institution_id,
        {
            "social": (1, 99.5), "tg": (2, 80.0), "vk": (3, 70.0),
            "max": (4, 60.0), "rutube": (5, 50.0),
        },
        "Июль 2026",
        measured_at,
    )
    institution = db.list_institutions()[0]
    assert institution["m_rating_social_rank"] == 1
    assert institution["m_rating_tg_rank"] == 2
    assert institution["m_rating_vk_rank"] == 3
    assert institution["m_rating_max_rank"] == 4
    assert institution["m_rating_rutube_rank"] == 5
    assert institution["m_rating_period"] == "Июль 2026"


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
    assert before == after == (1, 1, 11)
    account = db.list_platform_accounts()[0]
    assert account["native_id"] == "123"
    assert account["subscriber_count"] == 1000


def test_history_reset_and_vk_joint_id_migration_run_only_once(tmp_path):
    db = Database(tmp_path / "migration.db")
    db.migrate()
    channel_id = db.add_channel("legacy")
    now = datetime.now(timezone.utc)
    telegram_post_id = db.add_post(
        channel_id, "m:1", [1], None, now, now, 0, True, "text", False,
    )
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(institution_id, "vk", "university")
    db.set_platform_account_native_id(account_id, "74773715")
    platform_post_id = db.upsert_platform_post(
        account_id, "-74773715_59413", now, now, "photo", None,
        {
            "owner_id": -74773715,
            "id": 59413,
            "coowners": {
                "coowner_post_id": 1267,
                "list": [
                    {"owner_id": -164293611},
                    {"owner_id": -74773715},
                    {"owner_id": -777},
                ],
            },
        },
        history_complete=True,
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version IN (10, 11)")
    db.migrate()

    telegram = db.query("SELECT * FROM posts WHERE id=?", (telegram_post_id,))[0]
    platform = db.query("SELECT * FROM platform_posts WHERE id=?", (platform_post_id,))[0]
    assert (telegram["history_complete"], telegram["history_forced_incomplete"]) == (0, 1)
    assert (platform["history_complete"], platform["history_forced_incomplete"]) == (0, 1)
    assert platform["external_id"] == "-74773715_1267"
    assert platform["source_external_id"] == "-74773715_59413"
    assert platform["url"] == "https://vk.ru/wall-74773715_1267"
    assert platform["is_joint"] == 1
    assert platform["additional_author_count"] == 2

    new_platform_id = db.upsert_platform_post(
        account_id, "-74773715_1268", now, now, "text", None,
        {"owner_id": -74773715, "id": 1268}, history_complete=True,
    )
    db.migrate()
    new_platform = db.query(
        "SELECT history_complete, history_forced_incomplete FROM platform_posts WHERE id=?",
        (new_platform_id,),
    )[0]
    assert (new_platform["history_complete"], new_platform["history_forced_incomplete"]) == (1, 0)
