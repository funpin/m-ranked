from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .max_api import MaxChannel, MaxPost


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _json_safe(value: Any) -> Any:
    """Convert SDK models to values SQLite's JSON encoder can persist.

    PyMax response models occasionally contain unresolved Pydantic serializers.
    Falling back to ``vars()`` keeps collection running, but the nested values
    still need normalizing before they are stored as raw diagnostic payloads.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return _json_safe(dump(mode="python", by_alias=True))
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: _json_safe(item) for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _model_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _json_safe(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json", by_alias=True)
        except Exception:
            # Some PyMax/Pydantic combinations leave a MockValSer placeholder
            # on nested response models. Raw fields are diagnostic only, so a
            # normalized vars() representation is an appropriate fallback.
            pass
    if hasattr(value, "__dict__"):
        return _json_safe({
            key: item for key, item in vars(value).items()
            if not key.startswith("_")
        })
    return {}


def _install_pymax_decode_compatibility() -> None:
    """Retry malformed MAX msgpack strings with replacement decoding.

    MAX currently returns a few string-typed fields containing non-UTF-8 bytes.
    PyMax decodes the entire response strictly, which otherwise discards valid
    channel/message metrics along with the malformed auxiliary field.
    """
    import msgpack
    from pymax.protocol.tcp.payload import MsgpackPayloadCodec

    if getattr(MsgpackPayloadCodec, "_m_ranked_utf8_compat", False):
        return
    strict_decode = MsgpackPayloadCodec.decode

    def decode(codec: Any, payload_bytes: bytes) -> Any:
        try:
            return strict_decode(codec, payload_bytes)
        except UnicodeDecodeError:
            def ext_hook(code: int, data: bytes) -> Any:
                if code != codec.WRAPPED_VALUE_EXT_CODE:
                    return msgpack.ExtType(code, data)
                return msgpack.unpackb(
                    data, raw=False, strict_map_key=False,
                    unicode_errors="replace", ext_hook=ext_hook,
                )

            try:
                return msgpack.unpackb(
                    payload_bytes, raw=False, strict_map_key=False,
                    unicode_errors="replace", ext_hook=ext_hook,
                )
            except msgpack.exceptions.ExtraData as exc:
                return exc.unpacked

    MsgpackPayloadCodec.decode = decode
    MsgpackPayloadCodec._m_ranked_utf8_compat = True


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


def _comment_count(payload: Any) -> int | None:
    """Read the comment counter encoded in MAX discussion buttons.

    MAX channel comments are commonly exposed through an inline keyboard.
    Some providers include the count in the button text, while the explicit
    "Прокомментировать" call to action represents an open, empty discussion.
    A generic "Комментарии" button carries no count and must remain unknown.
    """
    explicit_counts: list[int] = []
    empty_discussion = False

    def visit(value: Any, in_buttons: bool = False) -> None:
        nonlocal empty_discussion
        if isinstance(value, dict):
            for key, item in value.items():
                is_buttons = in_buttons or str(key).casefold() == "buttons"
                if is_buttons and str(key).casefold() == "text" and isinstance(item, str):
                    label = item.casefold()
                    if "коммент" not in label and "comment" not in label:
                        continue
                    match = re.search(r"\d[\d\s]*", label)
                    if match:
                        explicit_counts.append(int(match.group(0).replace(" ", "")))
                    elif "прокоммент" in label:
                        empty_discussion = True
                else:
                    visit(item, is_buttons)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, in_buttons)

    visit(payload)
    if explicit_counts:
        return max(explicit_counts)
    return 0 if empty_discussion else None


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
    views: dict[str, int | None] | None = None,
) -> MaxPost:
    message_id = int(getattr(message, "id"))
    timestamp = int(getattr(message, "time"))
    published_at = datetime.fromtimestamp(
        timestamp / 1000 if timestamp > 100_000_000_000 else timestamp,
        tz=timezone.utc,
    )
    stats = getattr(message, "stats", None) or {}
    if not isinstance(stats, dict):
        stats = _model_dict(stats)
    view_count = _optional_int(stats.get("views"))
    if view_count is None and views:
        view_count = views.get(str(message_id), views.get(message_id))
    reaction_info = None
    if reactions:
        reaction_info = reactions.get(str(message_id)) or reactions.get(message_id)
    reaction_info = reaction_info or getattr(message, "reaction_info", None)
    reaction_total, breakdown = _reaction_state(reaction_info)
    raw = _model_dict(message)
    if view_count is not None:
        raw_stats = raw.get("stats")
        if not isinstance(raw_stats, dict):
            raw_stats = {}
            raw["stats"] = raw_stats
        raw_stats["views"] = view_count
    return MaxPost(
        id=str(message_id),
        published_at=published_at,
        views=view_count,
        reactions=reaction_total,
        reposts=None,
        comments=_comment_count(raw),
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
        _install_pymax_decode_compatibility()
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
            parsed = urlparse(value)
            if parsed.netloc.casefold() == "web.max.ru":
                return parsed._replace(netloc="max.ru").geturl()
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
        missing_view_ids = [
            message_id for message_id, message in zip(message_ids, messages)
            if _optional_int(
                (_model_dict(getattr(message, "stats", None))
                 if not isinstance(getattr(message, "stats", None), dict)
                 else (getattr(message, "stats", None) or {})).get("views")
            ) is None
        ]
        views = await self._message_views(chat_id, missing_view_ids)
        reactions = await self._request(
            self.client.get_reactions, chat_id, message_ids,
        )
        return [
            _message_post(message, chat_id, reactions, views)
            for message in messages
        ]

    async def _message_views(
        self,
        chat_id: int,
        message_ids: list[int],
    ) -> dict[str, int | None]:
        if not message_ids:
            return {}
        getter = getattr(self.client, "get_message_stats", None)
        if callable(getter):
            response = await self._request(getter, chat_id, message_ids)
        else:
            from pymax.protocol.enums import Opcode

            response = await self._request(
                self.client._app.invoke,
                Opcode.MSG_GET_STAT,
                {"chatId": chat_id, "messageIds": message_ids},
            )
        payload = response if isinstance(response, dict) else getattr(response, "payload", None)
        stats = (payload or {}).get("stats") or {}
        result: dict[str, int | None] = {}
        for message_id, values in stats.items():
            if not isinstance(values, dict):
                values = _model_dict(values)
            result[str(message_id)] = _optional_int(values.get("views"))
        return result

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
