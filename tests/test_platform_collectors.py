import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.database import Database
from app.max_api import MaxChannel, MaxPost
from app.max_collector import MaxCollector
from app.rutube import RutubeChannel, RutubeVideo
from app.rutube_collector import RutubeCollector


def settings(tmp_path) -> Settings:
    return Settings(
        telegram_api_id=None, telegram_api_hash=None,
        telegram_session_path=tmp_path / "session", database_path=tmp_path / "db.sqlite",
        initial_channels=(), poll_interval_minutes=5, track_post_for_hours=960,
        complete_history_max_first_age_minutes=6, jump_min_abs=15, jump_min_ratio=2.0,
        web_host="127.0.0.1", web_port=8080, display_timezone="Europe/Moscow",
        log_path=tmp_path / "app.log", discovery_limit=100, discovery_overlap=20,
        max_access_token="max-token",
    )


class FakeRutube:
    async def resolve_channel(self, reference, url=None):
        return 77

    async def videos(self, channel_id, limit=100):
        video = RutubeVideo(
            "video-1", "Видео", datetime.now(timezone.utc) - timedelta(hours=1),
            321, "https://rutube.ru/video/video-1/", {"hits": 321},
        )
        return RutubeChannel(77, "Вуз на Rutube", "https://rutube.ru/u/vuz/"), [video]

    async def close(self):
        pass


class FakeMax:
    async def channel(self, chat_id):
        return MaxChannel(chat_id, "MAX вуза", 456, "https://max.ru/vuz")

    async def posts(self, chat_id, count=100):
        return [MaxPost(
            "m1", datetime.now(timezone.utc) - timedelta(hours=1),
            90, 4, 3, "https://max.ru/vuz/m1", {"message_id": "m1"},
        )]

    async def close(self):
        pass


def test_rutube_public_collector_preserves_unavailable_metrics_as_null(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    db.add_platform_account(institution, "rutube", "vuz", url="https://rutube.ru/u/vuz/")

    asyncio.run(RutubeCollector(cfg, db, FakeRutube()).poll_cycle())

    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert snapshot["views_count"] == 321
    assert snapshot["reactions_count"] is None
    assert snapshot["comments_count"] is None


def test_max_collector_requires_chat_id_and_stores_supported_counters(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account_id = db.add_platform_account(institution, "max", "vuz")
    db.set_platform_account_native_id(account_id, "-123")

    asyncio.run(MaxCollector(cfg, db, FakeMax()).poll_cycle())

    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert (snapshot["views_count"], snapshot["comments_count"], snapshot["shares_count"]) == (90, 3, 4)
    assert snapshot["reactions_count"] is None
