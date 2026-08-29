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


def test_public_collector_marks_explicitly_missing_post_deleted(tmp_path):
    now = datetime.now(timezone.utc)
    settings = SimpleNamespace(
        subscriber_refresh_hours=24,
        track_post_for_hours=960,
        poll_interval_minutes=5,
        second_day_poll_interval_minutes=15,
        third_day_poll_interval_minutes=60,
        days_4_to_6_poll_interval_minutes=180,
        days_7_to_13_poll_interval_minutes=360,
        day_14_plus_poll_interval_minutes=720,
        complete_history_max_first_age_minutes=6,
        jump_min_abs=15,
        jump_min_ratio=2.0,
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

    deleted = db.query("SELECT deleted_at FROM posts WHERE id=?", (deleted_post_id,))[0]
    assert deleted["deleted_at"] is not None
    assert all(post["id"] != deleted_post_id for post in db.active_posts(
        channel_id, (now - timedelta(days=40)).isoformat(),
    ))


def test_age_based_snapshot_intervals():
    settings = SimpleNamespace(
        poll_interval_minutes=5,
        second_day_poll_interval_minutes=15,
        third_day_poll_interval_minutes=60,
        days_4_to_6_poll_interval_minutes=180,
        days_7_to_13_poll_interval_minutes=360,
        day_14_plus_poll_interval_minutes=720,
    )
    cases = {
        0: 5,
        24 * 3600 - 1: 5,
        24 * 3600: 15,
        48 * 3600: 60,
        72 * 3600: 180,
        7 * 24 * 3600: 360,
        14 * 24 * 3600: 720,
    }
    for age, expected in cases.items():
        assert snapshot_interval_minutes(age, settings) == expected
