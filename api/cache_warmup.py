"""Scheduled profile-B cache warmup through the ordinary public HTTP path.

Прогрев держит в кэше не только обзор и статистику, но и весь каталог:
карточку каждого аккаунта с её списком постов и соседними аккаунтами вуза, а
также страницы постов за последние часы. Карточки вузов и статистика постов
открывались медленно ровно потому, что их никто не грел: при малом числе
посетителей каждый первый просмотр платил полсекунды пересборки.

Прогрев ходит по тем же запросам, что и страницы Next, поэтому попадает ровно
в их ключи. Каждый запрос несёт заголовок с допустимым возрастом ответа: API
пересобирает только то, что старше, и пересобирает сразу, а не фоном. Так
частый проход почти ничего не стоит, а темп пересборки задаёт возраст, а не
частота прохода; параллельность ограничена, чтобы пересборка каталога не
занимала оба ядра Сервера 2 разом.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from .cache_metrics import atomic_write, render_warmup_metrics
from .cached import WARMUP_HEADER
from .config import Settings

logger = logging.getLogger(__name__)

# Столько же постов показывает карточка аккаунта и столько же точек истории
# запрашивает страница поста: иначе ключи прогрева не совпадут с живыми.
ACCOUNT_PUBLICATIONS_LIMIT = 100
INSTITUTION_ACCOUNTS_LIMIT = 100
PUBLICATION_HISTORY_LIMIT = 3000
OVERVIEW_PAGE_LIMIT = 200


def _path(template: str, *segments: Any, **query: Any) -> str:
    path = template.format(*(quote(str(segment), safe="") for segment in segments))
    present = {name: value for name, value in query.items() if value is not None}
    return f"{path}?{urlencode(present)}" if present else path


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class CacheWarmer:
    def __init__(
        self,
        client: Any,
        targets: tuple[str, ...],
        *,
        interval_seconds: float,
        metrics_file: Any = None,
        catalog: bool = False,
        recent_hours: int = 24,
        concurrency: int = 2,
    ) -> None:
        self.client = client
        self.targets = targets
        self.interval_seconds = interval_seconds
        self.metrics_file = metrics_file
        self.catalog = catalog
        self.recent_hours = recent_hours
        self._slots = asyncio.Semaphore(max(1, concurrency))
        self.succeeded = 0
        self.failed = 0
        self.last_completed_unixtime = 0.0
        self._round_succeeded = 0
        self._round_failed = 0
        self._round_seen: set[str] = set()

    async def _get(self, target: str, *, parse: bool = False,
                   absent_ok: bool = False) -> Any:
        """Один запрос прогрева. Отказ изолирован и только считается.

        За проход каждый адрес спрашивается один раз: у многих постов одна и
        та же карточка аккаунта.
        """
        if not parse:
            if target in self._round_seen:
                return None
            self._round_seen.add(target)
        async with self._slots:
            try:
                response = await self.client.get(target)
                if absent_ok and getattr(response, "status_code", None) == 404:
                    self._round_succeeded += 1
                    return None
                response.raise_for_status()
                self._round_succeeded += 1
                return response.json() if parse else None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._round_failed += 1
                status = getattr(getattr(error, "response", None), "status_code", None)
                logger.warning(
                    "cache warmup target failed: %s code=%s%s", target,
                    type(error).__name__, f" status={status}" if status else "",
                )
                return None

    async def _catalog_accounts(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = await self._get(
                _path("/api/v1/overview", limit=OVERVIEW_PAGE_LIMIT, cursor=cursor),
                parse=True,
            )
            if not isinstance(page, dict):
                return accounts
            for card in page.get("items") or ():
                for account in card.get("accounts") or ():
                    account_id = account.get("accountId")
                    if isinstance(account_id, str) and account_id not in seen:
                        seen.add(account_id)
                        accounts.append(account)
            cursor = page.get("nextCursor")
            if not cursor:
                return accounts

    async def _warm_account(self, account_id: str, institutions: set[int],
                            recent: list[str], horizon: datetime) -> None:
        """Карточка аккаунта так, как её собирает страница: сама карточка,
        её посты и соседние аккаунты того же вуза."""
        card = await self._get(_path("/api/v1/accounts/{}", account_id), parse=True)
        posts = await self._get(
            _path("/api/v1/accounts/{}/publications", account_id,
                  limit=ACCOUNT_PUBLICATIONS_LIMIT),
            parse=True,
        )
        institution = card.get("institutionLegacyId") if isinstance(card, dict) else None
        if isinstance(institution, int) and institution not in institutions:
            institutions.add(institution)
            await self._get(_path(
                "/api/v1/institutions/{}/accounts", institution,
                platform="all", limit=INSTITUTION_ACCOUNTS_LIMIT,
            ))
        if not isinstance(posts, dict):
            return
        for item in posts.get("items") or ():
            published = _parse_time(item.get("publishedAt"))
            publication_id = item.get("publicationId")
            if published is not None and published >= horizon and isinstance(publication_id, str):
                recent.append(publication_id)

    async def _warm_publication(self, publication_id: str) -> None:
        """Страница поста: история, анализ и то, что страница читает по той
        же ревизии, — карточка аккаунта по legacy id и соседние посты."""
        _meta, history, _analysis = await asyncio.gather(
            self._get(_path("/api/v1/publications/{}", publication_id)),
            self._get(
                _path("/api/v1/publications/{}/history", publication_id,
                      limit=PUBLICATION_HISTORY_LIMIT),
                parse=True,
            ),
            self._get(
                _path("/api/v1/publications/{}/anomaly-analysis", publication_id),
                absent_ok=True,
            ),
        )
        if not isinstance(history, dict):
            return
        publication = history.get("publication") or {}
        related: list[str] = []
        account_id = publication.get("accountLegacyId")
        account_type = publication.get("accountLegacyType")
        if account_id is not None and account_type:
            related.append(_path(
                "/api/v1/accounts/{}", account_id, legacyType=account_type,
            ))
        legacy_type = publication.get("legacyType")
        for neighbour in (history.get("previousLegacyId"), history.get("nextLegacyId")):
            if neighbour is not None and legacy_type:
                related.append(_path(
                    "/api/v1/publications/{}", neighbour, legacyType=legacy_type,
                ))
        await asyncio.gather(*(self._get(target) for target in related))

    async def run_once(self) -> tuple[int, int]:
        self._round_succeeded = 0
        self._round_failed = 0
        self._round_seen = set()
        await asyncio.gather(*(self._get(target) for target in self.targets))
        if self.catalog:
            horizon = datetime.now(timezone.utc) - timedelta(hours=self.recent_hours)
            institutions: set[int] = set()
            recent: list[str] = []
            accounts = await self._catalog_accounts()
            await asyncio.gather(*(
                self._warm_account(account["accountId"], institutions, recent, horizon)
                for account in accounts
            ))
            if self.recent_hours:
                await asyncio.gather(*(
                    self._warm_publication(publication_id)
                    for publication_id in dict.fromkeys(recent)
                ))
        succeeded, failed = self._round_succeeded, self._round_failed
        self.succeeded += succeeded
        self.failed += failed
        self.last_completed_unixtime = time.time()
        if self.metrics_file is not None:
            try:
                atomic_write(self.metrics_file, render_warmup_metrics(
                    succeeded=self.succeeded,
                    failed=self.failed,
                    last_completed_unixtime=self.last_completed_unixtime,
                ))
            except OSError:
                logger.warning("cache warmup metrics publish failed", exc_info=True)
        return succeeded, failed

    async def run_forever(self) -> None:
        while True:
            began = time.monotonic()
            succeeded, failed = await self.run_once()
            elapsed = time.monotonic() - began
            logger.info(
                "cache warmup round targets=%s failed=%s seconds=%.1f",
                succeeded + failed, failed, elapsed,
            )
            # Пауза отсчитывается от начала прохода: долгий проход не
            # растягивает период на свою длительность.
            await asyncio.sleep(max(1.0, self.interval_seconds - elapsed))


async def _run(once: bool) -> int:
    settings = Settings()
    if settings.deployment_profile != "b":
        logger.error("cache warmup is available only in API_DEPLOYMENT_PROFILE=b")
        return 2
    timeout = httpx.Timeout(
        connect=3,
        read=max(30.0, settings.statement_timeout_ms / 1000 + 5),
        write=30,
        pool=None,
    )
    async with httpx.AsyncClient(
        base_url=settings.cache_warmup_base_url,
        timeout=timeout,
        trust_env=False,
        headers={
            "user-agent": "m-ranked-cache-warmup/2",
            WARMUP_HEADER: str(settings.cache_warmup_max_age_seconds),
        },
        limits=httpx.Limits(max_connections=settings.cache_warmup_concurrency),
    ) as client:
        warmer = CacheWarmer(
            client, settings.cache_warmup_targets,
            interval_seconds=settings.cache_warmup_interval_seconds,
            metrics_file=settings.cache_warmup_metrics_file,
            catalog=settings.cache_warmup_catalog,
            recent_hours=settings.cache_warmup_recent_hours,
            concurrency=settings.cache_warmup_concurrency,
        )
        if once:
            _succeeded, failed = await warmer.run_once()
            return int(failed > 0)
        await warmer.run_forever()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Строка журнала httpx на каждый запрос прогрева — тысячи строк за проход.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(_run(args.once)))


if __name__ == "__main__":
    main()
