"""Кэширование публичных ответов и валидаторы ETag."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import Request
from fastapi.responses import Response

from .cache import Entry, cache_call
from .db import Database
from .providers import public_representation_version

logger = logging.getLogger(__name__)

PUBLIC_CACHE = "public, max-age=30, stale-while-revalidate=60"

# Прогрев просит пересобрать ответ, если тот старше указанного числа секунд,
# и пересобрать сразу, а не фоном: так он сам держит темп и не выпускает
# сотни пересчётов разом. Моложе порога свежести пересборку не вызвать ничем,
# поэтому посторонний с этим заголовком не заставит API работать чаще, чем
# его заставляют обычные посетители.
WARMUP_HEADER = "x-m-ranked-cache-warmup"

# Задачи пересчёта держим за ссылку: без неё сборщик мусора вправе забрать
# задачу до того, как она доработает. Их же число ограничивает фоновую
# нагрузку процесса.
_REFRESHING: set[asyncio.Task[None]] = set()
DEFAULT_REFRESH_CONCURRENCY = 2

REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"
PINNED_REVISION_SQL = (
    "SELECT id, committed_at FROM analytics.dataset_revision WHERE id=%(revision)s"
)

Builder = Callable[[int, Any], Awaitable[dict[str, Any]]]
# Другие запросы, на которые годится тот же ответ. Карточку аккаунта
# спрашивают и по UUID, и по legacy id: первую — страница аккаунта, второе —
# страница поста. Без псевдонимов прогрев и пересчёт собирали её дважды.
Aliases = Callable[[dict[str, Any]], Iterable[dict[str, Any]]]


def _length_prefixed(digest: "hashlib._Hash", value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)


def cache_key(namespace: str, query: dict[str, Any]) -> str:
    """Ключ логического запроса, общий для живых запросов и прогрева.

    Номера ревизии в ключе нет: запись одна на запрос, а ревизия лежит в ней.
    Курсор страницы, если он есть, входит в запрос и уже несёт свою ревизию.
    """
    digest = hashlib.sha256()
    _length_prefixed(digest, public_representation_version())
    _length_prefixed(digest, namespace)
    for name in sorted(query):
        _length_prefixed(digest, name)
        _length_prefixed(digest, "" if query[name] is None else str(query[name]))
    return f"{namespace}:{digest.hexdigest()}"


async def current_revision(db: Database) -> tuple[int, Any]:
    row = await db.fetch_one(REVISION_SQL)
    return (int(row["id"]), row["committed_at"]) if row else (0, None)


async def published_revision(db: Database, cache: Any) -> tuple[int, Any]:
    """Текущая ревизия, удерживаемая окном кэша.

    На Сервере 2 ревизия сменяется каждые полторы секунды. Пока каждый
    пересчёт брал самую свежую, два ответа одной страницы почти никогда не
    совпадали по снимку. Окно удержания делает «текущую» ревизию общей для
    всех пересчётов, воркеров и для /revision, по которой ключует ответы Next.
    """
    cached = await cache_call(cache.get_revision())
    if cached is not None:
        return cached
    revision = await current_revision(db)
    adopted = await cache_call(cache.set_revision(*revision))
    return adopted if isinstance(adopted, tuple) else revision


async def _resolve_revision(
    db: Database, cache: Any, pinned: int | None,
) -> tuple[int, Any]:
    """Ревизия для пересборки: закреплённая клиентом или опубликованная.

    Несуществующая закреплённая ревизия не ошибка: она могла быть вычищена
    обслуживанием, и тогда ответ собирается по текущей, а клиент увидит
    расхождение в поле datasetRevision и решит сам.
    """
    if pinned is not None:
        row = await db.fetch_one(PINNED_REVISION_SQL, {"revision": pinned})
        if row is not None:
            return int(row["id"]), row["committed_at"]
    return await published_revision(db, cache)


def _warmup_age(request: Request, cache: Any) -> float | None:
    raw = request.headers.get(WARMUP_HEADER)
    if raw is None:
        return None
    try:
        requested = float(raw)
    except ValueError:
        return None
    return max(requested, float(getattr(cache, "fresh_seconds", 0.0)))


async def serve(request: Request, namespace: str, query: dict[str, Any],
                tags: frozenset[str], build: Builder,
                pinned_revision: int | None = None,
                aliases: Aliases | None = None) -> Response:
    """Отдаёт ответ из кэша или строит его, соблюдая If-None-Match.

    Закреплённая ревизия нужна, чтобы собрать ответ по тому же снимку, что и
    соседние запросы страницы. Готовая запись отдаётся и по другой ревизии:
    расхождение в минуту экран не меняет, а пересборка тяжёлой карточки на
    каждый просмотр поста стоила полсекунды. Точная ревизия соблюдается там,
    где без неё нельзя, — в продолжении списка по курсору: курсор входит в
    ключ и сам несёт ревизию.
    """
    db: Database = request.app.state.db
    cache: Any = request.app.state.cache

    key = cache_key(namespace, query)
    store = _Store(cache, namespace, key, tags, aliases)
    entry: Entry | None = await cache_call(cache.get(key))
    warmup_age = _warmup_age(request, cache)
    if entry is not None:
        if warmup_age is not None:
            if cache.age(entry) >= warmup_age:
                entry = None
        elif cache.is_stale(entry):
            await _schedule_refresh(request, store, build)

    if entry is None:
        payload, etag = await _build_or_wait(
            request, db, store, build, pinned_revision, warmup_age,
        )
    else:
        payload, etag = entry.value, entry.etag

    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})

    return Response(payload, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})


async def _build_or_wait(request: Request, db: Database, store: "_Store",
                         build: Builder, pinned: int | None,
                         warmup_age: float | None) -> tuple[str, str]:
    """Собирает ответ сам или дожидается того, кто уже собирает."""
    cache, key = store.cache, store.key
    revision, committed_at = await _resolve_revision(db, cache, pinned)
    if await cache_call(cache.begin_refresh(key)):
        try:
            return await _rebuild(store, build, revision, committed_at)
        finally:
            await cache_call(cache.end_refresh(key))

    def acceptable(candidate: Entry | None) -> bool:
        return candidate is not None and (
            warmup_age is None or cache.age(candidate) < warmup_age
        )

    # Тот же ответ уже собирает другой процесс. Ждём не дольше бюджета
    # запроса, потом собираем сами через базу.
    deadline = time.monotonic() + min(
        30.0,
        max(1.0, request.app.state.settings.statement_timeout_ms / 1000 + 1),
    )
    while time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        entry = await cache_call(cache.get(key))
        if acceptable(entry):
            return entry.value, entry.etag
    return await _rebuild(store, build, revision, committed_at)


async def _schedule_refresh(request: Request, store: "_Store", build: Builder) -> None:
    """Запускает фоновый пересчёт, если на него есть место.

    Число одновременных пересчётов ограничено: поисковый робот, прошедший по
    сотне несвежих страниц, иначе поднял бы сотню тяжёлых запросов разом.
    Без места пересчёт просто не начинается — запись останется несвежей, и
    его запустит следующий читатель или прогрев.
    """
    limit = getattr(
        request.app.state.settings, "cache_refresh_concurrency",
        DEFAULT_REFRESH_CONCURRENCY,
    )
    if len(_REFRESHING) >= limit:
        return
    if not await cache_call(store.cache.begin_refresh(store.key)):
        return
    task = asyncio.create_task(
        _refresh(request.app.state.db, store, build),
        name=f"cache-refresh:{store.namespace}",
    )
    _REFRESHING.add(task)
    task.add_done_callback(_REFRESHING.discard)


class _Store:
    """Куда класть собранный ответ: его ключ и ключи его псевдонимов."""

    __slots__ = ("cache", "namespace", "key", "tags", "aliases")

    def __init__(self, cache: Any, namespace: str, key: str,
                 tags: frozenset[str], aliases: Aliases | None) -> None:
        self.cache = cache
        self.namespace = namespace
        self.key = key
        self.tags = tags
        self.aliases = aliases

    async def put(self, body: dict[str, Any], payload: str, etag: str,
                  revision: int) -> None:
        keys = [self.key]
        if self.aliases is not None:
            for alias in self.aliases(body):
                alias_key = cache_key(self.namespace, alias)
                if alias_key not in keys:
                    keys.append(alias_key)
        for key in keys:
            await cache_call(self.cache.put(key, payload, etag, self.tags, revision))


async def _rebuild(store: _Store, build: Builder,
                   revision: int, committed_at: Any) -> tuple[str, str]:
    """Строит представление заново и кладёт его в кэш."""
    body = await build(revision, committed_at)
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)
    etag = '"' + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32] + '"'
    await store.put(body, payload, etag, revision)
    return payload, etag


async def _refresh(db: Database, store: _Store, build: Builder) -> None:
    """Фоновый пересчёт по опубликованной ревизии.

    Отказ оставляет прежнюю запись дожить свой срок.
    """
    try:
        revision, committed_at = await published_revision(db, store.cache)
        await _rebuild(store, build, revision, committed_at)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("фоновый пересчёт ответа не удался: %s", store.key, exc_info=True)
    finally:
        await cache_call(store.cache.end_refresh(store.key))


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    return any(candidate.strip().removeprefix("W/") == etag
               for candidate in header.split(","))
