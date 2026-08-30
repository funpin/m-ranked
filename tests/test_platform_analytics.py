from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.database import Database
from app.platform_analytics import platform_activity_cards


def settings(tmp_path) -> Settings:
    return Settings(
        telegram_api_id=None, telegram_api_hash=None,
        telegram_session_path=tmp_path / "session", database_path=tmp_path / "db.sqlite",
        initial_channels=(), poll_interval_minutes=5, track_post_for_hours=960,
        complete_history_max_first_age_minutes=6, jump_min_abs=15, jump_min_ratio=2.0,
        web_host="127.0.0.1", web_port=8080, display_timezone="Europe/Moscow",
        log_path=tmp_path / "app.log", discovery_limit=100, discovery_overlap=20,
        vk_access_token="token",
    )


def test_platform_card_uses_window_deltas_and_keeps_exact_post_count(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution = db.add_institution("Вуз", "ВУЗ")
    account = db.add_platform_account(institution, "vk", "vuz")
    end = datetime.now(timezone.utc).replace(microsecond=0)
    published = end - timedelta(hours=2)
    post = db.upsert_platform_post(account, "-1_1", published, published, "text", None, {})
    db.insert_platform_snapshot(
        post, end - timedelta(minutes=90), 1800, 5,
        views_count=100, reactions_count=10, comments_count=1, shares_count=0, raw={},
    )
    db.insert_platform_snapshot(
        post, end - timedelta(minutes=10), 6600, 5,
        views_count=140, reactions_count=16, comments_count=3, shares_count=1, raw={},
    )

    card = platform_activity_cards(
        db, cfg, "vk", end - timedelta(hours=3), end - timedelta(hours=6), end,
    )[0]

    assert card["activity_post_count"] == 1
    assert card["post_count"] == 1
    assert card["total_views"] == 40
    assert card["total_reactions"] == 6
    assert card["total_comments"] == 2
    assert card["total_shares"] == 1
