import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.vk import VkApiError, VkClient, normalize_vk_community_ref, parse_vk_post


def test_normalize_vk_community_ref():
    assert normalize_vk_community_ref("https://vk.com/mgumariupolkuindzhi/") == "mgumariupolkuindzhi"
    assert normalize_vk_community_ref("https://vk.ru/mephi_official") == "mephi_official"
    assert normalize_vk_community_ref("https://m.vk.ru/zgu_university/") == "zgu_university"
    assert normalize_vk_community_ref("@public123") == "public123"
    with pytest.raises(ValueError):
        normalize_vk_community_ref("https://example.com/not-vk")


def test_parse_vk_post_metrics():
    post = parse_vk_post({
        "owner_id": -42,
        "id": 17,
        "date": 1_700_000_000,
        "attachments": [{"type": "photo"}, {"type": "video"}],
        "views": {"count": 1200},
        "likes": {"count": 80},
        "comments": {"count": 9},
        "reposts": {"count": 4},
    })
    assert post.external_key == "-42_17"
    assert post.post_type == "album"
    assert (post.views, post.likes, post.comments, post.reposts) == (1200, 80, 9, 4)
    assert post.published_at == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


def test_vk_client_reads_community_and_wall():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("groups.getById"):
            return httpx.Response(200, json={"response": {"groups": [{
                "id": 42, "screen_name": "university", "name": "University",
                "members_count": 1234,
            }]}})
        return httpx.Response(200, json={"response": {"items": [{
            "owner_id": -42, "id": 7, "date": 1_700_000_000,
            "views": {"count": 100}, "likes": {"count": 5},
            "comments": {"count": 2}, "reposts": {"count": 1},
        }]}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = VkClient("token", client=http)
            community = await client.community("university")
            posts = await client.wall(community.id)
            return community, posts

    community, posts = asyncio.run(scenario())
    assert community.members_count == 1234
    assert posts[0].comments == 2


def test_vk_client_surfaces_api_errors():
    async def scenario():
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json={"error": {"error_code": 5, "error_msg": "User authorization failed"}},
        ))
        async with httpx.AsyncClient(transport=transport) as http:
            await VkClient("bad", client=http).community("university")

    with pytest.raises(VkApiError, match="VK API 5"):
        asyncio.run(scenario())
