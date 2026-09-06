from __future__ import annotations

from typing import Any


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a positive integer") from error
    if normalized <= 0 or str(value).strip() != str(normalized):
        raise ValueError(f"{field} must be a canonical positive integer")
    return normalized


def telegram_message_external_id(message_id: Any) -> str:
    """Return the canonical target identity for one Telegram message."""

    return f"m:{_positive_integer(message_id, 'message_id')}"


def telegram_group_external_id(grouped_id: Any) -> str:
    """Return the canonical target identity for one Telegram media group."""

    return f"g:{_positive_integer(grouped_id, 'grouped_id')}"


def telegram_publication_external_id(
    message_id: Any,
    grouped_id: Any | None = None,
) -> str:
    """Match the identity emitted by target collectors for a logical post."""

    if grouped_id is not None:
        return telegram_group_external_id(grouped_id)
    return telegram_message_external_id(message_id)


def parse_telegram_external_id(external_id: str) -> tuple[str, int]:
    """Parse a canonical target identity without accepting ambiguous bare IDs."""

    prefix, separator, raw_value = str(external_id).partition(":")
    if separator != ":" or prefix not in {"m", "g"}:
        raise ValueError("Telegram external_id must use the m: or g: namespace")
    return prefix, _positive_integer(raw_value, "external_id")
