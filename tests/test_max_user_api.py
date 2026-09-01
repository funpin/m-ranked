import asyncio
from types import SimpleNamespace

from app.max_user_api import MaxUserClient, max_username


class FakeSdkClient:
    def __init__(self):
        self.connected = False
        self.closed = False
        self.joined = []
        self.reaction_calls = []
        self.connect_calls = 0
        self.message = SimpleNamespace(
            id=700,
            time=1_750_000_000_000,
            type="message",
            attaches=[SimpleNamespace(type=SimpleNamespace(value="PHOTO"))],
            stats={"views": 321},
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
    assert sdk.closed is True


def test_max_user_client_fetches_due_messages_by_id(tmp_path):
    sdk = FakeSdkClient()
    client = MaxUserClient("", tmp_path / "max.session.db", client=sdk)

    posts = asyncio.run(client.posts_by_ids(-123, ["700"]))

    assert [post.id for post in posts] == ["700"]
    assert max_username("https://max.ru/example") == "example"
    assert max_username("@example") == "example"


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
