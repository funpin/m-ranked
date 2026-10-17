"""Настройки и клиент Telegram Bot API: токен не утекает, 429 и 403 разобраны."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from telegram_bot.config import BotConfig
from telegram_bot.telegram import BotBlocked, TelegramClient, TelegramError

# Заведомо поддельное значение: в реальных файлах токена нет.
TOKEN = "123:abc"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    token_file = tmp_path / "token"
    token_file.write_text("\n" + TOKEN + "\n\n", encoding="utf-8")
    env = {
        "TELEGRAM_BOT_TOKEN_FILE": str(token_file),
        "TELEGRAM_BOT_ADMIN_IDS": "11, 22",
        "TELEGRAM_BOT_DSN": "postgresql://bot@db/app",
    }
    env.update(extra)
    return env


def test_token_file_first_non_empty_line(tmp_path):
    config = BotConfig.from_env(_env(tmp_path))
    assert config.token == TOKEN
    assert config.admin_ids == frozenset({11, 22})
    assert config.api_base_url == "http://127.0.0.1:8080"
    assert config.spool_dir == Path("/var/lib/m-ranked/telegram-bot/inbox")
    assert config.timezone == "Europe/Moscow"
    assert TOKEN not in repr(config)

    overridden = BotConfig.from_env(_env(
        tmp_path,
        TELEGRAM_BOT_API_BASE_URL="http://api.test:9000",
        TELEGRAM_BOT_SPOOL_DIR=str(tmp_path / "spool"),
    ))
    assert overridden.api_base_url == "http://api.test:9000"
    assert overridden.spool_dir == tmp_path / "spool"


def test_missing_token_file_names_path_not_token(tmp_path):
    missing = tmp_path / "нет-такого-файла"
    with pytest.raises(SystemExit) as raised:
        BotConfig.from_env(_env(tmp_path, TELEGRAM_BOT_TOKEN_FILE=str(missing)))
    assert str(missing) in str(raised.value)


def test_empty_token_file_exits(tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        BotConfig.from_env(_env(tmp_path, TELEGRAM_BOT_TOKEN_FILE=str(empty)))
    assert str(empty) in str(raised.value)


@pytest.mark.parametrize("name", [
    "TELEGRAM_BOT_TOKEN_FILE", "TELEGRAM_BOT_ADMIN_IDS", "TELEGRAM_BOT_DSN",
])
def test_required_env_missing_exits(tmp_path, name):
    env = _env(tmp_path)
    del env[name]
    with pytest.raises(SystemExit) as raised:
        BotConfig.from_env(env)
    assert name in str(raised.value)


def test_bad_admin_ids_exit(tmp_path):
    with pytest.raises(SystemExit):
        BotConfig.from_env(_env(tmp_path, TELEGRAM_BOT_ADMIN_IDS="11,abc"))


class Recorder:
    """MockTransport, который отдаёт заготовленные ответы по очереди."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


def ok(result) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def fail(code: int, description: str, **parameters) -> httpx.Response:
    body: dict = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(code, json=body)


def _client(recorder: Recorder, sleeps: list[float] | None = None) -> TelegramClient:
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return TelegramClient(
        TOKEN, transport=httpx.MockTransport(recorder), sleep=sleep,
    )


def _run(coro_factory):
    async def scenario():
        return await coro_factory()

    return asyncio.run(scenario())


def test_send_uses_html_without_previews():
    recorder = Recorder(ok({"message_id": 7}))
    keyboard = [[{"text": "Да", "callback_data": "y"}]]

    async def go():
        client = _client(recorder)
        try:
            return await client.send_message(5, "<b>привет</b>", keyboard)
        finally:
            await client.aclose()

    assert _run(go) == {"message_id": 7}
    body = recorder.body()
    assert body["chat_id"] == 5
    assert body["text"] == "<b>привет</b>"
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True
    assert body["reply_markup"] == {"inline_keyboard": keyboard}
    assert recorder.requests[0].url.path == f"/bot{TOKEN}/sendMessage"


def test_send_without_keyboard_has_no_reply_markup():
    recorder = Recorder(ok({"message_id": 1}))

    async def go():
        async with _client(recorder) as client:
            await client.send_message(5, "x")

    _run(go)
    assert "reply_markup" not in recorder.body()


def test_edit_message_html_and_keyboard():
    recorder = Recorder(ok(True))
    keyboard = [[{"text": "x", "callback_data": "x"}]]

    async def go():
        async with _client(recorder) as client:
            return await client.edit_message(5, 9, "t", keyboard)

    assert _run(go) is None
    body = recorder.body()
    assert recorder.requests[0].url.path.endswith("/editMessageText")
    assert body["message_id"] == 9
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True
    assert body["reply_markup"] == {"inline_keyboard": keyboard}


def test_get_updates_params_and_long_read_timeout():
    recorder = Recorder(ok([{"update_id": 3}]), ok([]))

    async def go():
        async with _client(recorder) as client:
            first = await client.get_updates(None)
            second = await client.get_updates(4, timeout=10)
            return first, second

    first, second = _run(go)
    assert first == [{"update_id": 3}]
    assert second == []
    assert recorder.body(0) == {"timeout": 50}
    assert recorder.body(1) == {"offset": 4, "timeout": 10}
    # Чтение должно жить дольше, чем держит запрос long polling.
    assert recorder.requests[0].extensions["timeout"]["read"] > 50
    assert recorder.requests[1].extensions["timeout"]["read"] > 10


def test_answer_callback_set_commands_leave_chat():
    recorder = Recorder(ok(True), ok(True), ok(True), ok(True))
    scope = {"type": "chat", "chat_id": 5}

    async def go():
        async with _client(recorder) as client:
            await client.answer_callback("cb1", "готово")
            await client.answer_callback("cb2")
            await client.set_commands([("start", "Начать")], scope)
            await client.leave_chat(5)

    _run(go)
    assert recorder.body(0) == {"callback_query_id": "cb1", "text": "готово"}
    assert recorder.body(1) == {"callback_query_id": "cb2"}
    assert recorder.body(2) == {
        "commands": [{"command": "start", "description": "Начать"}],
        "scope": scope,
    }
    assert recorder.body(3) == {"chat_id": 5}


def test_retry_after_429_once():
    recorder = Recorder(fail(429, "Too Many Requests: retry after 1", retry_after=1), ok({"message_id": 1}))
    sleeps: list[float] = []

    async def go():
        async with _client(recorder, sleeps) as client:
            return await client.send_message(5, "x")

    assert _run(go) == {"message_id": 1}
    assert sleeps == [1]
    assert len(recorder.requests) == 2


def test_second_429_raises_telegram_error():
    recorder = Recorder(
        fail(429, "Too Many Requests", retry_after=1),
        fail(429, "Too Many Requests", retry_after=1),
    )
    sleeps: list[float] = []

    async def go():
        async with _client(recorder, sleeps) as client:
            await client.send_message(5, "x")

    with pytest.raises(TelegramError):
        _run(go)
    assert sleeps == [1]
    assert len(recorder.requests) == 2


def test_not_modified_is_ignored():
    recorder = Recorder(fail(400, "Bad Request: message is not modified: specified new message content"))

    async def go():
        async with _client(recorder) as client:
            return await client.edit_message(5, 9, "t")

    assert _run(go) is None


@pytest.mark.parametrize("response", [
    fail(403, "Forbidden: bot was blocked by the user"),
    fail(400, "Bad Request: chat not found"),
])
def test_forbidden_raises_bot_blocked(response):
    recorder = Recorder(response)

    async def go():
        async with _client(recorder) as client:
            await client.send_message(42, "x")

    with pytest.raises(BotBlocked) as raised:
        _run(go)
    assert raised.value.chat_id == 42
    assert isinstance(raised.value, TelegramError)


def test_other_api_error_is_telegram_error_not_blocked():
    recorder = Recorder(fail(400, "Bad Request: can't parse entities"))

    async def go():
        async with _client(recorder) as client:
            await client.send_message(5, "<x")

    with pytest.raises(TelegramError) as raised:
        _run(go)
    assert not isinstance(raised.value, BotBlocked)
    assert "can't parse entities" in str(raised.value)


def test_non_json_response_is_telegram_error():
    recorder = Recorder(httpx.Response(502, text="<html>bad gateway</html>"))

    async def go():
        async with _client(recorder) as client:
            await client.send_message(5, "x")

    with pytest.raises(TelegramError):
        _run(go)


def test_token_never_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    url_with_token = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    recorder = Recorder(
        httpx.ConnectError(f"boom {url_with_token}"),
        httpx.ReadTimeout(f"slow {url_with_token}"),
        fail(400, "Bad Request: nope"),
        fail(403, "Forbidden: bot was blocked by the user"),
        ok({"message_id": 1}),
    )
    errors: list[BaseException] = []

    async def go():
        client = _client(recorder)
        async with client:
            for _ in range(4):
                try:
                    await client.send_message(5, "x")
                except TelegramError as error:
                    errors.append(error)
            await client.send_message(5, "x")
            assert TOKEN not in repr(client)

    _run(go)
    assert len(errors) == 4
    for error in errors:
        assert TOKEN not in str(error)
        assert TOKEN not in repr(error)
        # Исходное исключение httpx несёт URL с токеном — цепочку обрываем.
        assert error.__cause__ is None
        assert error.__suppress_context__ or error.__context__ is None
    assert TOKEN not in caplog.text
