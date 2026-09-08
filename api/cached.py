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


def _length_prefixed(digest: "hashlib._Hash", value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)


def cache_key(namespace: str, revision: int, query: dict[str, Any]) -> str:
    """Ключ не содержит номера ревизии в отпечатке, но содержит его в самом ключе.

    Прежний кэш ключевался ревизией и обесценивался целиком при каждой записи:
    ревизия штамповалась в пиковом режиме раз в 3.5 секунды. Здесь ревизия
    остаётся частью ключа, но записи сбрасываются по тегам из outbox, а не
    сменой ревизии, поэтому переживают её.
    """
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


async def serve(request: Request, namespace: str, query: dict[str, Any],
                tags: frozenset[str],
                build: Callable[[int, Any], Awaitable[dict[str, Any]]]) -> Response:
    """Отдаёт ответ из кэша или строит его, соблюдая If-None-Match."""
    db: Database = request.app.state.db
    cache: ResponseCache = request.app.state.cache

    revision, committed_at = await current_revision(db)
    key = cache_key(namespace, revision, query)

    entry = cache.get(key)
    if entry is None:
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
