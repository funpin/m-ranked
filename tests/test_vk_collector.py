import asyncio
from dataclasses import replace
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

    async def posts(self, post_ids: list[str]) -> list[VkPost]:
        return [self.post] if self.post.external_key in post_ids else []

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
    assert stored_post["url"] == "https://vk.ru/wall-42_7"
    snapshot = db.query("SELECT * FROM platform_snapshots")[0]
    assert (snapshot["views_count"], snapshot["reactions_count"]) == (100, 5)
    assert (snapshot["comments_count"], snapshot["shares_count"]) == (2, 1)
    assert db.get_state("vk_poll_last_error_count") == "0"
    assert db.get_state("vk_poll_last_account_count") == "1"


def test_vk_collector_refreshes_known_post_outside_wall_page(tmp_path):
    cfg = replace(_settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(institution_id, "vk", "university")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    old_post = VkPost(-42, 7, published, "text", 120, 8, 3, 2, {"id": 7})
    platform_post_id = db.upsert_platform_post(
        account_id, old_post.external_key, published, published, "text", None, {},
    )
    db.insert_platform_snapshot(
        platform_post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=2, shares_count=1, raw={},
    )

    class PointClient(FakeVkClient):
        async def wall(self, community_id: int, count: int = 100) -> list[VkPost]:
            return []

    asyncio.run(VkCollector(cfg, db, PointClient(old_post)).poll_cycle())

    snapshots = db.platform_snapshots(platform_post_id)
    assert len(snapshots) == 2
    assert snapshots[-1]["views_count"] == 120


def test_vk_collector_marks_missing_post_deleted_after_two_point_checks(tmp_path):
    cfg = replace(_settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(institution_id, "vk", "university")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    old_post = VkPost(-42, 7, published, "text", 120, 8, 3, 2, {"id": 7})
    platform_post_id = db.upsert_platform_post(
        account_id, old_post.external_key, published, published, "text",
        "https://vk.ru/wall-42_7", {"text": "Архив VK"},
    )
    db.insert_platform_snapshot(
        platform_post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=2, shares_count=1, raw={},
    )

    class MissingClient(FakeVkClient):
        def __init__(self):
            super().__init__(old_post)
            self.requested: list[str] = []

        async def wall(self, community_id: int, count: int = 100) -> list[VkPost]:
            return []

        async def posts(self, post_ids: list[str]) -> list[VkPost]:
            self.requested.extend(post_ids)
            return []

    client = MissingClient()
    collector = VkCollector(cfg, db, client)
    asyncio.run(collector.poll_cycle())
    pending = db.platform_post(platform_post_id)
    assert pending is not None
    assert pending["missing_check_count"] == 1
    assert pending["deleted_at"] is None

    asyncio.run(collector.poll_cycle())
    deleted = db.platform_post(platform_post_id)
    assert deleted is not None
    assert deleted["missing_check_count"] == 2
    assert deleted["deleted_at"] is not None

    asyncio.run(collector.poll_cycle())
    assert client.requested == ["-42_7", "-42_7"]


def test_vk_collector_does_not_mark_missing_when_point_lookup_fails(tmp_path):
    cfg = replace(_settings(tmp_path), discovery_limit=1)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(institution_id, "vk", "university")
    published = datetime.now(timezone.utc) - timedelta(days=2)
    old_post = VkPost(-42, 7, published, "text", 120, 8, 3, 2, {"id": 7})
    post_id = db.upsert_platform_post(
        account_id, "-42_7", published, published, "text", None, {},
    )
    db.insert_platform_snapshot(
        post_id, published + timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=5, comments_count=2, shares_count=1, raw={},
    )

    class ErrorClient(FakeVkClient):
        async def wall(self, community_id: int, count: int = 100) -> list[VkPost]:
            return []

        async def posts(self, post_ids: list[str]) -> list[VkPost]:
            raise RuntimeError("VK temporarily unavailable")

    asyncio.run(VkCollector(cfg, db, ErrorClient(old_post)).poll_cycle())

    stored = db.platform_post(post_id)
    assert stored is not None
    assert stored["missing_check_count"] == 0
    assert stored["deleted_at"] is None


def test_vk_collector_stores_joint_post_under_community_number(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    db.add_platform_account(institution_id, "vk", "university")
    post = VkPost(
        owner_id=-900,
        post_id=12,
        published_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        post_type="photo",
        views=100,
        likes=5,
        comments=2,
        reposts=1,
        raw={
            "owner_id": -900,
            "id": 12,
            "coowners": {
                "coowner_post_id": {"owner_id": -42, "post_id": 77},
                "list": [{"owner_id": -900}, {"owner_id": -42}],
            },
        },
    )
    asyncio.run(VkCollector(cfg, db, FakeVkClient(post)).poll_cycle())

    stored = db.query("SELECT * FROM platform_posts")[0]
    assert stored["external_id"] == "-42_77"
    assert stored["source_external_id"] == "-900_12"
    assert stored["url"] == "https://vk.ru/wall-900_12"
    assert stored["is_joint"] == 1
    assert stored["additional_author_count"] == 1
    assert stored["history_complete"] == 1


def test_vk_collector_suppresses_transient_zero_counters(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("University", "UNI")
    account_id = db.add_platform_account(institution_id, "vk", "university")
    published = datetime.now(timezone.utc) - timedelta(hours=1)
    post_id = db.upsert_platform_post(
        account_id, "-42_7", published, published, "text", None, {},
    )
    db.insert_platform_snapshot(
        post_id, published + timedelta(minutes=5), 300, 5,
        views_count=100, reactions_count=5, comments_count=2, shares_count=1,
        raw={},
    )
    reset = VkPost(-42, 7, published, "text", 120, 0, 0, 0, {
        "owner_id": -42, "id": 7,
    })

    asyncio.run(VkCollector(cfg, db, FakeVkClient(reset)).poll_cycle())

    snapshot = db.platform_snapshots(post_id)[-1]
    assert snapshot["views_count"] == 120
    assert snapshot["reactions_count"] is None
    assert snapshot["comments_count"] is None
    assert snapshot["shares_count"] is None
    assert "ignored_transient_zero_metrics" in snapshot["raw_json"]
