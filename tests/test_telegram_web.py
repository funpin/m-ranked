import asyncio

from app.telegram_web import TelegramWebSession


class FakePage:
    def __init__(self):
        self.arguments = None

    async def evaluate(self, _script, arguments=None):
        self.arguments = arguments
        return {
            "rows": {
                str(message_id): message_id % 10
                for message_id in arguments["messageIds"]
            }
        }


def test_comments_are_batched_and_normalized(tmp_path):
    session = TelegramWebSession(tmp_path / "profile", concurrency=2)
    session._page = FakePage()
    session._authorized = True

    result = asyncio.run(session.comments("example", [42, 43, 42]))

    assert result == {42: 2, 43: 3}
    assert session._page.arguments == {
        "username": "example",
        "messageIds": [42, 43],
    }
    assert session.connected


def test_empty_comment_batch_does_not_start_browser(tmp_path):
    session = TelegramWebSession(tmp_path / "profile")

    assert asyncio.run(session.comments("example", [])) == {}
    assert not session.connected
