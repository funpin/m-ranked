from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from collector_runtime.config import Settings

from .auth import apply_platform_auth_file
from .coordinator import (
    PollCycleCoordinator,
    SystemUtcClock,
    ensure_runtime_release_available,
)
from .lease import PostgresAdvisoryLeaseProvider
from .model import Platform, RunStatus, utc
from .normalize import sanitize_error_code
from .phase import (
    PhaseLease,
    PhasePolicy,
    PhaseRequest,
    PhaseScheduler,
    PostgresPersistGuard,
    PostgresPhaseArbiter,
    due_slot,
)
from .placement import Placement, parse_membership
from .platforms.registry import build_adapter
from .retention import (
    RetentionPolicy,
    WorkingSetRetention,
    disk_state,
)
from .repository import PostgresCollectorRepository
from .tracking import validate_tracking_policy
from .transfer import (
    HttpsMtlsTransport,
    InProcessTransport,
    PostgresDataAdapter,
    PostgresTransferProducer,
)


logger = logging.getLogger("collector_target")

TRANSIENT_BACKOFF_MIN_SECONDS = 2.0
TRANSIENT_BACKOFF_MAX_SECONDS = 30.0


def is_transient(error: BaseException) -> bool:
    """Сбой, который проходит сам: база занята, перезапущена или недоступна.

    Сюда же относится потеря глобальной аренды фазы: её держит соединение, и
    обрыв соединения снимает замок. Всё остальное — ошибка кода или данных, и
    её честнее отдать systemd, чем крутить цикл вхолостую.
    """
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    if isinstance(error, RuntimeError) and str(error) == "GlobalPhaseLeaseLost":
        return True
    try:
        import psycopg
    except ImportError:  # pragma: no cover - packaging guard
        return False
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))


def _log_startup(
    platform: Platform,
    partition: str,
    collector_version: str,
    schedule_mode: str,
    deployment_profile: str,
    transfer_mode: str,
    *,
    interval_seconds: int | None = None,
    cycle_deadline_seconds: int | None = None,
    collect_concurrency: int | None = None,
) -> None:
    logger.info(
        "collector started platform=%s partition=%s collector_version=%s "
        "schedule_mode=%s deployment_profile=%s transfer_mode=%s",
        platform.value,
        partition,
        collector_version,
        schedule_mode,
        deployment_profile,
        transfer_mode,
    )
    # Две настройки умеют молча стоить замеров, поэтому о них говорится на
    # старте, а не только в документации.
    if (
        interval_seconds is not None
        and cycle_deadline_seconds is not None
        and cycle_deadline_seconds > interval_seconds
    ):
        logger.warning(
            "collector cycle deadline exceeds its interval platform=%s "
            "interval_seconds=%s cycle_deadline_seconds=%s: медленный цикл "
            "перешагнёт свой слот, и планировщик схлопнет пропущенные",
            platform.value, interval_seconds, cycle_deadline_seconds,
        )
    if (
        deployment_profile == "b"
        and collect_concurrency is not None
        and collect_concurrency < len(Platform)
    ):
        logger.warning(
            "collector collect concurrency is below the platform count "
            "platform=%s collect_concurrency=%s platforms=%s: сбор площадок "
            "встанет в очередь, циклы перерастут слоты и ряд замеров получит "
            "провалы",
            platform.value, collect_concurrency, len(Platform),
        )


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


def _poll_interval_seconds(
    platform: Platform,
    settings: Settings,
    cli_override: int | None = None,
) -> int:
    """Resolve a platform interval without letting a legacy global override Rutube.

    ``COLLECTOR_POLL_INTERVAL_SECONDS`` predates the isolated platform units and
    is retained for the three five-minute collectors. Rutube has a deliberately
    slower provider policy, so changing it now requires the explicit platform
    variable (or the CLI flag) instead of an accidental value in common.env.
    """
    def positive(value: int, source: str) -> int:
        if value <= 0:
            raise ValueError(f"{source} must be a positive integer")
        return value

    if cli_override is not None:
        return positive(cli_override, "--interval-seconds")
    specific_name = f"COLLECTOR_{platform.value.upper()}_POLL_INTERVAL_SECONDS"
    specific = os.getenv(specific_name, "").strip()
    if specific:
        return positive(int(specific), specific_name)
    legacy = os.getenv("COLLECTOR_POLL_INTERVAL_SECONDS", "").strip()
    if legacy and platform != Platform.RUTUBE:
        return positive(int(legacy), "COLLECTOR_POLL_INTERVAL_SECONDS")
    return positive(_default_interval(platform, settings), "platform default interval")


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


def _schedule_mode(settings: Settings) -> str:
    mode = settings.collector_schedule_mode.strip().lower()
    if mode not in {"legacy", "phased", "shadow"}:
        raise ValueError("COLLECTOR_SCHEDULE_MODE must be legacy, phased or shadow")
    return mode


def _cycle_deadline(platform: Platform, settings: Settings) -> int:
    value = {
        Platform.TELEGRAM: settings.collector_telegram_cycle_deadline_seconds,
        Platform.VK: settings.collector_vk_cycle_deadline_seconds,
        Platform.MAX: settings.collector_max_cycle_deadline_seconds,
        Platform.RUTUBE: settings.collector_rutube_cycle_deadline_seconds,
    }[platform]
    if value < 1:
        raise ValueError("platform cycle deadline must be positive")
    return value


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    if seconds <= 0:
        return stop.is_set()
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


async def _run_bounded_cycle(
    coordinator: PollCycleCoordinator,
    scheduled_at: datetime,
    *,
    stop: asyncio.Event,
    lease: PhaseLease,
    deadline_seconds: int,
    shutdown_grace_seconds: int,
    lease_probe_seconds: float,
) -> tuple[Any, bool]:
    """Run one cycle with deadline, lease-loss and bounded-stop cancellation."""
    cycle = asyncio.create_task(coordinator.run(scheduled_at))
    stopping = asyncio.create_task(stop.wait())

    async def wait_for_lease_loss() -> None:
        while True:
            await asyncio.sleep(max(0.25, min(5.0, lease_probe_seconds)))
            if not await asyncio.to_thread(lease.alive):
                return

    lease_lost = asyncio.create_task(wait_for_lease_loss())
    forced = False
    try:
        done, _pending = await asyncio.wait(
            {cycle, stopping, lease_lost},
            timeout=deadline_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cycle in done:
            return await cycle, forced
        if lease_lost in done:
            cycle.cancel()
            await asyncio.gather(cycle, return_exceptions=True)
            raise RuntimeError("GlobalPhaseLeaseLost")
        if stopping in done:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(cycle), timeout=shutdown_grace_seconds,
                ), forced
            except TimeoutError:
                forced = True
                cycle.cancel()
                await asyncio.gather(cycle, return_exceptions=True)
                raise asyncio.CancelledError
        cycle.cancel()
        await asyncio.gather(cycle, return_exceptions=True)
        raise TimeoutError("CollectorCycleDeadlineExceeded")
    finally:
        stopping.cancel()
        lease_lost.cancel()
        await asyncio.gather(stopping, lease_lost, return_exceptions=True)


def _maintain_working_set(
    retention: WorkingSetRetention,
    metrics: Any,
    disk_path: str,
) -> None:
    """Observe disk and release acknowledged months, outside any collect phase.

    Retention runs between cycles on purpose: it takes ACCESS EXCLUSIVE on the
    observation tables, and a collect phase holding the global lease must never
    wait behind housekeeping.
    """
    try:
        state = disk_state(disk_path)
        metrics.disk(used_percent=state.used_percent, free_bytes=state.free_bytes)
        if state.pauses_collection:
            logger.error(
                "collector disk watermark reached path=%s used_percent=%.1f "
                "threshold=%s",
                disk_path, state.used_percent, state.threshold,
            )
        elif state.warns:
            logger.warning(
                "collector disk watermark reached path=%s used_percent=%.1f "
                "threshold=%s",
                disk_path, state.used_percent, state.threshold,
            )
    except OSError as error:
        logger.warning(
            "collector disk probe failed code=%s", sanitize_error_code(error),
        )
    if not retention.policy.enabled:
        return
    try:
        retention.run()
    except Exception as error:
        # Housekeeping must never take a collector down: the cycle that
        # follows is worth more than the space this would have freed.
        logger.error(
            "working set retention skipped code=%s", sanitize_error_code(error),
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
    phase_arbiter: PostgresPhaseArbiter | None = None
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
        interval_seconds = _poll_interval_seconds(
            platform, settings, args.interval_seconds,
        )
        schedule_mode = _schedule_mode(settings)
        account_concurrency = args.account_concurrency or _default_concurrency(
            platform, settings,
        )
        if (
            interval_seconds < 1
            or account_concurrency < 1
            or settings.collector_phase_max_wait_seconds < 1
            or settings.collector_phase_retry_seconds <= 0
            or settings.collector_phase_request_stale_seconds < 1
            or settings.collector_shutdown_grace_seconds < 1
        ):
            logger.error("collector startup failed code=InvalidRuntimeLimits")
            return 2
        collector_version = (
            args.collector_version
            or os.getenv("COLLECTOR_VERSION", "").strip()
            or "target-v1"
        )
        clock = SystemUtcClock()
        deployment_profile = settings.collector_deployment_profile.strip().lower()
        transfer_mode = settings.collector_transfer_mode.strip().lower()
        producer_id = (
            f"{settings.collector_transfer_producer_id}/{args.partition}"
            if transfer_mode != "disabled" else None
        )
        repository = PostgresCollectorRepository(
            dsn,
            snapshot_heartbeat_hours=settings.publication_snapshot_heartbeat_hours,
            transfer_producer_id=producer_id,
            deployment_profile=deployment_profile,
        )
        repository.assert_schema_contract()
        lease_provider = PostgresAdvisoryLeaseProvider(dsn)
        adapter = build_adapter(platform, settings, clock, repository)
        # Размещение строится один раз при старте. Список участников приходит
        # с Сервера 2 конфигурацией; при его отсутствии хост считает себя
        # единственным и собирает всё, как раньше.
        placement = (
            Placement(
                parse_membership(settings.collector_membership),
                {
                    Platform.TELEGRAM: settings.collector_replication_telegram,
                    Platform.VK: settings.collector_replication_vk,
                    Platform.MAX: settings.collector_replication_max,
                    Platform.RUTUBE: settings.collector_replication_rutube,
                },
            )
            if settings.collector_membership else None
        )
        if placement is not None:
            for uncovered in placement.uncovered():
                logger.warning(
                    "collector placement leaves a platform uncovered platform=%s",
                    uncovered.value,
                )
            for short in placement.underprovisioned():
                logger.warning(
                    "collector placement runs below its replication factor "
                    "platform=%s effective=%s requested=%s",
                    short.value, placement.effective_replication(short),
                    placement.replication[short],
                )
        persist_guard = (
            PostgresPersistGuard(
                lambda: PostgresAdvisoryLeaseProvider(dsn)._factory(),
                wait_seconds=settings.collector_persist_wait_seconds,
            )
            if settings.collector_collect_concurrency > 1 else None
        )
        coordinator = PollCycleCoordinator(
            platform=platform,
            adapter=adapter,
            repository=repository,
            lease_provider=lease_provider,
            collector_version=collector_version,
            partition_key=args.partition,
            account_concurrency=account_concurrency,
            clock=clock,
            persist_guard=persist_guard,
            placement=placement,
            server_id=settings.collector_server_id if placement else None,
        )
        if transfer_mode == "in-process":
            data_adapter = PostgresDataAdapter(repository)
            repository.configure_transfer_sender(PostgresTransferProducer(
                repository, InProcessTransport(data_adapter), coordinator.metrics,
            ))
        elif transfer_mode == "https-mtls":
            # Сборщик только запечатывает пачку в outbox той же транзакцией,
            # что и запись, а доставляет её служба m-ranked-target-transfer-
            # sender. Прежде конверт уходил отсюда же, сразу после записи и
            # под общим замком записи: сетевой вызов на Сервер 2 с новым
            # TLS-рукопожатием держал замок, три других сборщика ждали его по
            # 5–14 секунд на аккаунт, и циклы перерастали свои слоты. Настройки
            # транспорта всё равно проверяются на старте, чтобы ошибка в них
            # была видна сразу, а не только в журнале отправителя.
            HttpsMtlsTransport(
                settings.collector_transfer_https_endpoint or "",
                certificate=settings.collector_transfer_client_certificate or "",
                private_key=settings.collector_transfer_private_key or "",
                ca_bundle=settings.collector_transfer_ca_bundle or "",
            )
        retention = WorkingSetRetention(
            repository,
            RetentionPolicy(
                mode=settings.collector_working_set_retention.strip().lower(),
                track_post_for_hours=settings.track_post_for_hours,
                months_per_run=settings.collector_working_set_months_per_run,
            ),
            clock=clock,
            metrics=coordinator.metrics,
        )
        coordinator.metrics.schedule_mode(platform, schedule_mode)
        coordinator.metrics.deployment_profile(platform, deployment_profile)
        _log_startup(
            platform, args.partition, collector_version, schedule_mode,
            deployment_profile, transfer_mode,
            interval_seconds=interval_seconds,
            cycle_deadline_seconds=_cycle_deadline(platform, settings),
            collect_concurrency=settings.collector_collect_concurrency,
        )
        offset = platform_offset(platform, interval_seconds)
        policy = PhasePolicy(
            platform,
            interval_seconds,
            offset,
            _cycle_deadline(platform, settings),
        )
        phase_arbiter = PostgresPhaseArbiter(
            dsn, collect_slots=settings.collector_collect_concurrency,
        )
        phase_scheduler = PhaseScheduler(
            phase_arbiter,
            max_wait_seconds=settings.collector_phase_max_wait_seconds,
            retry_seconds=settings.collector_phase_retry_seconds,
            request_stale_seconds=settings.collector_phase_request_stale_seconds,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - platform guard
                pass

        if schedule_mode == "legacy":
            while not stop.is_set():
                ensure_runtime_release_available()
                began = time.monotonic()
                scheduled_at = repository.resumable_scheduled_at(
                    platform, args.partition, collector_version,
                ) or _scheduled_slot(clock.now(), interval_seconds)
                summary = await coordinator.run(scheduled_at)
                logger.info(
                    "collector cycle completed platform=%s partition=%s run=%s "
                    "scheduled_at=%s phase=cycle status=%s collector_version=%s "
                    "accounts=%s errors=%s mode=legacy",
                    platform.value,
                    args.partition,
                    summary.run_id,
                    scheduled_at.isoformat(),
                    summary.status.value,
                    collector_version,
                    summary.account_count,
                    summary.error_count,
                )
                if args.once:
                    return 1 if summary.status == RunStatus.FAILED else 0
                elapsed = time.monotonic() - began
                if elapsed >= interval_seconds:
                    logger.warning(
                        "collector cycle overran platform=%s partition=%s run=%s "
                        "scheduled_at=%s phase=cycle status=overrun collector_version=%s "
                        "seconds=%.1f interval=%s",
                        platform.value, args.partition, summary.run_id,
                        scheduled_at.isoformat(), collector_version,
                        elapsed, interval_seconds,
                    )
                remaining = min(
                    next_delay(elapsed, interval_seconds),
                    slot_delay(clock.now().timestamp(), interval_seconds, offset),
                )
                if await _wait_or_stop(stop, remaining):
                    break
            return 0

        pending_phase: tuple[
            datetime, int, datetime, datetime | None, datetime | None,
        ] | None = None
        backoff = TRANSIENT_BACKOFF_MIN_SECONDS
        while not stop.is_set():
            try:
                ensure_runtime_release_available()
                now = utc(clock.now(), "clock.now")
                if pending_phase is not None:
                    (
                        scheduled_at, coalesced_slots, next_due,
                        resumable, last_completed,
                    ) = pending_phase
                else:
                    resumable = repository.resumable_scheduled_at(
                        platform, args.partition, collector_version,
                    )
                    last_completed = repository.last_completed_scheduled_at(
                        platform, args.partition, collector_version,
                    )
                    if resumable is not None:
                        scheduled_at = resumable
                        coalesced_slots = 0
                        next_due = scheduled_at + timedelta(seconds=interval_seconds)
                    else:
                        scheduled_at, coalesced_slots, next_due = due_slot(
                            now, policy, last_completed,
                        )
                        if scheduled_at is None:
                            if await _wait_or_stop(
                                stop, max(0.0, (next_due - now).total_seconds()),
                            ):
                                break
                            continue
                    pending_phase = (
                        scheduled_at, coalesced_slots, next_due,
                        resumable, last_completed,
                    )
                schedule_lag = max(0.0, (now - scheduled_at).total_seconds())
                logger.info(
                    "collector phase requested platform=%s partition=%s run=pending "
                    "scheduled_at=%s phase=requested status=due collector_version=%s "
                    "schedule_lag_seconds=%.3f coalesced_slots=%s mode=%s",
                    platform.value, args.partition, scheduled_at.isoformat(),
                    collector_version, schedule_lag, coalesced_slots, schedule_mode,
                )
                if schedule_mode == "shadow":
                    coordinator.metrics.cycle(
                        platform,
                        duration=0.0,
                        schedule_lag=schedule_lag,
                        overrun=False,
                        coalesced_slots=coalesced_slots,
                        resumed=resumable is not None,
                    )
                    if args.once:
                        return 0
                    pending_phase = None
                    if await _wait_or_stop(
                        stop, max(0.0, (next_due - utc(clock.now(), "clock.now")).total_seconds()),
                    ):
                        break
                    continue

                request = PhaseRequest(
                    platform,
                    args.partition,
                    collector_version,
                    scheduled_at,
                    (
                        resumable
                        if resumable is not None else
                        last_completed + timedelta(seconds=interval_seconds)
                        if last_completed is not None else
                        scheduled_at
                    ),
                    now,
                )
                acquisition = await phase_scheduler.acquire(request, stop)
                phase_result = (
                    "cancelled" if acquisition.cancelled else
                    "superseded" if acquisition.superseded else
                    "acquired" if acquisition.lease is not None else
                    "timeout"
                )
                coordinator.metrics.phase_wait(
                    platform,
                    result=phase_result,
                    duration=acquisition.wait_seconds,
                    attempts=acquisition.attempts,
                )
                if acquisition.lease is None:
                    logger.info(
                        "collector phase not acquired platform=%s partition=%s run=pending "
                        "scheduled_at=%s phase=waiting status=%s collector_version=%s "
                        "wait_seconds=%.3f attempts=%s",
                        platform.value, args.partition, scheduled_at.isoformat(),
                        phase_result, collector_version, acquisition.wait_seconds,
                        acquisition.attempts,
                    )
                    if acquisition.cancelled or stop.is_set():
                        break
                    if acquisition.superseded:
                        pending_phase = None
                        if args.once:
                            return 0
                        continue
                    if args.once:
                        return 0
                    await _wait_or_stop(stop, settings.collector_phase_retry_seconds)
                    continue

                phase_lease = acquisition.lease
                began = time.monotonic()
                summary = None
                forced_shutdown = False
                try:
                    logger.info(
                        "collector phase started platform=%s partition=%s run=pending "
                        "scheduled_at=%s phase=active status=running collector_version=%s "
                        "wait_seconds=%.3f schedule_lag_seconds=%.3f",
                        platform.value, args.partition, scheduled_at.isoformat(),
                        collector_version, acquisition.wait_seconds, schedule_lag,
                    )
                    summary, forced_shutdown = await _run_bounded_cycle(
                        coordinator,
                        scheduled_at,
                        stop=stop,
                        lease=phase_lease,
                        deadline_seconds=policy.cycle_deadline_seconds,
                        shutdown_grace_seconds=settings.collector_shutdown_grace_seconds,
                        lease_probe_seconds=settings.collector_phase_retry_seconds,
                    )
                    phase_lease.finish(summary.status.value, clock.now())
                except asyncio.CancelledError:
                    forced_shutdown = True
                    coordinator.metrics.shutdown(platform, forced=True)
                    logger.warning(
                        "collector phase cancelled platform=%s partition=%s run=pending "
                        "scheduled_at=%s phase=shutdown status=cancelled collector_version=%s",
                        platform.value, args.partition, scheduled_at.isoformat(),
                        collector_version,
                    )
                    break
                except TimeoutError as error:
                    coordinator.metrics.request_timeout(platform)
                    logger.error(
                        "collector phase deadline platform=%s partition=%s run=pending "
                        "scheduled_at=%s phase=active status=failed collector_version=%s code=%s",
                        platform.value, args.partition, scheduled_at.isoformat(),
                        collector_version, sanitize_error_code(error),
                    )
                    if args.once:
                        return 1
                finally:
                    phase_lease.release()
                    pending_phase = None
                _maintain_working_set(
                    retention, coordinator.metrics, settings.collector_disk_path,
                )
                elapsed = time.monotonic() - began
                coordinator.metrics.cycle(
                    platform,
                    duration=elapsed,
                    schedule_lag=schedule_lag,
                    overrun=elapsed >= interval_seconds,
                    coalesced_slots=coalesced_slots,
                    resumed=resumable is not None,
                )
                if elapsed >= interval_seconds:
                    # Цикл, не уложившийся в свой интервал, стоит пропущенных
                    # замеров: планировщик схлопнет перешагнутые слоты в один, и в
                    # истории точек появится провал вместо ровного ряда. Раньше это
                    # было видно только полем overrun в INFO-строке, и разрыв
                    # находили уже на графике публикации, а не в журнале.
                    logger.warning(
                        "collector cycle overran its interval platform=%s partition=%s "
                        "scheduled_at=%s duration_seconds=%.3f interval_seconds=%s "
                        "skipped_slots=%s collector_version=%s",
                        platform.value, args.partition, scheduled_at.isoformat(),
                        elapsed, interval_seconds,
                        int(elapsed) // interval_seconds, collector_version,
                    )
                if forced_shutdown:
                    coordinator.metrics.shutdown(platform, forced=True)
                if summary is not None:
                    logger.info(
                        "collector phase completed platform=%s partition=%s run=%s "
                        "scheduled_at=%s phase=completed status=%s collector_version=%s "
                        "accounts=%s errors=%s duration_seconds=%.3f overrun=%s",
                        platform.value, args.partition, summary.run_id,
                        scheduled_at.isoformat(), summary.status.value,
                        collector_version, summary.account_count, summary.error_count,
                        elapsed, str(elapsed >= interval_seconds).lower(),
                    )
                    if args.once:
                        return 1 if summary.status == RunStatus.FAILED else 0
                if stop.is_set():
                    coordinator.metrics.shutdown(platform, forced=False)
                    break
                backoff = TRANSIENT_BACKOFF_MIN_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not is_transient(error):
                    raise
                # Сбой базы — не повод терять процесс. Перезапуск стоил
                # замера: пока systemd выжидал паузу и поднимал интерпретатор,
                # слот уходил, а при частых сбоях служба упиралась в
                # StartLimitBurst и замолкала совсем. Цикл остаётся на месте:
                # незавершённый прогон подхватит resumable_scheduled_at, а
                # новый слот выдаст due_slot.
                pending_phase = None
                logger.warning(
                    "collector database unavailable platform=%s partition=%s "
                    "code=%s retry_in_seconds=%.0f",
                    platform.value, args.partition,
                    sanitize_error_code(error), backoff,
                )
                if args.once:
                    return 1
                if await _wait_or_stop(stop, backoff):
                    break
                backoff = min(backoff * 2, TRANSIENT_BACKOFF_MAX_SECONDS)
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
        if phase_arbiter is not None:
            phase_arbiter.close()
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
