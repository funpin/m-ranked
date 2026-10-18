"""Чтение нашего локального HTTP API.

Запросы повторяют запросы сайта по умолчанию (те же параметры, без sort,
direction, group и types), чтобы ключ кэша ответов API совпал и бот не
вызывал новых чтений из базы. Одно соединение за раз.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from .render import PLATFORM_ORDER, default_count
from .words import Institution, TopQuery

USER_AGENT = "m-ranked-telegram-bot/1"
TIMEOUT_SECONDS = 30.0
PAGE_LIMIT = 50
INSTITUTIONS_TTL = 3600.0


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


class ApiSource:
    def __init__(self, client: httpx.AsyncClient,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._clock = clock
        self._institutions: list[Institution] | None = None
        self._institutions_at = 0.0

    async def _get(self, path: str, params: dict[str, Any], *, missing_ok: bool = False) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as error:
            raise SourceUnavailable(f"{path}: {type(error).__name__}") from None
        if missing_ok and response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SourceUnavailable(f"{path}: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise SourceUnavailable(f"{path}: ответ не JSON") from None

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
