import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.max_user_api import (
    MaxUserClient,
    _comment_count,
    _install_pymax_decode_compatibility,
    _model_dict,
    max_username,
)


class FakeSdkClient:
    def __init__(self):
        self.connected = False
        self.closed = False
        self.joined = []
        self.reaction_calls = []
        self.stats_calls = []
        self.connect_calls = 0
        self.message = SimpleNamespace(
            id=700,
            time=1_750_000_000_000,
            type="message",
            attaches=[SimpleNamespace(type=SimpleNamespace(value="PHOTO"))],
            stats=None,
            reaction_info=None,
            link=SimpleNamespace(type=SimpleNamespace(value="forward"), chat_id=-999),
        )

    async def connect(self):
        self.connect_calls += 1
        self.connected = True

    def is_connected(self):
        return self.connected

    async def close(self):
        self.connected = False
        self.closed = True

    async def join_channel(self, link):
        self.joined.append(link)
        return SimpleNamespace(
            id=-123, type=SimpleNamespace(value="CHANNEL"), title="Канал вуза",
            participants_count=456, link="https://max.ru/vuz",
        )

    async def get_chat(self, chat_id):
        return SimpleNamespace(
            id=chat_id, type="channel", title="Канал вуза",
            participants_count=456, link="https://max.ru/vuz",
        )

    async def fetch_history(self, **kwargs):
        return [self.message]

    async def get_messages(self, chat_id, ids):
        return [self.message] if 700 in ids else []

    async def get_reactions(self, chat_id, ids):
        self.reaction_calls.append((chat_id, ids))
        return {
            "700": SimpleNamespace(
                total_count=8,
                counters=[
                    SimpleNamespace(reaction="LIKE", count=5),
                    SimpleNamespace(reaction="FIRE", count=3),
                ],
            ),
        }

    async def get_message_stats(self, chat_id, ids):
        self.stats_calls.append((chat_id, ids))
        return {"stats": {str(message_id): {"views": 321} for message_id in ids}}


def test_max_user_client_resolves_channel_and_parses_metrics(tmp_path):
    sdk = FakeSdkClient()
    client = MaxUserClient("", tmp_path / "max.session.db", client=sdk)

    channel = asyncio.run(client.resolve_channel("vuz"))
    posts = asyncio.run(client.posts(channel.id, 25))
    asyncio.run(client.close())

    assert sdk.joined == ["https://max.ru/vuz"]
    assert (channel.id, channel.title, channel.participants_count) == (-123, "Канал вуза", 456)
    assert len(posts) == 1
    post = posts[0]
    assert (post.id, post.views, post.reactions) == ("700", 321, 8)
    assert post.reaction_breakdown == {"LIKE": 5, "FIRE": 3}
    assert post.post_type == "photo"
    assert post.is_repost is True
    assert sdk.reaction_calls == [(-123, [700])]
    assert sdk.stats_calls == [(-123, [700])]
    assert sdk.closed is True


def test_max_user_client_fetches_due_messages_by_id(tmp_path):
    sdk = FakeSdkClient()
    client = MaxUserClient("", tmp_path / "max.session.db", client=sdk)

    posts = asyncio.run(client.posts_by_ids(-123, ["700"]))

    assert [post.id for post in posts] == ["700"]
    assert posts[0].views == 321
    assert sdk.stats_calls == [(-123, [700])]
    assert max_username("https://max.ru/example") == "example"
    assert max_username("@example") == "example"


def test_max_user_client_normalizes_web_channel_links(tmp_path):
    sdk = FakeSdkClient()
    client = MaxUserClient("", tmp_path / "max.session.db", client=sdk)

    asyncio.run(client.resolve_channel("https://web.max.ru/example"))

    assert sdk.joined == ["https://max.ru/example"]


def test_max_user_client_reconnects_after_request_failure(tmp_path):
    class FlakySdkClient(FakeSdkClient):
        def __init__(self):
            super().__init__()
            self.fail_once = True

        async def join_channel(self, link):
            if self.fail_once:
                self.fail_once = False
                raise ConnectionError("temporary disconnect")
            return await super().join_channel(link)

    sdk = FlakySdkClient()
    client = MaxUserClient("", tmp_path / "max.session.db", client=sdk)

    try:
        asyncio.run(client.resolve_channel("vuz"))
    except ConnectionError:
        pass
    channel = asyncio.run(client.resolve_channel("vuz"))

    assert channel.id == -123
    assert sdk.connect_calls == 2


def test_model_dict_falls_back_when_pydantic_serializer_is_unresolved():
    class BrokenModel:
        visible = "ignored class attribute"

        def __init__(self):
            self.payload = SimpleNamespace(
                created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                opaque=b"\xff\x00",
            )

        def model_dump(self, **kwargs):
            raise TypeError("'MockValSer' object is not an instance of 'SchemaSerializer'")

    raw = _model_dict(BrokenModel())

    assert raw == {
        "payload": {
            "created_at": "2026-09-02T00:00:00+00:00",
            "opaque": "ff00",
        },
    }


def test_pymax_decoder_retries_malformed_utf8_strings():
    pytest.importorskip("pymax")
    from pymax.protocol.tcp.payload import MsgpackPayloadCodec

    _install_pymax_decode_compatibility()

    assert MsgpackPayloadCodec().decode(b"\xa1\xff") == "\ufffd"


def test_comment_count_reads_explicit_max_discussion_buttons():
    assert _comment_count({
        "attaches": [{"keyboard": {"buttons": [[{
            "text": "💬 8 комментариев →", "type": "OPEN_APP",
        }]]}}],
    }) == 8
    assert _comment_count({
        "attaches": [{"keyboard": {"buttons": [[{
            "text": "💬 Комментарии (12)", "type": "OPEN_APP",
        }]]}}],
    }) == 12


def test_comment_count_distinguishes_empty_unknown_and_disabled_discussions():
    assert _comment_count({
        "attaches": [{"keyboard": {"buttons": [[{
            "text": "💬 Прокомментировать →", "type": "OPEN_APP",
        }]]}}],
    }) == 0
    assert _comment_count({
        "attaches": [{"keyboard": {"buttons": [[{
            "text": "💬 Комментарии", "type": "OPEN_APP",
        }]]}}],
    }) is None
    assert _comment_count({"attaches": []}) is None
