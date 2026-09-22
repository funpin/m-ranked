"""Кэши публичных ответов для deployment-профилей A и B.

Профиль A держит ограниченный LRU в одном API-процессе. Профиль B кладёт те же
записи в Redis, чтобы несколько процессов и отдельный прогрев видели общий
результат.

Ключ — логический запрос, без номера ревизии набора данных. Ревизия на
Сервере 2 сменяется 2400 раз в час: её двигает каждая принятая пачка. Пока
она входила в ключ, запись устаревала быстрее, чем приходил второй
посетитель, и почти каждый просмотр карточки аккаунта платил полсекунды
пересчёта, а страница публикации — ещё и за закреплённую карточку аккаунта.
Теперь запись одна на запрос, а ревизия, по которой она собрана, лежит в ней
самой и видна в ответе как datasetRevision.

Свежесть отсчитывается от возраста записи. Молодая отдаётся как есть. Старше
fresh_seconds — отдаётся сразу, а пересчёт идёт фоном: ответ и так объявляет
stale-while-revalidate. Читатель ждёт пересчёт, только когда записи нет
совсем — её никто не спрашивал дольше TTL, и прогрев её не держит.

Уведомление о записи помечает запись несвежей, но не раньше нижней границы
возраста и не укорачивает ей жизнь: на проде уведомления идут чаще раза в
секунду, и раньше они сводили кэш к минуте жизни — после чего очередной
посетитель снова ждал пересчёт.

Цифры на экране — приросты за три часа, сутки, неделю и месяц, и отставание
в минуту в них не видно; сам ответ несёт asOf и datasetRevision, по которым
видно, какой это снимок.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from inspect import isawaitable
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
import redis.asyncio as redis
from redis.exceptions import RedisError

CHANNEL = "mranked_cache"
logger = logging.getLogger(__name__)
_SAFE_TAG = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SECRET = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._~+/=-]+|access[_-]?token|"
    r"api[_-]?key|cookie|password|passwd|session[_-]?(?:id|token)|"
    r"postgres(?:ql)?://[^\s]+:[^@\s]+@)"
)


async def cache_call(value: Any) -> Any:
    """Await Redis operations while preserving the synchronous LRU interface."""
    return await value if isawaitable(value) else value


@dataclass(slots=True)
class Entry:
    value: Any
    etag: str
    expires_at: float
    tags: frozenset[str]
    born_at: float
    fresh_until: float
    # Ревизия набора данных, по которой собран ответ. В ключ она не входит.
    revision: int = 0

    def is_stale(self, now: float) -> bool:
        return now >= self.fresh_until


class ResponseCache:
    """LRU с общим TTL и сбросом по тегам.

    Тег — это область данных ("publications", "overview", "comparison"), которую
    затрагивает запись. Событие outbox несёт список затронутых тегов, и воркер
    выбрасывает ровно те записи, которые их несут. Сброса по префиксу ключа нет
    намеренно: при 19 тысячах записей в час перебор ключей стоит дороже кэша.
    """

    def __init__(self, capacity: int, ttl_seconds: float, min_age_seconds: float = 0.0,
                 *, fresh_seconds: float | None = None,
                 revision_hold_seconds: float | None = None) -> None:
        if min_age_seconds < 0:
            raise ValueError("min_age_seconds must not be negative")
        if (fresh_seconds is not None and fresh_seconds <= 0) or (
            revision_hold_seconds is not None and revision_hold_seconds <= 0
        ):
            raise ValueError("fresh_seconds and revision_hold_seconds must be positive")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._min_age = min(float(min_age_seconds), float(ttl_seconds))
        self.fresh_seconds = min(
            float(ttl_seconds if fresh_seconds is None else fresh_seconds),
            float(ttl_seconds),
        )
        self._revision_hold = float(
            ttl_seconds if revision_hold_seconds is None else revision_hold_seconds
        )
        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._refreshing: set[str] = set()
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0
        self._revision: tuple[int, Any] | None = None
        self._revision_until = 0.0
        self._lock_acquired = 0
        self._lock_contended = 0

    def begin_refresh(self, key: str) -> bool:
        """Занимает право пересчитать запись. Второй желающий получает отказ."""
        if key in self._refreshing:
            self._lock_contended += 1
            return False
        self._refreshing.add(key)
        self._lock_acquired += 1
        return True

    def end_refresh(self, key: str) -> None:
        self._refreshing.discard(key)

    def is_stale(self, entry: Entry) -> bool:
        return entry.is_stale(time.monotonic())

    def age(self, entry: Entry) -> float:
        return time.monotonic() - entry.born_at

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

    def put(self, key: str, value: Any, etag: str, tags: frozenset[str],
            revision: int = 0) -> None:
        if self._capacity == 0:
            return
        born = time.monotonic()
        self._entries[key] = Entry(value, etag, born + self._ttl, tags, born,
                                   born + self.fresh_seconds, revision)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def invalidate(self, tags: frozenset[str]) -> int:
        """Помечает записи с этими тегами несвежими, но не раньше нижней границы.

        Запись не выбрасывается и не укорачивает себе жизнь: она продолжает
        обслуживать читателей, пока идёт фоновый пересчёт. Нижняя граница
        возраста держит темп пересчёта: уведомления приходят чаще раза в
        секунду, и без неё ответ перестраивался бы непрерывно.

        Возвращает число записей, ставших несвежими прямо сейчас.
        """
        if not tags or self._min_age >= self.fresh_seconds:
            return 0
        now = time.monotonic()
        marked = 0
        for entry in self._entries.values():
            if not entry.tags & tags:
                continue
            stale_from = max(now, entry.born_at + self._min_age)
            if stale_from < entry.fresh_until:
                entry.fresh_until = stale_from
                marked += 1
        return marked

    def clear(self) -> None:
        self._entries.clear()
        self._refreshing.clear()
        self._revision = None

    def get_revision(self) -> tuple[int, Any] | None:
        if self._revision is None or time.monotonic() >= self._revision_until:
            return None
        return self._revision

    def set_revision(self, revision: int, committed_at: Any) -> tuple[int, Any]:
        """Закрепляет опубликованную ревизию на окно удержания."""
        self._revision = (revision, committed_at)
        self._revision_until = time.monotonic() + self._revision_hold
        return self._revision

    @property
    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "hits": self._hits,
                "misses": self._misses, "stale_hits": self._stale_hits,
                "refreshing": len(self._refreshing),
                "refresh_acquired": self._lock_acquired,
                "refresh_contended": self._lock_contended}

    async def close(self) -> None:
        return None


class RedisResponseCache:
    """Shared Redis cache with fail-open database rebuilds.

    Redis stores only public serialized responses and opaque, already-hashed
    response keys. Any Redis failure is a miss, never an API error.
    Distributed refresh ownership is a tokenised SET NX lock with
    a bounded lifetime; Lua releases only the caller's token.
    """

    _RELEASE = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(
        self,
        url: str,
        *,
        capacity: int,
        ttl_seconds: float,
        min_age_seconds: float = 0.0,
        fresh_seconds: float | None = None,
        revision_hold_seconds: float | None = None,
        refresh_lock_seconds: float = 150.0,
        timeout_ms: int = 250,
        namespace: str = "mranked:response:v1",
    ) -> None:
        self._capacity = capacity
        self._ttl = float(ttl_seconds)
        self._min_age = min(float(min_age_seconds), self._ttl)
        self.fresh_seconds = min(
            float(self._ttl if fresh_seconds is None else fresh_seconds), self._ttl,
        )
        self._revision_hold_ms = max(1, int(
            (self._ttl if revision_hold_seconds is None else revision_hold_seconds)
            * 1000
        ))
        self._lock_ms = max(1, int(refresh_lock_seconds * 1000))
        self._namespace = namespace
        timeout = timeout_ms / 1000
        self._redis = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
            health_check_interval=30,
        )
        # The local set is used only when Redis itself is unavailable while a
        # rebuild lock is acquired. Entries are deliberately not mirrored:
        # an unavailable shared cache must be a miss and a database rebuild,
        # never a possibly divergent process-local hit.
        self._fallback_locks = ResponseCache(0, ttl_seconds)
        self._tokens: dict[str, bytes] = {}
        self._revision_uncertain = False
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0
        self._errors = 0
        self._lock_acquired = 0
        self._lock_contended = 0

    def _entry_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self._namespace}:entry:{digest}"

    def _lock_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self._namespace}:refresh:{digest}"

    def _tag_key(self, tag: str) -> str:
        return f"{self._namespace}:tag:{tag}"

    @property
    def _revision_key(self) -> str:
        return f"{self._namespace}:revision"

    @staticmethod
    def _encode(entry: Entry) -> bytes:
        return json.dumps({
            "value": entry.value,
            "etag": entry.etag,
            "expiresAt": entry.expires_at,
            "tags": sorted(entry.tags),
            "bornAt": entry.born_at,
            "freshUntil": entry.fresh_until,
            "revision": entry.revision,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _decode(raw: bytes) -> Entry:
        value = json.loads(raw)
        return Entry(
            value["value"], value["etag"], float(value["expiresAt"]),
            frozenset(value["tags"]), float(value["bornAt"]),
            float(value["freshUntil"]), int(value.get("revision", 0)),
        )

    def age(self, entry: Entry) -> float:
        return time.time() - entry.born_at

    async def get(self, key: str) -> Entry | None:
        if self._capacity == 0:
            return None
        try:
            raw = await self._redis.get(self._entry_key(key))
            if raw is None:
                self._misses += 1
                return None
            entry = self._decode(raw)
            now = time.time()
            if entry.expires_at <= now:
                pipe = self._redis.pipeline(transaction=False)
                pipe.delete(self._entry_key(key))
                pipe.zrem(f"{self._namespace}:lru", self._entry_key(key))
                for tag in entry.tags:
                    pipe.zrem(self._tag_key(tag), self._entry_key(key))
                await pipe.execute()
                self._misses += 1
                return None
            await self._redis.zadd(f"{self._namespace}:lru", {
                self._entry_key(key): now,
            })
            self._hits += 1
            if entry.is_stale(now):
                self._stale_hits += 1
            return entry
        except (RedisError, OSError, ValueError, TypeError):
            self._errors += 1
            logger.warning("Redis response cache unavailable during get")
            self._misses += 1
            return None

    async def put(
        self, key: str, value: Any, etag: str, tags: frozenset[str],
        revision: int = 0,
    ) -> None:
        if self._capacity == 0:
            return
        if any(not _SAFE_TAG.fullmatch(tag) for tag in tags):
            raise ValueError("cache tags must be bounded identifiers")
        serialized_value = value if isinstance(value, str) else json.dumps(value, default=str)
        if _SECRET.search(serialized_value):
            self._errors += 1
            logger.warning("Redis response cache refused a secret-shaped public value")
            return
        now = time.time()
        entry = Entry(
            value, etag, now + self._ttl, tags, now, now + self.fresh_seconds,
            revision,
        )
        entry_key = self._entry_key(key)
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.set(entry_key, self._encode(entry), px=max(1, int(self._ttl * 1000)))
            pipe.zadd(f"{self._namespace}:lru", {entry_key: now})
            for tag in tags:
                # The expiry timestamp as score lets invalidation prune dead
                # references even when this hot tag is continuously extended.
                pipe.zadd(self._tag_key(tag), {entry_key: entry.expires_at})
            await pipe.execute()
            overflow = int(await self._redis.zcard(f"{self._namespace}:lru")) - self._capacity
            if overflow > 0:
                victims = await self._redis.zpopmin(
                    f"{self._namespace}:lru", count=overflow,
                )
                if victims:
                    victim_keys = [item[0] for item in victims]
                    raw_entries = await self._redis.mget(victim_keys)
                    cleanup = self._redis.pipeline(transaction=False)
                    cleanup.delete(*victim_keys)
                    for victim_key, raw_entry in zip(victim_keys, raw_entries, strict=True):
                        if raw_entry is None:
                            continue
                        for tag in self._decode(raw_entry).tags:
                            cleanup.zrem(self._tag_key(tag), victim_key)
                    await cleanup.execute()
        except (RedisError, OSError):
            self._errors += 1
            logger.warning("Redis response cache unavailable during put")

    async def invalidate(self, tags: frozenset[str]) -> int:
        if any(not _SAFE_TAG.fullmatch(tag) for tag in tags):
            raise ValueError("cache tags must be bounded identifiers")
        # Пометка несвежим стоит чтения каждой записи с тегом, а уведомления на
        # проде идут каждые полторы секунды. Когда свежесть по возрасту
        # истекает не позже нижней границы, пометить уведомлению нечего, и
        # перебирать тысячи записей прогретого каталога незачем: этот перебор
        # забивал Redis и цикл событий API, и операции кэша уходили в таймаут.
        if not tags or self._min_age >= self.fresh_seconds:
            return 0
        try:
            # Опубликованная ревизия здесь не сбрасывается: она удерживается
            # своим окном. Сброс на каждое уведомление двигал её раз в
            # полторы секунды, и вместе с ней уходило всё, что на неё опиралось.
            members: set[bytes] = set()
            now = time.time()
            for tag in tags:
                await self._redis.zremrangebyscore(self._tag_key(tag), "-inf", now)
                members.update(await self._redis.zrangebyscore(
                    self._tag_key(tag), now, "+inf",
                ))
            marked = 0
            for entry_key in members:
                raw = await self._redis.get(entry_key)
                if raw is None:
                    continue
                entry = self._decode(raw)
                if not entry.tags & tags:
                    continue
                stale_from = max(now, entry.born_at + self._min_age)
                if stale_from >= entry.fresh_until:
                    continue
                entry.fresh_until = stale_from
                # xx: запись могла истечь между чтением и записью — не
                # воскрешать её; keepttl: срок жизни уведомление не меняет.
                await self._redis.set(
                    entry_key, self._encode(entry), xx=True, keepttl=True,
                )
                marked += 1
            return marked
        except (RedisError, OSError, ValueError, TypeError):
            self._errors += 1
            logger.warning("Redis response cache unavailable during invalidation")
            return 0

    async def clear(self) -> None:
        """Forget this process's trust in the revision after reconnect.

        Other workers did not lose notifications, and global deletion would
        punish them. The next request re-reads PostgreSQL and refreshes the
        shared revision hint; revision-scoped keys and TTL retain correctness.
        """
        self._revision_uncertain = True

    async def get_revision(self) -> tuple[int, Any] | None:
        if self._revision_uncertain:
            return None
        try:
            raw = await self._redis.get(self._revision_key)
            if raw is None:
                return None
            value = json.loads(raw)
            committed = value.get("committedAt")
            return int(value["revision"]), (
                datetime.fromisoformat(committed) if committed else None
            )
        except (RedisError, OSError, ValueError, TypeError):
            self._errors += 1
            return None

    async def set_revision(self, revision: int, committed_at: Any) -> tuple[int, Any]:
        """Публикует ревизию на окно удержания или принимает уже опубликованную.

        Первый процесс, прочитавший базу после истечения окна, закрепляет
        свою ревизию; остальные принимают её, а не свою. Иначе воркеры
        одновременно отдавали бы разные «текущие» снимки.
        """
        self._revision_uncertain = False
        own = (revision, committed_at)
        value = json.dumps({
            "revision": revision,
            "committedAt": committed_at.isoformat() if committed_at is not None else None,
        }, separators=(",", ":"))
        try:
            if await self._redis.set(
                self._revision_key, value, px=self._revision_hold_ms, nx=True,
            ):
                return own
            adopted = await self.get_revision()
            return adopted if adopted is not None else own
        except (RedisError, OSError):
            self._errors += 1
            self._revision_uncertain = True
            return own

    async def begin_refresh(self, key: str) -> bool:
        token = uuid4().hex.encode("ascii")
        try:
            acquired = bool(await self._redis.set(
                self._lock_key(key), token, nx=True, px=self._lock_ms,
            ))
            if acquired:
                self._tokens[key] = token
                self._lock_acquired += 1
            else:
                self._lock_contended += 1
            return acquired
        except (RedisError, OSError):
            self._errors += 1
            return self._fallback_locks.begin_refresh(key)

    def is_stale(self, entry: Entry) -> bool:
        return entry.is_stale(time.time())

    async def end_refresh(self, key: str) -> None:
        token = self._tokens.pop(key, None)
        if token is not None:
            try:
                await self._redis.eval(self._RELEASE, 1, self._lock_key(key), token)
            except (RedisError, OSError):
                self._errors += 1
        self._fallback_locks.end_refresh(key)

    async def close(self) -> None:
        await self._redis.aclose()

    @property
    def stats(self) -> dict[str, int]:
        return {
            # Redis cardinality is intentionally not queried on each metrics
            # sample. This gauge means process-local entries and is always
            # zero for the shared backend.
            "entries": 0,
            "hits": self._hits,
            "misses": self._misses,
            "stale_hits": self._stale_hits,
            "refreshing": len(self._tokens),
            "redis_errors": self._errors,
            "refresh_acquired": self._lock_acquired,
            "refresh_contended": self._lock_contended,
        }


class InvalidationListener:
    """Слушает pg_notify и сбрасывает затронутые теги.

    TTL остаётся страховкой на случай потерянного уведомления: NOTIFY не
    доставляется процессу, который в этот момент не подключён.
    """

    def __init__(self, dsn: str, cache: Any) -> None:
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
                    await cache_call(self._cache.clear())
                    backoff = 1.0
                    async for notify in conn.notifies():
                        await self._apply(notify.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("слушатель инвалидации отключён, повтор через %.0f с", backoff,
                               exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _apply(self, payload: str) -> None:
        try:
            tags = frozenset(json.loads(payload).get("tags") or ())
        except (ValueError, AttributeError):
            logger.warning("неразбираемое уведомление инвалидации: %r", payload)
            await cache_call(self._cache.clear())
            return
        marked = await cache_call(self._cache.invalidate(tags))
        if marked:
            logger.info("помечено несвежими записей кэша: %d, теги %s", marked, sorted(tags))
