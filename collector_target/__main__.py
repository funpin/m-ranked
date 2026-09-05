from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Any

from app.config import Settings

from .auth import apply_platform_auth_file
from .coordinator import PollCycleCoordinator, SystemUtcClock
from .lease import PostgresAdvisoryLeaseProvider
from .model import Platform, RunStatus
from .normalize import sanitize_error_code
from .repository import PostgresCollectorRepository
from .runtime_adapters import build_runtime_adapter
from .tracking import validate_tracking_policy


logger = logging.getLogger("collector_target")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M-Ranked target PostgreSQL collector",
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=[platform.value for platform in Platform],
        help="one isolated platform runtime",
    )
    parser.add_argument("--partition", default="default")
    parser.add_argument("--collector-version", default=None)
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--account-concurrency", type=int, default=None)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    return parser


def _default_concurrency(platform: Platform, settings: Settings) -> int:
    return {
        Platform.TELEGRAM: settings.telegram_concurrency,
        Platform.VK: settings.vk_concurrency,
        Platform.MAX: 1,
        Platform.RUTUBE: settings.rutube_account_concurrency,
    }[platform]


def _default_interval(platform: Platform, settings: Settings) -> int:
    minutes = (
        settings.rutube_first_three_days_poll_interval_minutes
        if platform == Platform.RUTUBE else settings.poll_interval_minutes
    )
    return minutes * 60


def _scheduled_slot(now: datetime, interval_seconds: int) -> datetime:
    instant = now.astimezone(timezone.utc)
    epoch = int(instant.timestamp())
    return datetime.fromtimestamp(
        epoch - (epoch % interval_seconds), tz=timezone.utc,
    )


async def _close(adapter: Any, platform: Platform) -> None:
    close = getattr(adapter, "close", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception as error:
        logger.error(
            "collector close failed platform=%s code=%s",
            platform.value,
            sanitize_error_code(error),
        )


async def _run(args: argparse.Namespace) -> int:
    platform = Platform(args.platform)
    adapter: Any | None = None
    try:
        settings = Settings.load(args.env_file)
        settings = apply_platform_auth_file(
            settings,
            platform,
            os.getenv("COLLECTOR_PLATFORM_AUTH_FILE", "").strip() or None,
        )
        validate_tracking_policy(settings)
        dsn = (
            os.getenv("COLLECTOR_DATABASE_URL", "").strip()
            or os.getenv("DATABASE_URL", "").strip()
        )
        if not dsn:
            logger.error("collector startup failed code=MissingDatabaseUrl")
            return 2
        interval_seconds = args.interval_seconds or int(
            os.getenv("COLLECTOR_POLL_INTERVAL_SECONDS", "0") or 0
        ) or _default_interval(platform, settings)
        account_concurrency = args.account_concurrency or _default_concurrency(
            platform, settings,
        )
        if interval_seconds < 1 or account_concurrency < 1:
            logger.error("collector startup failed code=InvalidRuntimeLimits")
            return 2
        collector_version = (
            args.collector_version
            or os.getenv("COLLECTOR_VERSION", "").strip()
            or "target-v1"
        )
        clock = SystemUtcClock()
        repository = PostgresCollectorRepository(dsn)
        lease_provider = PostgresAdvisoryLeaseProvider(dsn)
        adapter = build_runtime_adapter(platform, settings, clock, repository)
        coordinator = PollCycleCoordinator(
            platform=platform,
            adapter=adapter,
            repository=repository,
            lease_provider=lease_provider,
            collector_version=collector_version,
            partition_key=args.partition,
            account_concurrency=account_concurrency,
            clock=clock,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - platform guard
                pass

        while not stop.is_set():
            scheduled_at = repository.resumable_scheduled_at(
                platform, args.partition, collector_version,
            ) or _scheduled_slot(clock.now(), interval_seconds)
            summary = await coordinator.run(scheduled_at)
            logger.info(
                "collector cycle completed platform=%s run=%s status=%s accounts=%s errors=%s",
                platform.value,
                summary.run_id,
                summary.status.value,
                summary.account_count,
                summary.error_count,
            )
            if args.once:
                return 1 if summary.status == RunStatus.FAILED else 0
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
        return 0
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.error(
            "collector process failed platform=%s code=%s",
            platform.value,
            sanitize_error_code(error),
        )
        return 1
    finally:
        if adapter is not None:
            await _close(adapter, platform)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
