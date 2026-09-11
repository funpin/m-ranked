from datetime import datetime, timedelta, timezone

from collector_runtime.public_web import (
    parse_compact_count,
    parse_exact_subscriber_count,
    parse_public_channel,
    parse_public_page,
    public_post_is_deleted,
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


def test_public_page_marks_forward_from_another_channel_as_repost():
    html = """
    <div class="tgme_widget_message" data-post="example/78">
      <div class="tgme_widget_message_forwarded_from">
        <a class="tgme_widget_message_forwarded_from_name"
           href="https://t.me/source_channel">Source</a>
      </div>
      <time datetime="2026-08-28T08:00:00+00:00"></time>
    </div>
    """

    assert parse_public_page(html, "example")[0].is_repost


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


def test_public_service_message_placeholder_is_unavailable():
    html = """
    <div class="tgme_widget_message text_not_supported_wrap" data-post="example/42">
      <div class="message_media_not_supported_wrap">
        <div class="message_media_not_supported_label">Service message</div>
      </div>
      <time datetime="2026-09-01T06:45:29+00:00"></time>
    </div>
    """

    assert parse_public_page(html, "example") == []
    assert public_post_is_deleted(html) is True


def test_public_feed_service_message_without_label_is_unavailable():
    html = """
    <div class="tgme_widget_message text_not_supported_wrap service_message"
         data-post="example/43">
      <time datetime="2026-09-01T06:50:29+00:00"></time>
    </div>
    """

    assert parse_public_page(html, "example") == []
    assert public_post_is_deleted(html) is True


def test_snapshot_due_uses_stable_wall_clock_slots():
    previous = datetime(2026, 8, 31, 13, 5, 49, tzinfo=timezone.utc)

    assert snapshot_is_due(
        previous.isoformat(),
        datetime(2026, 8, 31, 13, 10, 15, tzinfo=timezone.utc),
        5,
    )
    assert not snapshot_is_due(
        previous.isoformat(),
        datetime(2026, 8, 31, 13, 9, 59, tzinfo=timezone.utc),
        5,
    )


def test_snapshot_due_respects_longer_interval_slots():
    previous = datetime(2026, 8, 31, 13, 5, tzinfo=timezone.utc)

    assert not snapshot_is_due(
        previous.isoformat(),
        datetime(2026, 8, 31, 13, 14, 59, tzinfo=timezone.utc),
        15,
    )
    assert snapshot_is_due(
        previous.isoformat(),
        datetime(2026, 8, 31, 13, 15, tzinfo=timezone.utc),
        15,
    )


def test_snapshot_due_keeps_cycle_slot_when_processing_crossed_boundary():
    scheduled_previous = datetime(2026, 8, 31, 13, 5, tzinfo=timezone.utc)
    measured_previous = datetime(2026, 8, 31, 13, 10, 2, tzinfo=timezone.utc)
    previous_bucket = int(scheduled_previous.timestamp()) // (5 * 60)

    assert snapshot_is_due(
        measured_previous.isoformat(),
        datetime(2026, 8, 31, 13, 10, 15, tzinfo=timezone.utc),
        5,
        last_measurement_bucket=previous_bucket,
    )


def test_snapshot_due_ignores_stored_bucket_from_previous_interval_scale():
    previous = datetime(2026, 8, 31, 13, 10, tzinfo=timezone.utc)
    five_minute_bucket = int(previous.timestamp()) // (5 * 60)

    assert snapshot_is_due(
        previous.isoformat(),
        datetime(2026, 8, 31, 13, 15, tzinfo=timezone.utc),
        15,
        last_measurement_bucket=five_minute_bucket,
    )
