from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any

from collector_runtime.config import Settings

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


def next_delay(elapsed_seconds: float, interval_seconds: int) -> float:
    """Сколько ещё ждать до начала следующего слота.

    Пауза отсчитывается от начала обхода, а не от его конца. Иначе период
    равен «длительность цикла плюс интервал»: на проде пятиминутный шаг так
    растягивался до семи минут у Telegram и до одиннадцати у ВК — ровно на
    длительность самого обхода. Обход, не уложившийся в интервал, не ждёт.
    """
    return max(0.0, interval_seconds - elapsed_seconds)


def platform_offset(platform: Platform, interval_seconds: int) -> int:
    """Своя доля интервала у каждой площадки.

    Слоты разложены по epoch и одинаковы для всех, поэтому сборщики с общим
    интервалом начинали обход в одну и ту же секунду. Достаточно было
    перезапустить их вместе — а это делает любая выкатка, — и телеграм с MAX
    навсегда занимали одно ядро одновременно вместо того, чтобы чередоваться:
    пиковая нагрузка удваивалась, хотя работы было столько же. Смещение
    выводится из имени площадки, поэтому переживает перезапуск и одинаково у
    всех партиций одной площадки.
    """
    order = sorted(member.value for member in Platform)
    return interval_seconds * order.index(platform.value) // len(order)


def slot_delay(now_epoch: float, interval_seconds: int, offset_seconds: int) -> float:
    """Сколько ждать до ближайшего слота этой площадки.

    Обход, не уложившийся в свой интервал, не ждёт полного круга: следующий
    слот может быть уже через несколько секунд, и расписание само выправится.
    """
    position = (now_epoch - offset_seconds) % interval_seconds
    return float(interval_seconds - position) if position else 0.0


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
    repository: PostgresCollectorRepository | None = None
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
        repository = PostgresCollectorRepository(
            dsn,
            snapshot_heartbeat_hours=settings.publication_snapshot_heartbeat_hours,
        )
        repository.assert_schema_contract()
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
        offset = platform_offset(platform, interval_seconds)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - platform guard
                pass

        while not stop.is_set():
            began = time.monotonic()
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
            elapsed = time.monotonic() - began
            if elapsed >= interval_seconds:
                logger.warning(
                    "collector cycle overran its interval platform=%s seconds=%.1f interval=%s",
                    platform.value, elapsed, interval_seconds,
                )
            # Ждём не «столько-то от начала обхода», а до своего слота: иначе
            # площадки с общим интервалом, запущенные вместе, так и остаются
            # в одной фазе. Первый обход после запуска может оказаться короче
            # интервала — этим расписание и притягивается к своему слоту.
            remaining = min(
                next_delay(elapsed, interval_seconds),
                slot_delay(clock.now().timestamp(), interval_seconds, offset),
            )
            if remaining > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=remaining)
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
        # Пул соединений держит собственные потоки: без явного закрытия выход
        # ждал бы их до таймаута systemd.
        if repository is not None:
            repository.close()


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
