from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .max_api import MaxChannel, MaxPost


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", by_alias=True)
    if hasattr(value, "__dict__"):
        return {
            key: item for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _reaction_state(value: Any) -> tuple[int | None, dict[str, int] | None]:
    if value is None:
        return None, None
    total = getattr(value, "total_count", None)
    counters = getattr(value, "counters", None)
    if isinstance(value, dict):
        total = value.get("total_count", value.get("totalCount", total))
        counters = value.get("counters", counters)
    breakdown: dict[str, int] = {}
    for counter in counters or []:
        if isinstance(counter, dict):
            reaction = counter.get("reaction") or counter.get("id")
            count = counter.get("count")
        else:
            reaction = getattr(counter, "reaction", None)
            count = getattr(counter, "count", None)
        if reaction is not None and count is not None:
            breakdown[str(_value(reaction))] = int(count)
    if total is None and breakdown:
        total = sum(breakdown.values())
    return _optional_int(total), breakdown or None


def _post_type(message: Any) -> str:
    attachments = list(getattr(message, "attaches", None) or [])
    if len(attachments) > 1:
        return "album"
    if not attachments:
        return "text"
    kind = _value(getattr(attachments[0], "type", None))
    return str(kind or "media").casefold()


def _is_repost(message: Any, chat_id: int) -> bool:
    link = getattr(message, "link", None)
    if link is None:
        return False
    link_type = _value(getattr(link, "type", None))
    if str(link_type or "").casefold() != "forward":
        return False
    source_chat_id = getattr(link, "chat_id", None)
    return source_chat_id is None or int(source_chat_id) != int(chat_id)


def _message_post(
    message: Any,
    chat_id: int,
    reactions: dict[str, Any] | None = None,
) -> MaxPost:
    message_id = int(getattr(message, "id"))
    timestamp = int(getattr(message, "time"))
    published_at = datetime.fromtimestamp(
        timestamp / 1000 if timestamp > 100_000_000_000 else timestamp,
        tz=timezone.utc,
    )
    stats = getattr(message, "stats", None) or {}
    reaction_info = None
    if reactions:
        reaction_info = reactions.get(str(message_id)) or reactions.get(message_id)
    reaction_info = reaction_info or getattr(message, "reaction_info", None)
    reaction_total, breakdown = _reaction_state(reaction_info)
    raw = _model_dict(message)
    return MaxPost(
        id=str(message_id),
        published_at=published_at,
        views=_optional_int(stats.get("views")),
        reactions=reaction_total,
        reposts=None,
        comments=None,
        url=None,
        raw=raw,
        reaction_breakdown=breakdown,
        post_type=_post_type(message),
        is_repost=_is_repost(message, chat_id),
    )


class MaxUserClient:
    """Monitoring adapter over a persistent MAX user session.

    PyMax is imported lazily so the rest of the service and its tests remain
    usable when MAX user-session support is not configured.
    """

    def __init__(
        self,
        phone: str,
        session_path: str | Path,
        first_name: str | None = None,
        last_name: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not phone and client is None:
            raise ValueError("MAX_USER_PHONE is required")
        self.session_path = Path(session_path)
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self._connected = False
        if client is not None:
            self.client = client
            return
        try:
            from pymax import (
                Client, ConsolePasswordProvider, ExtraConfig, RegistrationConfig,
            )
            from pymax.api.session.enums import DeviceType
        except ImportError as exc:  # pragma: no cover - depends on deployment extras
            raise RuntimeError(
                "MAX user client is not installed; install project requirements"
            ) from exc
        self.client = Client(
            phone=phone,
            work_dir=str(self.session_path.parent),
            session_name=self.session_path.name,
            password_provider=ConsolePasswordProvider(),
            extra_config=ExtraConfig(
                device_type=DeviceType.DESKTOP,
                reconnect=True,
                telemetry=False,
                registration_config=(
                    RegistrationConfig(first_name=first_name, last_name=last_name)
                    if first_name else None
                ),
            ),
        )

    async def connect(self) -> None:
        if self._connected:
            return
        await self.client.connect()
        is_connected = getattr(self.client, "is_connected", None)
        if callable(is_connected) and not is_connected():
            raise ConnectionError("MAX client did not establish a session")
        if self.session_path.exists():
            os.chmod(self.session_path, 0o600)
        self._connected = True

    async def _request(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        await self.connect()
        try:
            return await method(*args, **kwargs)
        except Exception:
            # PyMax.connect() is intentionally one-shot. Mark the wrapper as
            # disconnected so the next polling cycle builds a fresh runtime.
            self._connected = False
            try:
                await self.client.close()
            except Exception:
                pass
            raise

    async def authorize_interactive(self) -> None:
        await self.connect()

    async def close(self) -> None:
        await self.client.close()
        self._connected = False

    @staticmethod
    def _reference_url(reference: str) -> str:
        value = reference.strip()
        if "://" in value:
            return value
        return f"https://max.ru/{value.lstrip('@/')}"

    async def resolve_channel(
        self,
        reference: str,
        chat_id: int | None = None,
    ) -> MaxChannel:
        if chat_id is None:
            chat = await self._request(
                self.client.join_channel, self._reference_url(reference),
            )
        else:
            chat = await self._request(self.client.get_chat, chat_id)
        chat_type = str(_value(getattr(chat, "type", ""))).casefold()
        if chat_type != "channel":
            raise ValueError(f"MAX chat {getattr(chat, 'id', chat_id)} is not a channel")
        link = getattr(chat, "link", None) or self._reference_url(reference)
        return MaxChannel(
            id=int(getattr(chat, "id")),
            title=str(getattr(chat, "title", None) or reference),
            participants_count=_optional_int(getattr(chat, "participants_count", None)),
            link=str(link) if link else None,
        )

    async def _with_reactions(self, chat_id: int, messages: list[Any]) -> list[MaxPost]:
        if not messages:
            return []
        message_ids = [int(getattr(message, "id")) for message in messages]
        reactions = await self._request(
            self.client.get_reactions, chat_id, message_ids,
        )
        return [_message_post(message, chat_id, reactions) for message in messages]

    async def posts(self, chat_id: int, count: int = 100) -> list[MaxPost]:
        messages = await self._request(
            self.client.fetch_history,
            chat_id=chat_id,
            backward=max(1, min(count, 100)),
        )
        return await self._with_reactions(chat_id, list(messages or []))

    async def posts_by_ids(self, chat_id: int, message_ids: list[str]) -> list[MaxPost]:
        ids = [int(value) for value in message_ids]
        messages = await self._request(self.client.get_messages, chat_id, ids)
        return await self._with_reactions(chat_id, list(messages or []))


def max_username(reference: str) -> str:
    value = reference.strip()
    if "://" not in value:
        return value.lstrip("@/")
    path = [part for part in urlparse(value).path.split("/") if part]
    return path[-1].lstrip("@") if path else value
