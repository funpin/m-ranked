from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


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
    reposts: int | None
    comments: int | None
    url: str | None
    raw: dict[str, Any]
    is_repost: bool = False


def _optional_count(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if payload.get(key) is not None:
            return int(payload[key])
    return None


def max_post_is_repost(payload: dict[str, Any], chat_id: int) -> bool:
    """Return whether a MAX post is a forward from a different chat/channel."""
    link = payload.get("link")
    if not isinstance(link, dict) or str(link.get("type") or "").casefold() != "forward":
        return False
    source_chat_id = link.get("chat_id")
    if source_chat_id is None:
        return True
    try:
        return int(source_chat_id) != int(chat_id)
    except (TypeError, ValueError):
        return True


class MaxClient:
    """Minimal read-only client for the official MAX Bot API."""

    def __init__(
        self, token: str, api_base: str = "https://platform-api2.max.ru",
        client: httpx.AsyncClient | None = None,
    ):
        if not token:
            raise ValueError("MAX_ACCESS_TOKEN is required")
        self.client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self.api_base = api_base.rstrip("/")
        self.headers = {"Authorization": token}

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(
            f"{self.api_base}{path}", params=params, headers=self.headers,
        )
        response.raise_for_status()
        return response.json()

    async def channel(self, chat_id: int) -> MaxChannel:
        payload = await self._get(f"/chats/{chat_id}")
        if payload.get("type") != "channel":
            raise ValueError(f"MAX chat {chat_id} is not a channel")
        return MaxChannel(
            int(payload["chat_id"]), str(payload.get("title") or chat_id),
            _optional_count(payload, "participants_count"), payload.get("link"),
        )

    async def posts(self, chat_id: int, count: int = 100) -> list[MaxPost]:
        payload = await self._get("/messages", chat_id=chat_id, count=min(100, max(1, count)))
        result: list[MaxPost] = []
        for item in payload.get("messages") or []:
            body = item.get("body") or {}
            post_id = item.get("message_id") or item.get("mid") or body.get("mid")
            timestamp = item.get("timestamp")
            if not post_id or timestamp is None:
                continue
            stat = item.get("stat") or {}
            result.append(MaxPost(
                id=str(post_id),
                published_at=datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc),
                views=_optional_count(stat, "views", "views_count", "view_count"),
                reposts=_optional_count(stat, "reposts", "reposts_count", "repost_count"),
                comments=_optional_count(
                    stat, "comments", "comments_count", "comment_count",
                ),
                url=item.get("url"), raw=item,
                is_repost=max_post_is_repost(item, chat_id),
            ))
        return result
