"""Scheduled profile-B cache warmup through the ordinary public HTTP path."""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

import httpx

from .config import Settings
from .cache_metrics import atomic_write, render_warmup_metrics

logger = logging.getLogger(__name__)


class CacheWarmer:
    def __init__(
        self,
        client: Any,
        targets: tuple[str, ...],
        *,
        interval_seconds: float,
        metrics_file: Any = None,
    ) -> None:
        self.client = client
        self.targets = targets
        self.interval_seconds = interval_seconds
        self.metrics_file = metrics_file
        self.succeeded = 0
        self.failed = 0
        self.last_completed_unixtime = 0.0

    async def run_once(self) -> tuple[int, int]:
        succeeded = 0
        failed = 0
        for target in self.targets:
            try:
                response = await self.client.get(target)
                response.raise_for_status()
                succeeded += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
                logger.warning("cache warmup target failed: %s", target)
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
            await self.run_once()
            await asyncio.sleep(self.interval_seconds)


async def _run(once: bool) -> int:
    settings = Settings()
    if settings.deployment_profile != "b":
        logger.error("cache warmup is available only in API_DEPLOYMENT_PROFILE=b")
        return 2
    timeout = httpx.Timeout(
        connect=3,
        read=max(30.0, settings.statement_timeout_ms / 1000 + 5),
        write=30,
        pool=3,
    )
    async with httpx.AsyncClient(
        base_url=settings.cache_warmup_base_url,
        timeout=timeout,
        trust_env=False,
        headers={"user-agent": "m-ranked-cache-warmup/1"},
    ) as client:
        warmer = CacheWarmer(
            client, settings.cache_warmup_targets,
            interval_seconds=settings.cache_warmup_interval_seconds,
            metrics_file=settings.cache_warmup_metrics_file,
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
    raise SystemExit(asyncio.run(_run(args.once)))


if __name__ == "__main__":
    main()
