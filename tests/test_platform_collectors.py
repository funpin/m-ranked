import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.database import Database
from app.max_api import MaxChannel, MaxPost, max_post_is_repost
from app.max_collector import MaxCollector
from app.rutube import RutubeChannel, RutubeVideo, RutubeVideoMetrics
from app.rutube_collector import RutubeCollector


def settings(tmp_path) -> Settings:
    return Settings(
        telegram_api_id=None, telegram_api_hash=None,
        telegram_session_path=tmp_path / "session", database_path=tmp_path / "db.sqlite",
        initial_channels=(), poll_interval_minutes=5, track_post_for_hours=960,
        complete_history_max_first_age_minutes=6, jump_min_abs=15, jump_min_ratio=2.0,
        web_host="127.0.0.1", web_port=8080, display_timezone="Europe/Moscow",
        log_path=tmp_path / "app.log", discovery_limit=100, discovery_overlap=20,
        max_user_phone="+79990000000",
        max_session_path=tmp_path / "max.session.db",
    )


class FakeRutube:
    def __init__(self):
        self.video_calls = 0

    async def resolve_channel(self, reference, url=None):
        return 77

    async def videos(self, channel_id, limit=100):
        self.video_calls += 1
        video = RutubeVideo(
            "video-1", "Видео", datetime.now(timezone.utc) - timedelta(hours=1),
            321, "https://rutube.ru/video/video-1/", {"hits": 321},
        )
        return RutubeChannel(77, "Вуз на Rutube", "https://rutube.ru/u/vuz/"), [video]

    async def subscriber_count(self, channel_id, url=None):
        return 654

    async def video_metrics(self, video_id):
        return RutubeVideoMetrics(
            likes=17, comments=4,
            raw={"vote": {"positive": 17}, "comments": {"comments_count": 4}},
        )

    async def close(self):
        pass


class FakeMax:
    def __init__(self, discovery_posts=None, point_posts=None):
        self.discovery_posts = discovery_posts
        self.point_posts = point_posts or []
        self.resolved = []
        self.requested_ids = []

    async def resolve_channel(self, reference, chat_id=None):
        self.resolved.append((reference, chat_id))
        return MaxChannel(chat_id or -123, "MAX вуза", 456, "https://max.ru/vuz")

    async def posts(self, chat_id, count=100):
        if self.discovery_posts is not None:
            return self.discovery_posts
        return [MaxPost(
            id="m1",
            published_at=datetime.now(timezone.utc) - timedelta(hours=1),
            views=90,
            reactions=8,
            reposts=None,
            comments=None,
            url=None,
            raw={"message_id": "m1"},
            reaction_breakdown={"LIKE": 5, "FIRE": 3},
            is_repost=True,
        )]

    async def posts_by_ids(self, chat_id, message_ids):
        self.requested_ids.extend(message_ids)
        return [post for post in self.point_posts if post.id in message_ids]

    async def close(self):
        pass


def test_rutube_public_collector_stores_likes_and_comments(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    db.add_platform_account(institution, "rutube", "vuz", url="https://rutube.ru/u/vuz/")

    client = FakeRutube()
    collector = RutubeCollector(cfg, db, client)
    asyncio.run(collector.poll_cycle())
    asyncio.run(collector.poll_cycle())

    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert client.video_calls == 1
    assert len(db.query("SELECT * FROM platform_snapshots")) == 1
    assert snapshot["views_count"] == 321
    measured_at = datetime.fromisoformat(snapshot["measured_at"])
    assert snapshot["measurement_bucket"] == int(measured_at.timestamp()) // (60 * 60)
    assert snapshot["reactions_count"] == 17
    assert snapshot["comments_count"] == 4
    assert snapshot["shares_count"] is None
    assert db.list_platform_accounts(institution_id=institution)[0]["subscriber_count"] == 654


def test_max_collector_subscribes_resolves_chat_and_stores_supported_counters(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account_id = db.add_platform_account(
        institution, "max", "vuz", url="https://max.ru/vuz",
    )

    fake = FakeMax()
    asyncio.run(MaxCollector(cfg, db, fake).poll_cycle())

    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert fake.resolved == [("https://max.ru/vuz", None)]
    assert db.platform_account(account_id)["native_id"] == "-123"
    assert (snapshot["views_count"], snapshot["reactions_count"]) == (90, 8)
    assert snapshot["comments_count"] is None
    assert snapshot["shares_count"] is None
    assert db.query("SELECT is_repost FROM platform_posts")[0]["is_repost"] == 1


def test_max_session_is_ready_only_for_authorized_configured_phone(tmp_path):
    cfg = settings(tmp_path)
    assert cfg.max_user_session_ready is False
    with sqlite3.connect(cfg.max_session_path) as conn:
        conn.execute("CREATE TABLE sessions(token TEXT, phone TEXT)")
        conn.execute(
            "INSERT INTO sessions(token, phone) VALUES(?, ?)",
            ("saved-login-token", cfg.max_user_phone),
        )
    assert cfg.max_user_session_ready is True
    assert replace(cfg, max_user_phone="+78880000000").max_user_session_ready is False


def test_max_collector_refreshes_due_known_post_outside_history_page(tmp_path):
    cfg = replace(settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account_id = db.add_platform_account(institution, "max", "vuz")
    db.set_platform_account_native_id(account_id, "-123")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    post_id = db.upsert_platform_post(
        account_id, "700", published, published, "text", None, {},
    )
    db.insert_platform_snapshot(
        post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=None,
        shares_count=None, raw={},
    )
    refreshed = MaxPost(
        id="700", published_at=published, views=130, reactions=9,
        reposts=None, comments=None, url=None, raw={"id": 700},
    )
    fake = FakeMax(discovery_posts=[], point_posts=[refreshed])

    asyncio.run(MaxCollector(cfg, db, fake).poll_cycle())

    assert fake.requested_ids == ["700"]
    snapshots = db.platform_snapshots(post_id)
    assert len(snapshots) == 2
    assert (snapshots[-1]["views_count"], snapshots[-1]["reactions_count"]) == (130, 9)


def test_max_collector_marks_missing_post_deleted_after_two_point_checks(tmp_path):
    cfg = replace(settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account_id = db.add_platform_account(institution, "max", "vuz")
    db.set_platform_account_native_id(account_id, "-123")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    post_id = db.upsert_platform_post(
        account_id, "700", published, published, "text", None,
        {"text": "Архив MAX"},
    )
    db.insert_platform_snapshot(
        post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=None,
        shares_count=None, raw={},
    )
    fake = FakeMax(discovery_posts=[], point_posts=[])
    collector = MaxCollector(cfg, db, fake)

    asyncio.run(collector.poll_cycle())
    pending = db.platform_post(post_id)
    assert pending is not None
    assert pending["missing_check_count"] == 1
    assert pending["deleted_at"] is None

    asyncio.run(collector.poll_cycle())
    deleted = db.platform_post(post_id)
    assert deleted is not None
    assert deleted["missing_check_count"] == 2
    assert deleted["deleted_at"] is not None

    asyncio.run(collector.poll_cycle())
    assert fake.requested_ids == ["700", "700"]


def test_max_collector_does_not_mark_missing_when_point_lookup_fails(tmp_path):
    cfg = replace(settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account_id = db.add_platform_account(institution, "max", "vuz")
    db.set_platform_account_native_id(account_id, "-123")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    post_id = db.upsert_platform_post(
        account_id, "700", published, published, "text", None, {},
    )
    db.insert_platform_snapshot(
        post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=None,
        shares_count=None, raw={},
    )

    class ErrorMax(FakeMax):
        async def posts_by_ids(self, chat_id, message_ids):
            raise RuntimeError("MAX temporarily unavailable")

    asyncio.run(MaxCollector(
        cfg, db, ErrorMax(discovery_posts=[]),
    ).poll_cycle())

    stored = db.platform_post(post_id)
    assert stored is not None
    assert stored["missing_check_count"] == 0
    assert stored["deleted_at"] is None


def test_max_repost_requires_forward_from_another_chat():
    assert max_post_is_repost({"link": {"type": "forward", "chat_id": "-456"}}, -123)
    assert not max_post_is_repost(
        {"link": {"type": "forward", "chat_id": "-123"}}, -123,
    )
    assert not max_post_is_repost({"link": {"type": "reply", "chat_id": "-456"}}, -123)
    assert max_post_is_repost({"link": {"type": "forward", "chatId": "-456"}}, -123)
