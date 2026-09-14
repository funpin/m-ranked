"""Кэш публичных ответов в памяти процесса.

Прежде эту роль играл Redis с ключом, привязанным к номеру ревизии. Ревизия
штамповалась в пиковом режиме раз в 3.5 секунды, поэтому такой кэш был мёртв:
каждая запись обесценивала весь его объём. Здесь ключ не зависит от ревизии,
а сбрасывается по факту записи — через LISTEN/NOTIFY из outbox.

У сброса есть нижняя граница возраста. На проде уведомление приходит чаще
раза в секунду и всегда несёт все три области сразу: коллекторы пишут
непрерывно. Сброс «сразу и насовсем» означал бы, что записи не доживают до
второго читателя, и кэш снова мёртв — уже по другой причине. Поэтому
уведомление не удаляет свежую запись, а помечает её несвежей.

Несвежая запись продолжает обслуживать читателей, пока идёт пересчёт. Без
этого ровно один посетитель раз в окно платил за перестроение ответа своим
временем: на проде это 730–1024 мс против 1.5 мс у остальных — те самые
редкие «зависания на секунду». Ответ и так объявляет в заголовке
stale-while-revalidate, так что сервер просто перестал быть строже к себе,
чем к своим клиентам. Совсем старую запись — дольше stale_seconds — отдавать
уже нельзя, и тогда читатель ждёт пересчёт.

Цифры на экране — приросты за три часа, сутки, неделю и месяц, и отставание
в несколько секунд в них не видно; сам ответ несёт asOf и datasetRevision,
по которым видно, какой это снимок.
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
    born_at: float
    fresh_until: float

    def is_stale(self, now: float) -> bool:
        return now >= self.fresh_until


class ResponseCache:
    """LRU с общим TTL и сбросом по тегам.

    Тег — это область данных ("publications", "overview", "comparison"), которую
    затрагивает запись. Событие outbox несёт список затронутых тегов, и воркер
    выбрасывает ровно те записи, которые их несут. Сброса по префиксу ключа нет
    намеренно: при 19 тысячах записей в час перебор ключей стоит дороже кэша.
    """

    def __init__(self, capacity: int, ttl_seconds: int, min_age_seconds: float = 0.0,
                 stale_seconds: float = 0.0) -> None:
        if min_age_seconds < 0 or stale_seconds < 0:
            raise ValueError("min_age_seconds and stale_seconds must not be negative")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._min_age = min(float(min_age_seconds), float(ttl_seconds))
        self._stale = min(float(stale_seconds), float(ttl_seconds))
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._refreshing: set[str] = set()
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0

    def begin_refresh(self, key: str) -> bool:
        """Занимает право пересчитать запись. Второй желающий получает отказ."""
        if key in self._refreshing:
            return False
        self._refreshing.add(key)
        return True

    def end_refresh(self, key: str) -> None:
        self._refreshing.discard(key)

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
        if entry.is_stale(time.monotonic()):
            self._stale_hits += 1
        return entry

    def put(self, key: str, value: Any, etag: str, tags: frozenset[str]) -> None:
        if self._capacity == 0:
            return
        born = time.monotonic()
        # Пока записи не было, ответ считается свежим: помечает его несвежим
        # уведомление о записи, а TTL остаётся страховкой на потерянное.
        self._entries[key] = Entry(value, etag, born + self._ttl, tags, born,
                                   born + self._ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def invalidate(self, tags: frozenset[str]) -> int:
        """Помечает записи с этими тегами несвежими, но не раньше нижней границы.

        Запись не выбрасывается: она продолжает обслуживать читателей, пока
        идёт пересчёт, и живёт после этого не дольше stale_seconds. Нижняя
        граница возраста держит темп пересчёта: уведомления приходят чаще раза
        в секунду, и без неё ответ перестраивался бы непрерывно.

        Возвращает число записей, ставших несвежими прямо сейчас.
        """
        if not tags:
            return 0
        now = time.monotonic()
        marked = 0
        for entry in self._entries.values():
            if not entry.tags & tags:
                continue
            stale_from = max(now, entry.born_at + self._min_age)
            if stale_from < entry.fresh_until:
                entry.fresh_until = stale_from
                entry.expires_at = min(entry.expires_at, stale_from + self._stale)
                marked += 1
        return marked

    def clear(self) -> None:
        self._entries.clear()
        self._refreshing.clear()

    @property
    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "hits": self._hits,
                "misses": self._misses, "stale_hits": self._stale_hits,
                "refreshing": len(self._refreshing)}


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
        marked = self._cache.invalidate(tags)
        if marked:
            logger.info("помечено несвежими записей кэша: %d, теги %s", marked, sorted(tags))
