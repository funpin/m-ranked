from datetime import datetime, timezone
from types import SimpleNamespace

from app.collector import group_logical_posts, normalize_channel_ref


def message(mid, grouped_id=None, action=None):
    return SimpleNamespace(
        id=mid,
        grouped_id=grouped_id,
        date=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        action=action,
        media=None,
        reactions=None,
    )


def test_album_grouping_and_service_message_exclusion():
    posts = group_logical_posts([message(10, 777), message(11, 777), message(12), message(13, action=object())])
    assert len(posts) == 2
    album = next(post for post in posts if post.grouped_id == 777)
    assert album.message_ids == (10, 11)
    assert album.post_type == "album"


def test_channel_reference_normalization():
    assert normalize_channel_ref("https://t.me/example/") == "example"
    assert normalize_channel_ref("@example") == "example"
    assert normalize_channel_ref("https://t.me/s/naukamsu") == "naukamsu"
    assert normalize_channel_ref("t.me/s/naukamsu/") == "naukamsu"
