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


def test_concurrent_connect_starts_one_shared_browser(tmp_path):
    page = FakePage()
    starts = 0
    launches = 0

    async def goto(_url, *, wait_until):
        assert wait_until == "domcontentloaded"

    async def wait_for_function(_script, *, timeout):
        assert timeout == 60_000

    page.goto = goto
    page.wait_for_function = wait_for_function

    class Context:
        pages = [page]

    class Chromium:
        async def launch_persistent_context(self, *_args, **_kwargs):
            nonlocal launches
            launches += 1
            await asyncio.sleep(0)
            return Context()

    class Playwright:
        chromium = Chromium()

    class Starter:
        async def start(self):
            nonlocal starts
            starts += 1
            await asyncio.sleep(0)
            return Playwright()

    session = TelegramWebSession(tmp_path / "profile")
    session._playwright_import = lambda: Starter

    async def connect_all():
        await asyncio.gather(*(session.connect() for _ in range(6)))

    asyncio.run(connect_all())

    assert starts == 1
    assert launches == 1
    assert session.connected


def test_failed_concurrent_connect_is_cooled_down(tmp_path):
    launches = 0

    class Chromium:
        async def launch_persistent_context(self, *_args, **_kwargs):
            nonlocal launches
            launches += 1
            await asyncio.sleep(0)
            raise RuntimeError("browser unavailable")

    class Playwright:
        chromium = Chromium()

        async def stop(self):
            pass

    class Starter:
        async def start(self):
            return Playwright()

    session = TelegramWebSession(tmp_path / "profile")
    session._playwright_import = lambda: Starter

    async def connect_all():
        return await asyncio.gather(
            *(session.connect() for _ in range(6)),
            return_exceptions=True,
        )

    results = asyncio.run(connect_all())

    assert launches == 1
    assert all(isinstance(result, RuntimeError) for result in results)


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
