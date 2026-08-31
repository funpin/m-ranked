import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.database import Database

from app.public_web import (
    parse_compact_count,
    parse_exact_subscriber_count,
    parse_public_channel,
    parse_public_page,
    public_post_is_deleted,
    PublicWebCollector,
    snapshot_interval_minutes,
    snapshot_is_due,
)


def test_compact_public_counts():
    assert parse_compact_count("57") == 57
    assert parse_compact_count("1.2K") == 1200
    assert parse_compact_count("5.46K") == 5460


def test_public_page_reactions_paid_custom_and_album():
    html = """
    <div class="tgme_widget_message" data-post="example/42">
      <a class="tgme_widget_message_photo_wrap"></a>
      <a class="tgme_widget_message_photo_wrap"></a>
      <div class="tgme_widget_message_reactions">
        <span class="tgme_reaction tgme_reaction_paid"><i></i>3</span>
        <span class="tgme_reaction"><tg-emoji emoji-id="123"></tg-emoji>57</span>
      </div>
      <span class="tgme_widget_message_views">3.53K</span>
      <time datetime="2026-08-28T08:00:00+00:00"></time>
    </div>
    """
    posts = parse_public_page(html, "example")
    assert len(posts) == 1
    assert posts[0].message_id == 42
    assert posts[0].post_type == "album"
    assert posts[0].reactions.reactions == {"paid:star": 3, "custom:123": 57}
    assert posts[0].reactions.total == 60
    assert posts[0].views_count == 3530


def test_public_page_reaction_markup_variants():
    html = """
    <div class="tgme_widget_message" data-post="example/77">
      <div class="tgme_widget_message_reactions">
        <span class="tgme_reaction"><tg-emoji data-emoji-id="456"></tg-emoji>2</span>
        <span class="tgme_reaction"><img alt="🔥">3</span>
        <span class="tgme_reaction">👍 4</span>
      </div>
      <time datetime="2026-08-28T08:00:00+00:00"></time>
    </div>
    """
    post = parse_public_page(html, "example")[0]
    assert post.reactions.reactions == {"custom:456": 2, "🔥": 3, "👍": 4}


def test_public_channel_metadata():
    html = """
    <div class="tgme_channel_info_header_title">Example University</div>
    <div class="tgme_channel_info_counter"><span class="counter_value">11.4K</span><span class="counter_type">subscribers</span></div>
    """
    channel = parse_public_channel(html, "example")
    assert channel.title == "Example University"
    assert channel.subscribers == 11_400
    assert channel.subscribers_display == "11.4K"


def test_exact_subscriber_count_from_public_landing_page():
    html = '<div class="tgme_page_extra">25 015 subscribers</div>'
    assert parse_exact_subscriber_count(html) == 25_015


def test_public_post_deleted_marker():
    html = '<div class="tgme_widget_message_error">Post not found</div>'
    assert public_post_is_deleted(html) is True


def test_snapshot_due_tolerates_small_scheduler_jitter():
    previous = datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)
    assert snapshot_is_due(previous.isoformat(), previous + timedelta(minutes=4, seconds=31), 5)
    assert not snapshot_is_due(
        previous.isoformat(), previous + timedelta(minutes=4, seconds=29), 5,
    )


def test_public_collector_marks_explicitly_missing_post_deleted(tmp_path):
    now = datetime.now(timezone.utc)
    settings = SimpleNamespace(
        subscriber_refresh_hours=24,
        track_post_for_hours=960,
        poll_interval_minutes=5,
        second_day_poll_interval_minutes=15,
        third_day_poll_interval_minutes=15,
        days_4_to_6_poll_interval_minutes=30,
        days_7_to_13_poll_interval_minutes=60,
        day_14_plus_poll_interval_minutes=60,
        rutube_first_three_days_poll_interval_minutes=60,
        rutube_days_4_to_6_poll_interval_minutes=180,
        rutube_days_7_to_13_poll_interval_minutes=360,
        rutube_day_14_plus_poll_interval_minutes=720,
        complete_history_max_first_age_minutes=6,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        deletion_confirmation_checks=2,
    )
    db = Database(tmp_path / "public.db")
    db.migrate()
    channel_id = db.add_channel("example")
    deleted_post_id = db.add_post(
        channel_id, "m:42", [42], None, now - timedelta(hours=1),
        now - timedelta(hours=1), 0, True, "text", False,
    )
    db.insert_snapshot(
        deleted_post_id, now - timedelta(minutes=10), 3000, 5, {"👍": 5},
        [], 5, 15, 2.0, views_count=100,
    )
    feed_html = f"""
    <div class="tgme_channel_info_header_title">Example</div>
    <div class="tgme_widget_message" data-post="example/43">
      <time datetime="{(now - timedelta(minutes=2)).isoformat()}"></time>
      <span class="tgme_widget_message_views">10</span>
    </div>
    """

    async def fake_fetch(url):
        if url.endswith("/s/example"):
            return feed_html
        if url.endswith("/example"):
            return '<div class="tgme_page_extra">100 subscribers</div>'
        if "/42?" in url:
            return '<div class="tgme_widget_message_error">Post not found</div>'
        raise AssertionError(url)

    collector = PublicWebCollector(settings, db)
    collector._fetch = fake_fetch
    try:
        asyncio.run(collector._poll_channel(db.channel(channel_id)))
    finally:
        asyncio.run(collector.close())

    pending = db.query(
        "SELECT deleted_at, missing_check_count, missing_reason FROM posts WHERE id=?",
        (deleted_post_id,),
    )[0]
    assert pending["deleted_at"] is None
    assert pending["missing_check_count"] == 1
    assert pending["missing_reason"] == "telegram_embed_post_not_found"

    collector = PublicWebCollector(settings, db)
    collector._fetch = fake_fetch
    try:
        asyncio.run(collector._poll_channel(db.channel(channel_id)))
    finally:
        asyncio.run(collector.close())

    deleted = db.query(
        "SELECT deleted_at, missing_check_count FROM posts WHERE id=?", (deleted_post_id,)
    )[0]
    assert deleted["deleted_at"] is not None
    assert deleted["missing_check_count"] == 2
    assert all(post["id"] != deleted_post_id for post in db.active_posts(
        channel_id, (now - timedelta(days=40)).isoformat(),
    ))


def test_available_post_clears_pending_deletion_confirmation(tmp_path):
    now = datetime.now(timezone.utc)
    db = Database(tmp_path / "recovered.db")
    db.migrate()
    channel_id = db.add_channel("recovered")
    post_id = db.add_post(
        channel_id, "m:51", [51], None, now, now, 0, True, "text", False,
    )
    count, confirmed = db.record_post_missing(
        post_id, now, "temporary_404", confirmation_checks=2,
    )
    assert (count, confirmed) == (1, False)
    db.mark_post_available(post_id)
    row = db.query(
        "SELECT deleted_at, missing_check_count, missing_reason FROM posts WHERE id=?",
        (post_id,),
    )[0]
    assert row["deleted_at"] is None
    assert row["missing_check_count"] == 0
    assert row["missing_reason"] is None


def test_age_based_snapshot_intervals():
    settings = SimpleNamespace(
        poll_interval_minutes=5,
        second_day_poll_interval_minutes=15,
        third_day_poll_interval_minutes=15,
        days_4_to_6_poll_interval_minutes=30,
        days_7_to_13_poll_interval_minutes=60,
        day_14_plus_poll_interval_minutes=60,
        rutube_first_three_days_poll_interval_minutes=60,
        rutube_days_4_to_6_poll_interval_minutes=180,
        rutube_days_7_to_13_poll_interval_minutes=360,
        rutube_day_14_plus_poll_interval_minutes=720,
    )
    cases = {
        0: 5,
        24 * 3600 - 1: 5,
        24 * 3600: 15,
        48 * 3600: 15,
        72 * 3600: 30,
        7 * 24 * 3600: 60,
        14 * 24 * 3600: 60,
    }
    for age, expected in cases.items():
        assert snapshot_interval_minutes(age, settings) == expected

    rutube_cases = {
        0: 60,
        24 * 3600 - 1: 60,
        24 * 3600: 60,
        48 * 3600: 60,
        72 * 3600 - 1: 60,
        72 * 3600: 180,
        7 * 24 * 3600: 360,
        14 * 24 * 3600: 720,
    }
    for age, expected in rutube_cases.items():
        assert snapshot_interval_minutes(age, settings, platform="rutube") == expected
