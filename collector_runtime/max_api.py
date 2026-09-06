from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class MaxChannel:
    id: int
    title: str
    participants_count: int | None
    link: str | None


@dataclass(frozen=True)
class MaxPost:
    id: str
    published_at: datetime
    views: int | None
    reactions: int | None
    reposts: int | None
    comments: int | None
    url: str | None
    raw: dict[str, Any]
    reaction_breakdown: dict[str, int] | None = None
    post_type: str = "post"
    is_repost: bool = False


def max_post_slug(message_id: str | int) -> str:
    """Encode MAX's unsigned 64-bit message id as its public URL slug."""
    value = int(message_id)
    if not 0 <= value < 2**64:
        raise ValueError("MAX message id must fit an unsigned 64-bit integer")
    return base64.urlsafe_b64encode(value.to_bytes(8, "big")).decode().rstrip("=")


def max_post_url(reference: str, message_id: str | int) -> str | None:
    """Build the canonical public URL for a MAX channel publication."""
    value = reference.strip()
    if not value:
        return None
    if "://" in value:
        parts = [part for part in urlparse(value).path.split("/") if part]
        username = parts[0].lstrip("@") if parts else ""
    else:
        username = value.lstrip("@/").split("/", 1)[0]
    if not username:
        return None
    return f"https://max.ru/{username}/{max_post_slug(message_id)}"


def max_post_is_repost(payload: dict[str, Any], chat_id: int) -> bool:
    """Return whether a MAX post is a forward from a different chat/channel."""
    link = payload.get("link")
    if not isinstance(link, dict) or str(link.get("type") or "").casefold() != "forward":
        return False
    source_chat_id = link.get("chat_id", link.get("chatId"))
    if source_chat_id is None:
        return True
    try:
        return int(source_chat_id) != int(chat_id)
    except (TypeError, ValueError):
        return True
