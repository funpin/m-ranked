"""Тонкий клиент Telegram Bot API поверх httpx.

Токен входит в путь каждого запроса, поэтому он не должен попадать никуда,
кроме самого запроса: ни в сообщения исключений, ни в repr, ни в журнал.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

# httpx пишет полный URL запроса, а в нём токен, уже на уровне INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_ORIGIN = "https://api.telegram.org"
CALL_TIMEOUT = 20.0
CONNECT_TIMEOUT = 10.0
# Ответ на long polling приходит не раньше его таймаута: запас на сеть.
LONG_POLL_MARGIN = 15.0
# Дольше этого ждать по retry_after не стоит: цикл бота встанет.
MAX_RETRY_AFTER = 60.0
PHOTO_NAME = "cover.png"

# Поле файла multipart: имя поля → (имя файла, байты, тип).
Files = dict[str, tuple[str, bytes, str]]


class TelegramError(Exception):
    """Запрос к Bot API не удался. Текст не содержит токена."""


class BotBlocked(TelegramError):
    """Бот не может писать в чат: заблокирован, удалён или чата нет."""

    def __init__(self, chat_id: int) -> None:
        super().__init__(f"Бот не может писать в чат {chat_id}")
        self.chat_id = chat_id


class CannotInitiate(TelegramError):
    """Человек ещё не открывал бота (не нажимал /start): писать первым нельзя.

    Не BotBlocked: такого получателя не убирают, он появится, когда нажмёт /start.
    """

    def __init__(self, chat_id: int) -> None:
        super().__init__(f"Бот не может написать первым в чат {chat_id}")
        self.chat_id = chat_id


def _keyboard_markup(keyboard: list[list[dict]] | None) -> dict | None:
    return {"inline_keyboard": keyboard} if keyboard is not None else None


class TelegramClient:
    def __init__(
        self,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._prefix = f"/bot{token}/"
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=API_ORIGIN,
            transport=transport,
            trust_env=False,
            timeout=httpx.Timeout(CALL_TIMEOUT, connect=CONNECT_TIMEOUT),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "TelegramClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _post_once(
        self, method: str, payload: dict[str, Any], read_timeout: float | None,
        files: Files | None = None,
    ) -> tuple[int, dict[str, Any]]:
        timeout = (
            httpx.Timeout(CALL_TIMEOUT, connect=CONNECT_TIMEOUT, read=read_timeout)
            if read_timeout is not None else httpx.USE_CLIENT_DEFAULT
        )
        try:
            if files is None:
                response = await self._http.post(
                    self._prefix + method, json=payload, timeout=timeout,
                )
            else:
                # multipart: поля формы — строки, файл — отдельной частью.
                response = await self._http.post(
                    self._prefix + method, timeout=timeout, files=files,
                    data={key: str(value) for key, value in payload.items()},
                )
        except httpx.HTTPError as error:
            # Сообщение httpx может содержать URL с токеном: берём только
            # класс ошибки и обрываем цепочку исключений.
            raise TelegramError(
                f"{method}: сбой запроса к Telegram ({type(error).__name__})"
            ) from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise TelegramError(
                f"{method}: неожиданный ответ Telegram (HTTP {response.status_code})"
            )
        return response.status_code, body

    async def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        chat_id: int | None = None,
        read_timeout: float | None = None,
        files: Files | None = None,
    ) -> Any:
        retried = False
        while True:
            status, body = await self._post_once(method, payload, read_timeout, files)
            if body.get("ok") is True:
                return body.get("result")
            code = body.get("error_code", status)
            description = str(body.get("description", ""))
            lowered = description.lower()
            if code == 429 and not retried:
                parameters = body.get("parameters")
                delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
                delay = float(delay) if isinstance(delay, (int, float)) else 1.0
                if delay > MAX_RETRY_AFTER:
                    raise TelegramError(
                        f"{method}: Telegram просит подождать {delay:.0f} с (429)"
                    )
                retried = True
                await self._sleep(delay)
                continue
            if code == 400 and "message is not modified" in lowered:
                return None
            if chat_id is not None and code == 403 and "can't initiate conversation" in lowered:
                raise CannotInitiate(chat_id)
            if chat_id is not None and (
                code == 403 or (code == 400 and "chat not found" in lowered)
            ):
                raise BotBlocked(chat_id)
            raise TelegramError(f"{method}: Telegram ответил {code}: {description}")

    async def get_me(self) -> dict:
        return await self._call("getMe", {}) or {}

    async def get_updates(self, offset: int | None, timeout: int = 50) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call(
            "getUpdates", payload, read_timeout=timeout + LONG_POLL_MARGIN,
        )
        return result or []

    async def send_message(
        self, chat_id: int, text: str, keyboard: list[list[dict]] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        markup = _keyboard_markup(keyboard)
        if markup is not None:
            payload["reply_markup"] = markup
        return await self._call("sendMessage", payload, chat_id=chat_id)

    async def send_photo(self, chat_id: int, photo: bytes | str, caption: str) -> dict:
        """Картинка с подписью (HTML): байты — загрузка файла, строка — file_id
        уже загруженной. Ошибки — как у send_message."""
        payload: dict[str, Any] = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if isinstance(photo, str):
            payload["photo"] = photo
            return await self._call("sendPhoto", payload, chat_id=chat_id) or {}
        files = {"photo": (PHOTO_NAME, bytes(photo), "image/png")}
        return await self._call("sendPhoto", payload, chat_id=chat_id, files=files) or {}

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: list[list[dict]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        markup = _keyboard_markup(keyboard)
        if markup is not None:
            payload["reply_markup"] = markup
        await self._call("editMessageText", payload, chat_id=chat_id)

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text is not None:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def set_commands(
        self, commands: list[tuple[str, str]], scope: dict,
    ) -> None:
        await self._call("setMyCommands", {
            "commands": [
                {"command": command, "description": description}
                for command, description in commands
            ],
            "scope": scope,
        })

    async def leave_chat(self, chat_id: int) -> None:
        await self._call("leaveChat", {"chat_id": chat_id})
