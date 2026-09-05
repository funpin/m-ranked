from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Mapping


_SECRET_KEY = re.compile(
    r"(?:authorization|cookie|password|secret|session|token|api[_-]?key|phone)",
    re.IGNORECASE,
)


def as_utc(value: Any, *, fallback: datetime | None = None) -> datetime:
    if value is None or str(value).strip() == "":
        if fallback is None:
            raise ValueError("required timestamp is missing")
        return fallback.astimezone(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def completeness(row: Mapping[str, Any]) -> str:
    if bool(row.get("history_forced_incomplete")):
        return "forced_incomplete"
    return "complete" if bool(row.get("history_complete")) else "incomplete"


def access_mode(platform: str, raw: Any) -> str:
    value = str(raw or "").strip().casefold()
    aliases = {
        "public": "public_web" if platform == "telegram" else "public_api",
        "public_web": "public_web",
        "telegram_web": "telegram_web",
        "mtproto": "mtproto",
        "api": "official_api",
        "official": "official_api",
        "official_api": "official_api",
        "public_api": "public_api",
        "user": "user_session",
        "user_api": "user_session",
        "user_session": "user_session",
        "disabled": "disabled",
    }
    if value in aliases:
        return aliases[value]
    if platform == "max":
        return "user_session"
    if platform in {"vk", "rutube"}:
        return "official_api" if platform == "vk" else "public_api"
    return "public_web"


def observation_quality(raw: Any, *, default: str = "unknown") -> str:
    value = str(raw or "").strip().casefold().replace("-", "_")
    aliases = {
        "exact": "exact",
        "rounded": "rounded",
        "approximate": "estimated",
        "estimated": "estimated",
        "degraded": "degraded",
        "suspected_reset": "suspected_reset",
        "invalid": "invalid",
        "unknown": "unknown",
    }
    return aliases.get(value, default)


def parse_json(value: Any, *, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"unparsed_text": str(value)}


def sanitize_evidence(value: Any) -> Any:
    """Recursively redact credential-shaped fields before PostgreSQL evidence storage."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _SECRET_KEY.search(str(key))
                else sanitize_evidence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_evidence(item) for item in value]
    return value
