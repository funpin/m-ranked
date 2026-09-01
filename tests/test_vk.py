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


def test_joint_vk_post_uses_monitored_community_number():
    post = parse_vk_post({
        "owner_id": -164293611,
        "id": 4949,
        "date": 1_700_000_000,
        "coowners": {
            "coowner_post_id": {"owner_id": -62258607, "post_id": 72020},
            "list": [
                {"owner_id": -164293611},
                {"owner_id": -62258607},
                {"owner_id": -777},
            ],
        },
    })
    identity = post.identity_for_community(62258607)
    assert identity is not None
    assert identity.external_key == "-62258607_72020"
    assert identity.source_external_key == "-164293611_4949"
    assert identity.is_joint
    assert identity.additional_author_count == 2
    assert post.identity_for_community(999) is None


def test_joint_vk_post_reads_local_number_from_coowner_list():
    post = parse_vk_post({
        "owner_id": -164293611,
        "id": 59413,
        "date": 1_700_000_000,
        "coowners": {
            "list": [
                {"owner_id": -164293611, "post_id": 59413},
                {"owner_id": -74773715, "post_id": 1267},
                {"owner_id": -777, "post_id": 99},
            ],
        },
    })

    identity = post.identity_for_community(74773715)

    assert identity is not None
    assert identity.external_key == "-74773715_1267"
    assert identity.source_external_key == "-164293611_59413"
    assert identity.is_joint
    assert identity.additional_author_count == 2


def test_joint_vk_post_reads_numeric_local_number_for_target_owner():
    post = parse_vk_post({
        "owner_id": -74773715,
        "id": 59413,
        "date": 1_700_000_000,
        "coowners": {
            "coowner_post_id": 1267,
            "list": [
                {"owner_id": -164293611},
                {"owner_id": -74773715},
                {"owner_id": -777},
            ],
        },
    })

    identity = post.identity_for_community(74773715)

    assert identity is not None
    assert identity.external_key == "-74773715_1267"
    assert identity.source_external_key == "-74773715_59413"
    assert identity.is_joint
    assert identity.additional_author_count == 2


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
