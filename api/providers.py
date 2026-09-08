"""Явный, несекретный статус развёртывания интеграций.

Отсутствие настройки означает unknown, а не догадку о неисправных учётных
данных. Предупреждение выдаётся только при явном missing и никогда не содержит
значений ключей.
"""
from __future__ import annotations

import functools
import hashlib
import os

from .representation import representation_version

PLATFORMS = ("telegram", "vk", "max", "rutube")
ALLOWED = ("configured", "missing", "unknown")


def status(platform: str) -> str:
    value = os.environ.get(f"INTEGRATION_{platform.upper()}", "unknown")
    if value not in ALLOWED:
        raise ValueError(f"статус интеграции должен быть одним из {ALLOWED}, получено {value!r}")
    return value


def warning(platform: str) -> str | None:
    if status(platform) != "missing":
        return None
    if platform == "vk":
        return "vk_token_required"
    if platform == "max":
        phone = os.environ.get("HEALTH_MAX_PHONE_CONFIGURED", "false").lower() in ("1", "true", "yes")
        return "max_session_required" if phone else "max_phone_required"
    if platform == "rutube":
        return "rutube_api_disabled"
    return None


def public_representation_version() -> str:
    """Флаги развёртывания меняются без новой ревизии базы и без новой сборки.

    Поэтому они входят в версию представления: иначе смена статуса интеграции
    не сбросила бы валидаторы ETag.
    """
    digest = hashlib.sha256()
    digest.update(representation_version().encode("utf-8"))
    for platform in PLATFORMS:
        digest.update(b"\x00")
        digest.update(status(platform).encode("ascii"))
        digest.update(b"\x00")
        digest.update((warning(platform) or "").encode("ascii"))
    return digest.hexdigest()
