import asyncio

import httpx

from app.rutube import RutubeClient


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
