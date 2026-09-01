from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
