import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from collector_runtime.rutube import RutubeClient, channel_page_url


def test_rutube_exact_video_lookup_uses_identity_endpoint():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/video/video-1/"
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json={
            "id": "video-1",
            "title": "Exact video",
            "publication_ts": "2026-09-03T08:00:00Z",
            "hits": 42,
            "video_url": "https://rutube.ru/video/video-1/",
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).video("video-1")

    video = asyncio.run(run())
    assert video.id == "video-1"
    assert video.views == 42
    assert video.published_at == datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)


def test_rutube_video_metrics_uses_vote_and_comments_endpoints():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/numerator/video/video-1/vote":
            return httpx.Response(200, json={"positive": 23, "negative": 2})
        if request.url.path == "/api/v2/comments/video/video-1/":
            assert request.url.params["client"] == "wdp"
            return httpx.Response(200, json={"comments_count": 7, "results": []})
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).video_metrics("video-1")

    metrics = asyncio.run(run())
    assert metrics.likes == 23
    assert metrics.comments == 7
    assert metrics.raw["vote"]["negative"] == 2


def test_rutube_video_metrics_keeps_unavailable_counter_as_none():
    async def handler(request: httpx.Request) -> httpx.Response:
        if "/vote" in request.url.path:
            return httpx.Response(403)
        return httpx.Response(200, json={"comments_count": 0})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).video_metrics("video-1")

    metrics = asyncio.run(run())
    assert metrics.likes is None
    assert metrics.comments == 0


def test_rutube_subscriber_count_uses_public_channel_page():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://rutube.ru/channel/123/")
        return httpx.Response(
            200,
            text='<script>{"subscribers_count":2923}</script>',
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).subscriber_count(123)

    assert asyncio.run(run()) == 2923


def test_rutube_subscriber_count_is_optional():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).subscriber_count(123)

    assert asyncio.run(run()) is None


def test_rutube_channel_page_url_rejects_non_rutube_targets():
    assert channel_page_url("https://rutube.ru/channel/123") == "https://rutube.ru/channel/123/"
    assert channel_page_url("https://www.rutube.ru/u/studio/") == "https://rutube.ru/u/studio/"
    for hostile in (
        "http://rutube.ru/channel/123/",
        "https://rutube.ru:8080/channel/123/",
        "https://rutube.ru@127.0.0.1/channel/123/",
        "https://127.0.0.1/channel/123/",
        "https://[::1]/channel/123/",
        "https://10.0.0.5/channel/123/",
        "https://169.254.169.254/latest/meta-data/",
        "https://rutube.ru.evil.example/channel/123/",
        "https://rutube.ru/channel/123/?next=http://127.0.0.1",
        "file:///etc/passwd",
        None,
    ):
        assert channel_page_url(hostile) is None, hostile


def test_rutube_channel_page_refuses_redirect_outside_rutube():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "rutube.ru":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        raise AssertionError(f"collector followed a redirect to {request.url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).subscriber_count(
                123, "https://rutube.ru/channel/123/")

    assert asyncio.run(run()) is None


def test_rutube_subscriber_count_ignores_a_hostile_stored_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://rutube.ru/channel/123/")
        return httpx.Response(200, text='{"subscribers_count":7}')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).subscriber_count(
                123, "http://127.0.0.1:8080/admin")

    assert asyncio.run(run()) == 7


def test_rutube_resolve_channel_refuses_a_hostile_stored_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"collector fetched {request.url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await RutubeClient("https://rutube.ru/api", http).resolve_channel(
                "studio", "http://127.0.0.1:8080/admin")

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_rutube_api_calls_never_follow_a_redirect():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "rutube.ru"
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = RutubeClient("https://rutube.ru/api", http)
            with pytest.raises(ValueError, match="redirected"):
                await client.video("video-1")
            metrics = await client.video_metrics("video-1")
            assert metrics.likes is None and metrics.comments is None

    asyncio.run(run())


def test_rutube_default_client_does_not_follow_redirects():
    assert RutubeClient().client.follow_redirects is False
