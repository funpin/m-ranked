from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.collector import group_logical_posts, is_channel_repost, normalize_channel_ref


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


def test_grouping_rejects_noncanonical_telegram_group_identity():
    with pytest.raises(ValueError, match="canonical positive integer"):
        group_logical_posts([message(10, 0)])


def test_channel_reference_normalization():
    assert normalize_channel_ref("https://t.me/example/") == "example"
    assert normalize_channel_ref("@example") == "example"
    assert normalize_channel_ref("https://t.me/s/naukamsu") == "naukamsu"
    assert normalize_channel_ref("t.me/s/naukamsu/") == "naukamsu"


def test_telegram_repost_requires_a_different_source_channel():
    forwarded = message(20)
    forwarded.fwd_from = SimpleNamespace(from_id=SimpleNamespace(channel_id=111))
    forwarded.peer_id = SimpleNamespace(channel_id=222)
    own_forward = message(21)
    own_forward.fwd_from = SimpleNamespace(from_id=SimpleNamespace(channel_id=222))
    own_forward.peer_id = SimpleNamespace(channel_id=222)
    forwarded_from_user = message(22)
    forwarded_from_user.fwd_from = SimpleNamespace(from_id=SimpleNamespace(user_id=333))

    assert is_channel_repost(forwarded)
    assert not is_channel_repost(own_forward)
    assert not is_channel_repost(forwarded_from_user)
    assert group_logical_posts([forwarded])[0].is_repost
