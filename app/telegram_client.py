from __future__ import annotations

from pathlib import Path
from typing import Any


class TelegramReader:
    def __init__(self, api_id: int, api_hash: str, session_path: Path):
        try:
            from telethon import TelegramClient
        except ImportError as exc:
            raise RuntimeError("Telethon is not installed") from exc
        self._client = TelegramClient(str(session_path), api_id, api_hash)

    @property
    def client(self) -> Any:
        return self._client

    async def connect(self, require_authorized: bool = True) -> bool:
        await self._client.connect()
        authorized = await self._client.is_user_authorized()
        if require_authorized and not authorized:
            await self._client.disconnect()
            raise RuntimeError("Telegram session is not authorized; run: python -m app auth")
        return authorized

    async def authorize_interactive(self) -> None:
        await self._client.start()
        me = await self._client.get_me()
        print(f"Authorized Telegram user id={me.id}")

    async def disconnect(self) -> None:
        if self._client.is_connected():
            await self._client.disconnect()

    async def __aenter__(self) -> "TelegramReader":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
