from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

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


CHANNEL_HOSTS = frozenset({"rutube.ru", "www.rutube.ru"})
CHANNEL_PATHS = (
    (re.compile(r"/video/person/(\d{1,20})/?"), "video/person"),
    (re.compile(r"/channel/([A-Za-z0-9_-]{1,64})/?"), "channel"),
    (re.compile(r"/u/([A-Za-z0-9_-]{1,64})/?"), "u"),
)
MAX_PAGE_REDIRECTS = 4


def channel_page_url(value: str | None) -> str | None:
    """Return the canonical RUTUBE channel page URL, or None when it is not one.

    Channel URLs arrive from the catalogue database, so this sink re-checks them
    instead of trusting the admin API: anything outside RUTUBE is refused rather
    than fetched, which keeps the collector from being used as an SSRF proxy.
    """
    if not value:
        return None
    try:
        parsed, port = urlsplit(value), urlsplit(value).port
    except ValueError:
        return None
    if (parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in CHANNEL_HOSTS
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.query or parsed.fragment):
        return None
    for pattern, prefix in CHANNEL_PATHS:
        match = pattern.fullmatch(parsed.path)
        if match:
            return f"https://rutube.ru/{prefix}/{match.group(1)}/"
    return None


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
        # Ни один запрос не следует redirect сам: и страница канала, и вызовы
        # API проверяют каждый переход по тому же списку хостов.
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
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
        page = channel_page_url(url)
        if page is None:
            raise ValueError("RUTUBE channel URL is required for a slug")
        response = await self._channel_page(page)
        response.raise_for_status()
        match = re.search(r"video/person/(\d+)", response.text)
        if not match:
            raise ValueError(f"RUTUBE channel id was not found at {url}")
        return int(match.group(1))

    async def subscriber_count(self, channel_id: int, url: str | None = None) -> int | None:
        """Read the public subscriber counter embedded in the channel page."""
        page = channel_page_url(url) or f"https://rutube.ru/channel/{channel_id}/"
        try:
            response = await self._channel_page(page)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            return None
        match = re.search(r'"subscribers_count"\s*:\s*(\d+)', response.text)
        return int(match.group(1)) if match else None

    async def _channel_page(self, url: str) -> httpx.Response:
        """GET a channel page, re-checking every redirect hop against RUTUBE."""
        for _ in range(MAX_PAGE_REDIRECTS):
            response = await self.client.get(url, follow_redirects=False)
            if not response.is_redirect:
                return response
            target = response.headers.get("location")
            location = channel_page_url(urljoin(url, target)) if target else None
            if location is None:
                raise ValueError(f"RUTUBE channel page redirected outside RUTUBE: {url}")
            url = location
        raise ValueError(f"RUTUBE channel page redirects too many times: {url}")

    async def _api(self, path: str, **kwargs: Any) -> httpx.Response:
        """GET по официальному API. Redirect наружу здесь тоже не следуется."""
        response = await self.client.get(f"{self.api_base}{path}", follow_redirects=False,
                                         **kwargs)
        if response.is_redirect:
            raise ValueError(f"RUTUBE API redirected: {self.api_base}{path}")
        return response

    async def videos(self, channel_id: int, limit: int = 100) -> tuple[RutubeChannel, list[RutubeVideo]]:
        result: list[RutubeVideo] = []
        page = 1
        channel_name = str(channel_id)
        while len(result) < max(1, limit):
            response = await self._api(f"/video/person/{channel_id}/",
                                       params={"page": page, "format": "json"})
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

    async def video(self, video_id: str) -> RutubeVideo:
        """Read one exact video resource for refresh/deletion confirmation."""

        response = await self._api(f"/video/{video_id}/", params={"format": "json"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RUTUBE video response must be an object")
        external_id = str(payload.get("id") or "").strip()
        published = payload.get("publication_ts") or payload.get("created_ts")
        if not external_id or not published:
            raise ValueError("RUTUBE video response is incomplete")
        if external_id != str(video_id):
            raise ValueError("RUTUBE video response identity mismatch")
        return RutubeVideo(
            id=external_id,
            title=str(payload.get("title") or external_id),
            published_at=parse_rutube_datetime(str(published)),
            views=int(payload["hits"]) if payload.get("hits") is not None else None,
            url=str(
                payload.get("video_url")
                or f"https://rutube.ru/video/{external_id}/"
            ),
            raw=payload,
        )

    async def video_metrics(self, video_id: str) -> RutubeVideoMetrics:
        vote_response, comments_response = await asyncio.gather(
            self._api(f"/numerator/video/{video_id}/vote"),
            self._api(f"/v2/comments/video/{video_id}/",
                      params={"client": "wdp", "sort_by": "date_added_desc"}),
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
