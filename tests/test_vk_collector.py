import asyncio
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.database import Database
from app.vk import VkCommunity, VkPost
from app.vk_collector import VkCollector


def _settings(tmp_path) -> Settings:
    return Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=tmp_path / "telegram.session",
        database_path=tmp_path / "vk.db",
        initial_channels=(),
        poll_interval_minutes=5,
        track_post_for_hours=960,
        complete_history_max_first_age_minutes=6,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        web_host="127.0.0.1",
        web_port=8080,
        display_timezone="Europe/Moscow",
        log_path=tmp_path / "app.log",
        discovery_limit=100,
        discovery_overlap=20,
        vk_access_token="test-token",
    )


class FakeVkClient:
    def __init__(self, post: VkPost):
        self.post = post
        self.closed = False

    async def community(self, reference: str) -> VkCommunity:
        assert reference == "university"
        return VkCommunity(42, "university", "University VK", 1234)

    async def wall(self, community_id: int, count: int = 100) -> list[VkPost]:
        assert community_id == 42
        return [self.post]

    async def close(self) -> None:
        self.closed = True


def test_vk_collector_stores_post_and_raw_snapshot(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(
        institution_id, "vk", "university", url="https://vk.com/university",
    )
    post = VkPost(
        owner_id=-42,
        post_id=7,
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        post_type="photo",
        views=100,
        likes=5,
        comments=2,
        reposts=1,
        raw={"owner_id": -42, "id": 7},
    )
    fake = FakeVkClient(post)
    collector = VkCollector(cfg, db, fake)
    asyncio.run(collector.poll_cycle())

    account = db.list_platform_accounts(platform="vk")[0]
    assert int(account["id"]) == account_id
    assert account["native_id"] == "42"
    assert account["subscriber_count"] == 1234
    assert account["last_error"] is None
    stored_post = db.query("SELECT * FROM platform_posts")[0]
    assert stored_post["external_id"] == "-42_7"
    assert stored_post["url"] == "https://vk.com/wall-42_7"
    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert (snapshot["views_count"], snapshot["reactions_count"]) == (100, 5)
    assert (snapshot["comments_count"], snapshot["shares_count"]) == (2, 1)
    assert db.get_state("vk_poll_last_error_count") == "0"
    assert db.get_state("vk_poll_last_account_count") == "1"
