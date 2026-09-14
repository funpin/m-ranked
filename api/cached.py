"""Кэширование публичных ответов и валидаторы ETag."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .cache import ResponseCache
from .db import Database
from .providers import public_representation_version

PUBLIC_CACHE = "public, max-age=30, stale-while-revalidate=60"

REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"
PINNED_REVISION_SQL = (
    "SELECT id, committed_at FROM analytics.dataset_revision WHERE id=%(revision)s"
)


def _length_prefixed(digest: "hashlib._Hash", value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)


def cache_key(namespace: str, pinned_revision: int | None, query: dict[str, Any]) -> str:
    """Ключ живого ответа не зависит от номера ревизии.

    Прежде ревизия стояла в ключе. На проде она меняется раз в 1.9 секунды —
    её двигает каждая запись коллектора, — поэтому ключ обновлялся быстрее,
    чем приходил второй читатель, и кэш не отдал ни одного ответа: каждый
    просмотр страницы заново считал агрегаты. Свежесть держится сбросом по
    тегам из outbox и нижней границей возраста записи, а не номером в ключе.

    Закреплённый снимок — отдельный ответ и отдельный ключ: он намеренно
    описывает прошлое состояние и не должен вытеснять живой.
    """
    digest = hashlib.sha256()
    _length_prefixed(digest, public_representation_version())
    _length_prefixed(digest, namespace)
    for name in sorted(query):
        _length_prefixed(digest, name)
        _length_prefixed(digest, "" if query[name] is None else str(query[name]))
    scope = "live" if pinned_revision is None else f"r{pinned_revision}"
    return f"{namespace}:{scope}:{digest.hexdigest()}"


async def current_revision(db: Database) -> tuple[int, Any]:
    row = await db.fetch_one(REVISION_SQL)
    return (int(row["id"]), row["committed_at"]) if row else (0, None)


async def _resolve_revision(db: Database, pinned: int | None) -> tuple[int, Any]:
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
    return await current_revision(db)


async def serve(request: Request, namespace: str, query: dict[str, Any],
                tags: frozenset[str],
                build: Callable[[int, Any], Awaitable[dict[str, Any]]],
                pinned_revision: int | None = None) -> Response:
    """Отдаёт ответ из кэша или строит его, соблюдая If-None-Match."""
    db: Database = request.app.state.db
    cache: ResponseCache = request.app.state.cache

    # Номер ревизии нужен только для построения ответа, поэтому и читается
    # только при промахе: на попадании это был лишний заход в базу на каждый
    # запрос экрана.
    key = cache_key(namespace, pinned_revision, query)
    entry = cache.get(key)
    if entry is None:
        revision, committed_at = await _resolve_revision(db, pinned_revision)
        body = await build(revision, committed_at)
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)
        etag = '"' + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32] + '"'
        cache.put(key, payload, etag, tags)
    else:
        payload, etag = entry.value, entry.etag

    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})

    return Response(payload, media_type="application/json",
                    headers={"ETag": etag, "Cache-Control": PUBLIC_CACHE})


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    return any(candidate.strip().removeprefix("W/") == etag
               for candidate in header.split(","))
