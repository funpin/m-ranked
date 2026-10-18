"""Чтение нашего локального HTTP API.

Запросы повторяют запросы сайта по умолчанию (те же параметры, без sort,
direction, group и types), чтобы ключ кэша ответов API совпал и бот не
вызывал новых чтений из базы. Одно соединение за раз.

Свой кэш ответов (решение владельца 2026-10-18): кэш API держит ответ 10 минут,
а команды человеку нужны сразу. Копия моложе FRESH_SECONDS отдаётся всем без
запроса. На команду человека (person_request) годится и копия до часа: ответ
уходит из неё, а свежий запрос за той же копией идёт в фоне уже после ответа.
Запросов к API от этого не больше, чем без кэша: на каждую команду — не более
одного запроса на ключ, как и раньше. Фоновые проверки (выстрелил, накрутка)
старых копий не берут.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx

from .render import PLATFORM_ORDER, default_count
from .words import Institution, TopQuery

USER_AGENT = "m-ranked-telegram-bot/1"
TIMEOUT_SECONDS = 30.0
PAGE_LIMIT = 50
INSTITUTIONS_TTL = 3600.0
FRESH_SECONDS = 600.0  # как кэш ответов API (API_CACHE_TTL_SECONDS по умолчанию)
STALE_SECONDS = 3600.0  # решение владельца: на команду — копия не старше часа
# Ответ «Находок» — около 150 КБ JSON; храним байты: ≤ ~5 МБ при лимите службы 128 МБ.
CACHE_ENTRIES = 32

log = logging.getLogger(__name__)

Key = tuple[str, tuple[tuple[str, str], ...], bool]


class SourceUnavailable(Exception):
    """API недоступен или ответил ошибкой или не JSON. Текст не содержит URL."""


def make_client(base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        trust_env=False,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=1),
        headers={"User-Agent": USER_AGENT},
    )


@dataclass
class _PersonRequest:
    """Одна команда или нажатие человека: что вызвать перед первым холодным
    запросом («печатает…») и какие копии обновить после ответа."""
    on_cold: Callable[[], Awaitable[None]] | None
    stale: list[tuple["ApiSource", Key]] = field(default_factory=list)


_PERSON: ContextVar[_PersonRequest | None] = ContextVar("telegram_bot_person_request", default=None)


@contextmanager
def person_request(on_cold: Callable[[], Awaitable[None]] | None = None) -> Iterator[None]:
    """Запросы внутри — от человека: можно отвечать из копии до часа. На выходе
    (ответ уже отправлен) устаревшие копии обновляются в фоне."""
    request = _PersonRequest(on_cold)
    token = _PERSON.set(request)
    try:
        yield
    finally:
        _PERSON.reset(token)
        by_source: dict[int, tuple[ApiSource, list[Key]]] = {}
        for source, key in request.stale:
            by_source.setdefault(id(source), (source, []))[1].append(key)
        for source, keys in by_source.values():
            source.refresh_later(keys)


def _decode(content: bytes | None) -> Any:
    return None if content is None else json.loads(content)


class ApiSource:
    def __init__(self, client: httpx.AsyncClient,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._clock = clock
        self._institutions: list[Institution] | None = None
        self._institutions_at = 0.0
        # Ключ запроса → (когда получен, тело ответа; None — 404 при missing_ok).
        self._cache: OrderedDict[Key, tuple[float, bytes | None]] = OrderedDict()
        self._refreshing: set[Key] = set()
        self._tasks: set[asyncio.Task] = set()

    async def _fetch(self, path: str, params: dict[str, Any], missing_ok: bool) -> tuple[bytes | None, Any]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as error:
            raise SourceUnavailable(f"{path}: {type(error).__name__}") from None
        if missing_ok and response.status_code == 404:
            return None, None
        if response.status_code != 200:
            raise SourceUnavailable(f"{path}: HTTP {response.status_code}")
        try:
            return response.content, response.json()
        except ValueError:
            raise SourceUnavailable(f"{path}: ответ не JSON") from None

    def _store(self, key: Key, content: bytes | None) -> None:
        self._cache[key] = (self._clock(), content)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_ENTRIES:
            self._cache.popitem(last=False)

    async def _get(self, path: str, params: dict[str, Any], *, missing_ok: bool = False) -> Any:
        key: Key = (path, tuple(sorted((name, str(value)) for name, value in params.items())), missing_ok)
        request = _PERSON.get()
        entry = self._cache.get(key)
        if entry is not None:
            age = self._clock() - entry[0]
            if age < FRESH_SECONDS or (request is not None and age < STALE_SECONDS):
                self._cache.move_to_end(key)
                if age >= FRESH_SECONDS and request is not None:
                    request.stale.append((self, key))
                return _decode(entry[1])
        if request is not None and request.on_cold is not None:
            on_cold, request.on_cold = request.on_cold, None
            await on_cold()
        content, body = await self._fetch(path, params, missing_ok)
        self._store(key, content)
        return body

    def refresh_later(self, keys: list[Key]) -> None:
        """Обновить копии в фоне, по одной; ключ, который уже обновляется, — пропустить."""
        keys = [key for key in dict.fromkeys(keys) if key not in self._refreshing]
        if not keys:
            return
        self._refreshing.update(keys)
        task = asyncio.get_running_loop().create_task(self._refresh(keys))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _refresh(self, keys: list[Key]) -> None:
        try:
            for key in keys:
                path, params, missing_ok = key
                try:
                    content, _ = await self._fetch(path, dict(params), missing_ok)
                except Exception as error:  # noqa: BLE001 - копия остаётся до часа, следующая команда попробует снова
                    log.info("refresh %s: %s", path, type(error).__name__)
                    continue
                self._store(key, content)
        finally:
            self._refreshing.difference_update(keys)

    @staticmethod
    def _findings_params(institution: int | None, period: str) -> dict[str, Any]:
        if institution is None:
            return {"mode": "all", "period": period, "limit": PAGE_LIMIT}
        return {"mode": "institution", "institution": institution, "period": period,
                "limit": PAGE_LIMIT}

    async def findings(self, *, institution: int | None, platform: str, period: str,
                       suspicious: bool) -> dict:
        params = self._findings_params(institution, period)
        params.update(platform=platform, anomalies="include" if suspicious else "exclude")
        return await self._get("/api/v1/findings", params)

    async def anomalous(self, *, institution: int, period: str) -> dict:
        return await self._get("/api/v1/findings/anomalous",
                               self._findings_params(institution, period))

    async def dashboard(self) -> dict:
        return await self._get("/api/v1/compare/dashboard", {"period": "7d"})

    async def forecast(self) -> dict | None:
        return await self._get("/api/v1/rating/forecast", {}, missing_ok=True)

    async def institutions(self) -> list[Institution]:
        """Каталог вузов из ответа «Находок»; обновляется раз в час."""
        if (self._institutions is not None
                and self._clock() - self._institutions_at < INSTITUTIONS_TTL):
            return self._institutions
        body = await self.findings(institution=None, platform="all", period="7d", suspicious=False)
        self._institutions = [
            Institution(entry["legacyId"], entry.get("shortName"), entry["canonicalName"])
            for entry in body.get("institutions") or []
        ]
        self._institutions_at = self._clock()
        return self._institutions

    async def top_body(self, query: TopQuery, our_id: int | None) -> dict:
        """Ответ «Находок» под запрос /top.

        «Наши» и конкретный вуз: один запрос на все площадки, разбор по
        площадкам делает render. Если ответ усечён (hasMore) и на какой-то
        площадке постов меньше нужного, догружается именно она.
        """
        if query.who == "ours":
            if our_id is None:
                raise ValueError("не задан наш вуз")
            institution: int | None = our_id
        elif query.who == "institution":
            if query.institution is None:
                raise ValueError("не задан вуз")
            institution = query.institution
        else:
            institution = None
        body = await self.findings(institution=institution, platform=query.platform,
                                   period=query.period, suspicious=query.suspicious)
        if institution is None or query.platform != "all" or not body.get("hasMore"):
            return body
        wanted = default_count(query)
        items = list(body.get("items") or [])
        for platform in PLATFORM_ORDER:
            if sum(1 for item in items if item.get("platform") == platform) >= wanted:
                continue
            extra = await self.findings(institution=institution, platform=platform,
                                        period=query.period, suspicious=query.suspicious)
            items = [item for item in items if item.get("platform") != platform]
            items += [item for item in extra.get("items") or [] if item.get("platform") == platform]
        return {**body, "items": items}
