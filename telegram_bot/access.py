"""Кто что может: таблица команд из спека бота.

Контентные команды проверяются по чату (любой участник подключённого чата —
наша команда) или по человеку; /status и /settings — только по человеку и
только в личке. /start и /id — любому.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .store import Recipient

PUBLIC_COMMANDS = frozenset({"start", "id"})
CONTENT_COMMANDS = frozenset({"top", "week", "digest", "help"})


@dataclass(frozen=True)
class Access:
    user_id: int | None
    chat_id: int
    private: bool
    admin: bool
    alerts: bool
    known_person: bool
    known_chat: bool

    @property
    def known(self) -> bool:
        return self.known_person or self.known_chat


def access_for(message: dict, recipients: Iterable[Recipient]) -> Access:
    """Права для сообщения (или для сообщения под нажатой кнопкой с её «from»)."""
    chat = message.get("chat") or {}
    chat_id = int(chat["id"])
    private = chat.get("type") == "private"
    # От имени чата (анонимный админ, канал) «from» — служебный бот Telegram, а не человек.
    user_id = None if message.get("sender_chat") else (message.get("from") or {}).get("id")
    by_id = {r.chat_id: r for r in recipients}
    person = by_id.get(user_id) if isinstance(user_id, int) else None
    if person is not None and person.kind != "person":
        person = None
    connected = by_id.get(chat_id) if not private else None
    return Access(
        user_id=user_id if isinstance(user_id, int) else None,
        chat_id=chat_id,
        private=private,
        admin=bool(person and person.is_admin),
        alerts=bool(person and person.alerts),
        known_person=person is not None,
        known_chat=connected is not None and connected.kind == "chat",
    )


def allowed(command: str, access: Access) -> bool:
    if command in PUBLIC_COMMANDS:
        return True
    if command in CONTENT_COMMANDS:
        return access.known
    if command == "status":
        return access.alerts and access.private
    if command == "settings":
        return access.admin and access.private
    if command == "emoji":  # id кастомных эмодзи для таблицы слотов
        return access.admin and access.private
    return False
