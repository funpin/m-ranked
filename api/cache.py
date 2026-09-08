"""Кэш публичных ответов в памяти процесса.

Прежде эту роль играл Redis с ключом, привязанным к номеру ревизии. Ревизия
штамповалась в пиковом режиме раз в 3.5 секунды, поэтому такой кэш был мёртв:
каждая запись обесценивала весь его объём. Здесь ключ не зависит от ревизии,
а сбрасывается по факту записи — через LISTEN/NOTIFY из outbox.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import psycopg

CHANNEL = "mranked_cache"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Entry:
    value: Any
    etag: str
    expires_at: float
    tags: frozenset[str]


class ResponseCache:
    """LRU с общим TTL и сбросом по тегам.

    Тег — это область данных ("publications", "overview", "comparison"), которую
    затрагивает запись. Событие outbox несёт список затронутых тегов, и воркер
    выбрасывает ровно те записи, которые их несут. Сброса по префиксу ключа нет
    намеренно: при 19 тысячах записей в час перебор ключей стоит дороже кэша.
    """

    def __init__(self, capacity: int, ttl_seconds: int) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Entry | None:
        if self._capacity == 0:
            return None
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.expires_at <= time.monotonic():
            del self._entries[key]
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return entry

    def put(self, key: str, value: Any, etag: str, tags: frozenset[str]) -> None:
        if self._capacity == 0:
            return
        self._entries[key] = Entry(value, etag, time.monotonic() + self._ttl, tags)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def invalidate(self, tags: frozenset[str]) -> int:
        if not tags:
            return 0
        doomed = [key for key, entry in self._entries.items() if entry.tags & tags]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "hits": self._hits, "misses": self._misses}


class InvalidationListener:
    """Слушает pg_notify и сбрасывает затронутые теги.

    TTL остаётся страховкой на случай потерянного уведомления: NOTIFY не
    доставляется процессу, который в этот момент не подключён.
    """

    def __init__(self, dsn: str, cache: ResponseCache) -> None:
        self._dsn = dsn
        self._cache = cache
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="cache-invalidation")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with_suppressed = (asyncio.CancelledError,)
            try:
                await self._task
            except with_suppressed:
                pass

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    # Соединение рвалось — какие-то уведомления потеряны.
                    self._cache.clear()
                    backoff = 1.0
                    async for notify in conn.notifies():
                        self._apply(notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("слушатель инвалидации отключён, повтор через %.0f с", backoff,
                               exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _apply(self, payload: str) -> None:
        try:
            tags = frozenset(json.loads(payload).get("tags") or ())
        except (ValueError, AttributeError):
            logger.warning("неразбираемое уведомление инвалидации: %r", payload)
            self._cache.clear()
            return
        dropped = self._cache.invalidate(tags)
        if dropped:
            logger.info("сброшено записей кэша: %d, теги %s", dropped, sorted(tags))
