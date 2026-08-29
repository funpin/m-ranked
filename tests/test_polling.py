import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.collector import Collector, logical_comments, logical_views
from app.config import Settings
from app.database import Database


class FakeClient:
    def __init__(self, message):
        self.message = message

    async def get_entity(self, username):
        return SimpleNamespace(id=99, broadcast=True, title="Example", username=username)

    async def iter_messages(self, entity, limit, min_id):
        yield self.message

    async def get_messages(self, entity, ids):
        return [self.message for _ in ids]


def test_mocked_telegram_poll_writes_snapshot_without_duplicates(tmp_path):
    message = SimpleNamespace(
        id=123,
        grouped_id=None,
        date=datetime.now(timezone.utc),
        action=None,
        media=None,
        reactions=SimpleNamespace(results=[]),
        views=321,
        replies=SimpleNamespace(replies=7),
    )
    settings = Settings(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_session_path=tmp_path / "session",
        database_path=tmp_path / "db.sqlite",
        initial_channels=(),
        poll_interval_minutes=60,
        track_post_for_hours=336,
        complete_history_max_first_age_minutes=90,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        web_host="127.0.0.1",
        web_port=8080,
        display_timezone="UTC",
        log_path=tmp_path / "app.log",
        discovery_limit=200,
        discovery_overlap=20,
    )
    db = Database(settings.database_path)
    db.migrate()
    db.add_channel("example")
    collector = Collector(settings, db, SimpleNamespace(client=FakeClient(message)))

    asyncio.run(collector.poll_cycle())
    asyncio.run(collector.poll_cycle())

    assert len(db.query("SELECT * FROM posts")) == 1
    assert len(db.query("SELECT * FROM reaction_snapshots")) == 1
    snapshot = db.query("SELECT * FROM reaction_snapshots")[0]
    assert snapshot["total_reactions"] == 0
    assert snapshot["views_count"] == 321
    assert snapshot["comments_count"] == 7
    assert db.get_state("poll_last_duration_seconds") is not None
    assert db.get_state("poll_last_error_count") == "0"
    assert db.get_state("poll_last_channel_count") == "1"


def test_album_metrics_are_not_multiplied():
    messages = [
        SimpleNamespace(views=100, replies=SimpleNamespace(replies=3)),
        SimpleNamespace(views=100, replies=SimpleNamespace(replies=3)),
        SimpleNamespace(views=99, replies=None),
    ]
    assert logical_views(messages) == 100
    assert logical_comments(messages) == 3
