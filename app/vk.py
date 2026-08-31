from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class VkCommunity:
    id: int
    screen_name: str
    name: str
    members_count: int | None


@dataclass(frozen=True)
class VkPost:
    owner_id: int
    post_id: int
    published_at: datetime
    post_type: str
    views: int | None
    likes: int | None
    comments: int | None
    reposts: int | None
    raw: dict[str, Any]

    @property
    def external_key(self) -> str:
        return f"{self.owner_id}_{self.post_id}"


def normalize_vk_community_ref(value: str) -> str:
    value = value.strip().rstrip("/")
    value = re.sub(r"^https?://(?:m\.)?vk\.(?:com|ru)/", "", value, flags=re.I)
    value = value.split("?", 1)[0].split("/", 1)[0].lstrip("@")
    if not re.fullmatch(r"(?:club|public)?[A-Za-zА-Яа-яЁё0-9_.-]{2,64}", value):
        raise ValueError("Invalid VK community reference")
    return value


def _count(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, dict):
        value = value.get("count")
    return int(value) if value is not None else None


def parse_vk_post(payload: dict[str, Any]) -> VkPost:
    attachments = payload.get("attachments") or []
    types = [str(item.get("type", "")) for item in attachments if isinstance(item, dict)]
    if len(types) > 1:
        post_type = "album"
    elif types:
        post_type = types[0]
    else:
        post_type = "text"
    published = datetime.fromtimestamp(int(payload["date"]), tz=timezone.utc)
    return VkPost(
        owner_id=int(payload["owner_id"]),
        post_id=int(payload["id"]),
        published_at=published,
        post_type=post_type,
        views=_count(payload, "views"),
        likes=_count(payload, "likes"),
        comments=_count(payload, "comments"),
        reposts=_count(payload, "reposts"),
        raw=payload,
    )


class VkApiError(RuntimeError):
    pass


class VkClient:
    """Small read-only VK API client used by the future VK collector."""

    def __init__(
        self,
        access_token: str,
        api_version: str = "5.199",
        client: httpx.AsyncClient | None = None,
    ):
        if not access_token:
            raise ValueError("VK access token is required")
        self.access_token = access_token
        self.api_version = api_version
        self.client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _call(self, method: str, **params: Any) -> Any:
        response = await self.client.post(
            f"https://api.vk.com/method/{method}",
            data={**params, "access_token": self.access_token, "v": self.api_version},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            error = payload["error"]
            raise VkApiError(
                f"VK API {error.get('error_code', '?')}: {error.get('error_msg', 'unknown error')}"
            )
        return payload.get("response")

    async def community(self, reference: str) -> VkCommunity:
        ref = normalize_vk_community_ref(reference)
        response = await self._call("groups.getById", group_ids=ref, fields="members_count")
        groups = response.get("groups", []) if isinstance(response, dict) else response
        if not groups:
            raise VkApiError(f"VK community not found: {ref}")
        group = groups[0]
        return VkCommunity(
            id=int(group["id"]),
            screen_name=str(group.get("screen_name") or ref),
            name=str(group.get("name") or ref),
            members_count=(
                int(group["members_count"]) if group.get("members_count") is not None else None
            ),
        )

    async def wall(self, community_id: int, count: int = 100) -> list[VkPost]:
        response = await self._call(
            "wall.get", owner_id=-abs(int(community_id)), count=max(1, min(count, 100)),
            filter="owner",
        )
        items = response.get("items", []) if isinstance(response, dict) else []
        return [parse_vk_post(item) for item in items if not item.get("is_pinned")]

    async def posts(self, post_ids: list[str]) -> list[VkPost]:
        """Refresh exact counters for already known posts outside wall.get's first page."""
        if not post_ids:
            return []
        response = await self._call("wall.getById", posts=",".join(post_ids[:100]))
        items = response.get("items", []) if isinstance(response, dict) else response or []
        return [parse_vk_post(item) for item in items]
