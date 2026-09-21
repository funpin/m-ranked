"""Кэширование публичных ответов и валидаторы ETag."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import Response

from .cache import cache_call
from .db import Database
from .providers import public_representation_version

logger = logging.getLogger(__name__)

PUBLIC_CACHE = "public, max-age=30, stale-while-revalidate=60"

# Задачи пересчёта держим за ссылку: без неё сборщик мусора вправе забрать
# задачу до того, как она доработает.
_REFRESHING: set[asyncio.Task[None]] = set()

REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"
PINNED_REVISION_SQL = (
    "SELECT id, committed_at FROM analytics.dataset_revision WHERE id=%(revision)s"
)


def _length_prefixed(digest: "hashlib._Hash", value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)


def cache_key(namespace: str, revision: int, query: dict[str, Any]) -> str:
    """Revision-scoped opaque key shared by live requests and warmup."""
    digest = hashlib.sha256()
    _length_prefixed(digest, public_representation_version())
    _length_prefixed(digest, namespace)
    for name in sorted(query):
        _length_prefixed(digest, name)
        _length_prefixed(digest, "" if query[name] is None else str(query[name]))
    return f"{namespace}:r{revision}:{digest.hexdigest()}"


async def current_revision(db: Database) -> tuple[int, Any]:
    row = await db.fetch_one(REVISION_SQL)
    return (int(row["id"]), row["committed_at"]) if row else (0, None)


async def _resolve_revision(
    db: Database, cache: Any, pinned: int | None,
) -> tuple[int, Any]:
    """Ревизия для ответа: закреплённая клиентом или текущая.

    Экран публикации собирается из четырёх запросов, а ревизия набора данных
    на проде меняется каждые две секунды — её двигает каждая запись коллектора.
    Без закрепления примерно каждый тринадцатый просмотр складывал страницу из
    двух разных снимков. Несуществующая ревизия не ошибка: она могла быть
    вычищена обслуживанием, и тогда ответ отдаётся по текущей, а клиент увидит
    расхождение в поле datasetRevision и решит сам.
    """
    if pinned is not None:
        row = await db.fetch_one(PINNED_REVISION_SQL, {"revision": pinned})
        if row is not None:
            return int(row["id"]), row["committed_at"]
    else:
        cached = await cache_call(cache.get_revision())
        if cached is not None:
            return cached
    revision = await current_revision(db)
    if pinned is None:
        await cache_call(cache.set_revision(*revision))
    return revision


async def serve(request: Request, namespace: str, query: dict[str, Any],
                tags: frozenset[str],
                build: Callable[[int, Any], Awaitable[dict[str, Any]]],
                pinned_revision: int | None = None) -> Response:
    """Отдаёт ответ из кэша или строит его, соблюдая If-None-Match."""
    db: Database = request.app.state.db
    cache: Any = request.app.state.cache

    revision, committed_at = await _resolve_revision(db, cache, pinned_revision)
    key = cache_key(namespace, revision, query)
    entry = await cache_call(cache.get(key))
    if entry is None:
        if await cache_call(cache.begin_refresh(key)):
            try:
                payload, etag = await _rebuild(
                    cache, key, tags, build, revision, committed_at,
                )
            finally:
                await cache_call(cache.end_refresh(key))
        else:
            # Another process is rebuilding this exact revision. Wait only up
            # to the query budget, then fail open through the database.
            deadline = time.monotonic() + min(
                30.0,
                max(1.0, request.app.state.settings.statement_timeout_ms / 1000 + 1),
            )
            while time.monotonic() < deadline:
                await asyncio.sleep(0.02)
                entry = await cache_call(cache.get(key))
                if entry is not None:
                    break
            if entry is None:
                payload, etag = await _rebuild(
                    cache, key, tags, build, revision, committed_at,
                )
            else:
                payload, etag = entry.value, entry.etag
    else:
        payload, etag = entry.value, entry.etag
        # Несвежий ответ отдаётся сразу, а пересчёт идёт фоном. Иначе ровно
        # один посетитель раз в окно ждал перестроения ответа: на проде это
        # 730–1024 мс против полутора миллисекунд у остальных.
        if await cache_call(cache.is_stale(entry)) and await cache_call(cache.begin_refresh(key)):
            task = asyncio.create_task(
                _refresh(cache, key, tags, build, revision, committed_at),
                name=f"cache-refresh:{namespace}")
            _REFRESHING.add(task)
            task.add_done_callback(_REFRESHING.discard)

    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})

    return Response(payload, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})


async def _rebuild(cache: Any, key: str, tags: frozenset[str],
                   build: Callable[[int, Any], Awaitable[dict[str, Any]]],
                   revision: int, committed_at: Any) -> tuple[str, str]:
    """Строит представление заново и кладёт его в кэш."""
    body = await build(revision, committed_at)
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)
    etag = '"' + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32] + '"'
    await cache_call(cache.put(key, payload, etag, tags))
    return payload, etag


async def _refresh(cache: Any, key: str, tags: frozenset[str],
                   build: Callable[[int, Any], Awaitable[dict[str, Any]]],
                   revision: int, committed_at: Any) -> None:
    """Фоновый пересчёт. Отказ оставляет прежнюю запись дожить свой срок."""
    try:
        await _rebuild(cache, key, tags, build, revision, committed_at)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("фоновый пересчёт ответа не удался: %s", key, exc_info=True)
    finally:
        await cache_call(cache.end_refresh(key))


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    return any(candidate.strip().removeprefix("W/") == etag
               for candidate in header.split(","))
