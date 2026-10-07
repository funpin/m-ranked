"""Кэш норм аккаунтов для «Находок».

Нормы — медианы за 30 дней на каждом часу 1–24 — не зависят от фильтров
страницы и за минуты почти не меняются, а их расчёт читает контрольные точки
всех аккаунтов. Поэтому они считаются отдельным запросом не чаще раза в
NORMS_TTL_SECONDS на процесс; одновременные промахи ждут один расчёт.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

NORMS_TTL_SECONDS = 600.0

Loader = Callable[[], Awaitable[list[dict[str, Any]]]]


def serializable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Строки NORMS в виде, который уходит параметром jsonb в FINDINGS."""
    return [{key: (str(value) if key == "account_id" else value) for key, value in row.items()}
            for row in rows]


class NormsCache:
    def __init__(self, ttl_seconds: float = NORMS_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._value: list[dict[str, Any]] | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self, load: Loader) -> list[dict[str, Any]]:
        if self._value is not None and self._clock() < self._expires:
            return self._value
        async with self._lock:
            # Пока ждали замок, норму мог посчитать соседний запрос.
            if self._value is not None and self._clock() < self._expires:
                return self._value
            self._value = serializable(await load())
            self._expires = self._clock() + self._ttl
            return self._value
