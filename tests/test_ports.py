import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.clock import CallableUtcClock, FrozenUtcClock, SystemUtcClock, UtcClock
from app.collector import Collector
from app.config import Settings
from app.database import Database
from app.platform_analytics import LegacyAnalyticsQueryService
from app.ports import (
    AnalyticsQueryService,
    AnalyticsReadRepository,
    CollectorAdapter,
    ObservationRepository,
    ObservationTransaction,
    PlatformObservationRepository,
    TelegramObservationRepository,
    TransactionBoundary,
)
from app.web.app import create_app


def _settings(tmp_path) -> Settings:
    return Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=tmp_path / "telegram.session",
        database_path=tmp_path / "observations.sqlite",
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
        archive_dir=tmp_path / "archives",
        vk_access_token="test-token",
    )


def test_utc_clock_ports_are_aware_and_deterministic():
    instant = datetime(2026, 9, 3, 12, 34, 56)
    frozen = FrozenUtcClock(instant)
    callback = CallableUtcClock(lambda: instant)

    assert isinstance(frozen, UtcClock)
    assert frozen.now() == datetime(2026, 9, 3, 12, 34, 56, tzinfo=timezone.utc)
    assert callback.now() == frozen.now()

    before = datetime.now(timezone.utc)
    current = SystemUtcClock().now()
    after = datetime.now(timezone.utc)
    assert before <= current <= after
    assert current.tzinfo is timezone.utc


def test_database_implements_split_repository_and_transaction_ports(tmp_path):
    db = Database(tmp_path / "ports.sqlite")
    db.migrate()

    assert isinstance(db, ObservationRepository)
    assert isinstance(db, TelegramObservationRepository)
    assert isinstance(db, PlatformObservationRepository)
    assert isinstance(db, AnalyticsReadRepository)

    boundary = db.transaction()
    assert isinstance(boundary, TransactionBoundary)
    with boundary as transaction:
        assert isinstance(transaction, ObservationTransaction)


def test_transaction_adapter_commits_and_rolls_back_as_one_boundary(tmp_path):
    db = Database(tmp_path / "transaction.sqlite")
    db.migrate()
    channel_id = db.add_channel("portstest")
    published = datetime(2026, 9, 3, 10, tzinfo=timezone.utc)

    with db.transaction() as transaction:
        post_id = transaction.add_post(
            channel_id,
            "m:1",
            [1],
            None,
            published,
            published,
            0,
            True,
            "text",
            False,
        )
        assert transaction.insert_snapshot(
            post_id,
            published,
            0,
            7,
            {"👍": 7},
            [],
            5,
            15,
            2.0,
            views_count=70,
        )
        assert transaction.latest_snapshot_delta(post_id) is not None

    assert len(db.query("SELECT * FROM posts WHERE id=?", (post_id,))) == 1
    assert len(db.query("SELECT * FROM reaction_snapshots WHERE post_id=?", (post_id,))) == 1

    try:
        with db.transaction() as transaction:
            transaction.add_post(
                channel_id,
                "m:2",
                [2],
                None,
                published,
                published,
                0,
                True,
                "text",
                False,
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    assert db.query("SELECT id FROM posts WHERE logical_key='m:2'") == []


def test_collector_uses_injected_clock_for_cycle_state(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    instant = datetime(2026, 9, 3, 7, 15, tzinfo=timezone.utc)
    collector = Collector(
        cfg,
        db,
        SimpleNamespace(client=object()),
        clock=FrozenUtcClock(instant),
    )

    assert isinstance(collector, CollectorAdapter)
    asyncio.run(collector.poll_cycle())

    assert db.get_state("poll_last_started_at") == instant.isoformat()
    assert db.get_state("poll_last_completed_at") == instant.isoformat()
    assert db.get_state("poll_last_duration_seconds") == "0.000"
    assert db.get_state("next_poll") == (instant + timedelta(minutes=5)).isoformat()


def test_web_uses_injected_analytics_service_and_request_clock(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    instant = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)

    class RecordingAnalytics:
        def __init__(self):
            self.rating_calls = []
            self.activity_calls = []

        def rating_data(self, platform, cutoff):
            self.rating_calls.append((platform, cutoff))
            return [], []

        def activity_cards(self, platform, start, previous_start, end=None):
            self.activity_calls.append((platform, start, previous_start, end))
            return []

    analytics = RecordingAnalytics()
    assert isinstance(analytics, AnalyticsQueryService)
    client = TestClient(create_app(
        cfg,
        db,
        clock=FrozenUtcClock(instant),
        analytics_queries=analytics,
    ))

    assert client.get("/?platform=vk&period=1d").status_code == 200
    assert analytics.activity_calls == [(
        "vk", instant - timedelta(days=1), instant - timedelta(days=2), instant,
    )]

    assert client.get("/rating?platform=vk&period=30d").status_code == 200
    assert analytics.rating_calls == [("vk", instant - timedelta(days=30))]


def test_default_analytics_adapter_satisfies_service_port(tmp_path):
    cfg = _settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    service = LegacyAnalyticsQueryService(
        db,
        cfg,
        FrozenUtcClock(datetime(2026, 9, 3, tzinfo=timezone.utc)),
    )

    assert isinstance(service, AnalyticsQueryService)
    assert service.rating_data("vk", datetime(2026, 9, 1, tzinfo=timezone.utc)) == ([], [])
    assert service.activity_cards(
        "vk",
        datetime(2026, 9, 2, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    ) == []
