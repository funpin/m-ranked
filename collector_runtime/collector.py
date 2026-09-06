from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import LogicalPost
from .reactions import choose_album_reactions, parse_message_reactions
from .telegram_identity import telegram_publication_external_id


def normalize_channel_ref(value: str) -> str:
    value = value.strip().rstrip("/")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    parts = [part for part in value.lstrip("@").split("/") if part]
    # Telegram's public-preview URLs use /s/<username>.  The /s/ segment is
    # not a channel name and must never be saved as one.
    if parts and parts[0].lower() == "s":
        parts.pop(0)
    value = parts[0] if parts else ""
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        raise ValueError("Invalid Telegram channel username")
    return value


def post_type(message: Any) -> str:
    media = getattr(message, "media", None)
    if media is None:
        return "text"
    name = media.__class__.__name__.lower()
    for kind in ("photo", "document", "poll", "webpage", "contact", "geo"):
        if kind in name:
            return kind
    return name.removeprefix("messagemedia").lower() or "media"


def is_published_post(message: Any) -> bool:
    return bool(
        message
        and getattr(message, "id", None)
        and getattr(message, "date", None)
        and getattr(message, "action", None) is None
    )


def logical_views(messages: Iterable[Any]) -> int | None:
    """Return the visible view counter for a Telegram post or album.

    Telegram may repeat the same counter on album elements.  Taking the
    maximum avoids multiplying one logical post's audience by its item count.
    """
    values = [int(value) for message in messages if (value := getattr(message, "views", None)) is not None]
    return max(values) if values else None


def logical_comments(messages: Iterable[Any]) -> int | None:
    """Return the reply/comment counter for a Telegram post or album."""
    values: list[int] = []
    for message in messages:
        replies = getattr(message, "replies", None)
        value = getattr(replies, "replies", None) if replies is not None else None
        if value is not None:
            values.append(int(value))
    return max(values) if values else None


def is_channel_repost(message: Any) -> bool:
    """Return whether a Telegram message was forwarded from another channel."""
    forwarded = getattr(message, "fwd_from", None)
    source = getattr(forwarded, "from_id", None) if forwarded is not None else None
    source_channel_id = getattr(source, "channel_id", None)
    if source_channel_id is None:
        return False
    destination = getattr(message, "peer_id", None)
    destination_channel_id = getattr(destination, "channel_id", None)
    return (
        destination_channel_id is None
        or int(source_channel_id) != int(destination_channel_id)
    )


def group_logical_posts(messages: Iterable[Any]) -> list[LogicalPost]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for message in messages:
        if not is_published_post(message):
            continue
        grouped_id = getattr(message, "grouped_id", None)
        key = telegram_publication_external_id(message.id, grouped_id)
        groups[key].append(message)

    logical: list[LogicalPost] = []
    for group in groups.values():
        group.sort(key=lambda item: item.id)
        grouped_id = getattr(group[0], "grouped_id", None)
        if grouped_id is not None:
            state, ambiguous = choose_album_reactions(group)
            kind = "album"
        else:
            state = parse_message_reactions(group[0])
            ambiguous = False
            kind = post_type(group[0])
        published_at = min(message.date for message in group)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        logical.append(
            LogicalPost(
                tuple(message.id for message in group), grouped_id, published_at,
                kind, state, ambiguous, any(is_channel_repost(message) for message in group),
            )
        )
    return sorted(logical, key=lambda item: item.published_at)
