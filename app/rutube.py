from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class RutubeChannel:
    id: int
    name: str
    url: str


@dataclass(frozen=True)
class RutubeVideo:
    id: str
    title: str
    published_at: datetime
    views: int | None
    url: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class RutubeVideoMetrics:
    likes: int | None
    comments: int | None
    raw: dict[str, Any]


def parse_rutube_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class RutubeClient:
    """Read the official public RUTUBE APIs; they do not require a token."""

    def __init__(
        self,
        api_base: str = "https://rutube.ru/api",
        client: httpx.AsyncClient | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def resolve_channel(self, reference: str, url: str | None = None) -> int:
        numeric = re.search(r"(?:channel|video/person)/(\d+)", url or "")
        if numeric:
            return int(numeric.group(1))
        if reference.isdigit():
            return int(reference)
        if not url:
            raise ValueError("RUTUBE channel URL is required for a slug")
        response = await self.client.get(url)
        response.raise_for_status()
        match = re.search(r"video/person/(\d+)", response.text)
        if not match:
            raise ValueError(f"RUTUBE channel id was not found at {url}")
        return int(match.group(1))

    async def videos(self, channel_id: int, limit: int = 100) -> tuple[RutubeChannel, list[RutubeVideo]]:
        result: list[RutubeVideo] = []
        page = 1
        channel_name = str(channel_id)
        while len(result) < max(1, limit):
            response = await self.client.get(
                f"{self.api_base}/video/person/{channel_id}/",
                params={"page": page, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("results") or []
            for item in items:
                author = item.get("author") or {}
                channel_name = str(author.get("name") or channel_name)
                published = item.get("publication_ts") or item.get("created_ts")
                if not published or not item.get("id"):
                    continue
                result.append(RutubeVideo(
                    id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    published_at=parse_rutube_datetime(str(published)),
                    views=int(item["hits"]) if item.get("hits") is not None else None,
                    url=str(item.get("video_url") or f"https://rutube.ru/video/{item['id']}/"),
                    raw=item,
                ))
                if len(result) >= limit:
                    break
            if not payload.get("has_next") or not items:
                break
            page += 1
        return (
            RutubeChannel(
                channel_id, channel_name,
                f"https://rutube.ru/video/person/{channel_id}/",
            ),
            result,
        )

    async def video_metrics(self, video_id: str) -> RutubeVideoMetrics:
        vote_response, comments_response = await asyncio.gather(
            self.client.get(f"{self.api_base}/numerator/video/{video_id}/vote"),
            self.client.get(
                f"{self.api_base}/v2/comments/video/{video_id}/",
                params={"client": "wdp", "sort_by": "date_added_desc"},
            ),
            return_exceptions=True,
        )

        vote: dict[str, Any] | None = None
        comments: dict[str, Any] | None = None
        if isinstance(vote_response, httpx.Response) and vote_response.is_success:
            try:
                payload = vote_response.json()
                vote = payload if isinstance(payload, dict) else None
            except ValueError:
                vote = None
        if isinstance(comments_response, httpx.Response) and comments_response.is_success:
            try:
                payload = comments_response.json()
                comments = payload if isinstance(payload, dict) else None
            except ValueError:
                comments = None
        return RutubeVideoMetrics(
            likes=(
                int(vote["positive"])
                if vote is not None and vote.get("positive") is not None else None
            ),
            comments=(
                int(comments["comments_count"])
                if comments is not None and comments.get("comments_count") is not None
                else None
            ),
            raw={"vote": vote, "comments": comments},
        )
