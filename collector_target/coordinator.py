from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import time
from typing import Iterable

from .model import (
    AccountRef,
    CollectionContext,
    Platform,
    PlatformOutcome,
    RunSummary,
    RunStatus,
    utc,
)
from .metrics import CollectorMetrics
from .normalize import CanonicalNormalizer, sanitize_error_code
from .ports import CollectorRepository, LeaseProvider, PlatformCollector, UtcClock


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemUtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class PollCycleCoordinator:
    """One independently leased platform cycle with resumable account batches."""

    def __init__(
        self,
        *,
        platform: Platform,
        adapter: PlatformCollector,
        repository: CollectorRepository,
        lease_provider: LeaseProvider,
        collector_version: str,
        partition_key: str = "default",
        account_concurrency: int = 1,
        normalizer: CanonicalNormalizer | None = None,
        clock: UtcClock | None = None,
        metrics: CollectorMetrics | None = None,
    ) -> None:
        if adapter.platform != platform:
            raise ValueError("adapter platform does not match coordinator platform")
        if account_concurrency < 1:
            raise ValueError("account_concurrency must be positive")
        self.platform = platform
        self.adapter = adapter
        self.repository = repository
        self.lease_provider = lease_provider
        self.collector_version = collector_version
        self.partition_key = partition_key
        self.account_concurrency = account_concurrency
        self.normalizer = normalizer or CanonicalNormalizer()
        self.clock = clock or SystemUtcClock()
        output = os.environ.get("COLLECTOR_METRICS_FILE")
        self.metrics = metrics or CollectorMetrics(Path(output) if output else None)

    async def run(self, scheduled_at: datetime | None = None) -> RunSummary:
        started_at = utc(self.clock.now(), "clock.now")
        scheduled = utc(scheduled_at, "scheduled_at") if scheduled_at else started_at
        context = CollectionContext.create(
            self.platform,
            self.partition_key,
            self.collector_version,
            scheduled,
            started_at,
        )
        lease = self.lease_provider.acquire(self.platform, self.partition_key)
        if lease is None:
            summary = self.repository.record_skipped_run(context)
            self._observe_run(summary.status)
            return summary

        run_started = False
        try:
            self.repository.start_run(context)
            run_started = True
            accounts = tuple(
                self.repository.enabled_accounts(self.platform, self.partition_key)
            )
            semaphore = asyncio.Semaphore(self.account_concurrency)

            async def collect_account(account: AccountRef) -> None:
                async with semaphore:
                    account_started = utc(self.clock.now(), "account.started_at")
                    if not self.repository.begin_account(
                        context, account, account_started,
                    ):
                        return
                    began = time.monotonic()
                    succeeded = False
                    snapshots = 0
                    try:
                        raw = await self.adapter.collect(account, context)
                        try:
                            batch = self.normalizer.normalize(raw, context)
                        except Exception as rejected:
                            self.repository.quarantine_rejected_batch(raw, context, sanitize_error_code(rejected))
                            raise
                        result = self.repository.persist_account_batch(batch)
                        snapshots = getattr(result, "snapshot_count", 0)
                        succeeded = True
                    except asyncio.CancelledError:
                        self.repository.record_account_failure(
                            context,
                            account,
                            utc(self.clock.now(), "account.completed_at"),
                            "CancelledError",
                        )
                        raise
                    except Exception as error:
                        code = sanitize_error_code(error)
                        self.repository.record_account_failure(
                            context,
                            account,
                            utc(self.clock.now(), "account.completed_at"),
                            code,
                        )
                        logger.error(
                            "collector account failed platform=%s account=%s code=%s",
                            self.platform.value,
                            account.id,
                            code,
                        )
                    finally:
                        try:
                            self.metrics.account(self.platform, succeeded=succeeded,
                                                 duration=time.monotonic()-began, snapshots=snapshots)
                        except Exception as metric_error:
                            logger.warning("collector metrics unavailable code=%s", sanitize_error_code(metric_error))

            results = await asyncio.gather(
                *(collect_account(account) for account in accounts),
                return_exceptions=True,
            )
            fatal = next(
                (result for result in results if isinstance(result, BaseException)),
                None,
            )
            if fatal is not None:
                raise fatal
            summary = self.repository.finish_run(
                context, utc(self.clock.now(), "run.completed_at"),
            )
            self._observe_run(summary.status)
            return summary
        except asyncio.CancelledError:
            if run_started:
                self._best_effort_fail(context)
                self._observe_run(RunStatus.FAILED)
            raise
        except Exception:
            if run_started:
                self._best_effort_fail(context)
                self._observe_run(RunStatus.FAILED)
            raise
        finally:
            lease.release()

    def _observe_run(self, status: RunStatus) -> None:
        try:
            self.metrics.run(self.platform, status)
        except Exception as error:
            logger.warning("collector metrics unavailable code=%s", sanitize_error_code(error))

    def _best_effort_fail(self, context: CollectionContext) -> None:
        try:
            self.repository.fail_run(
                context, utc(self.clock.now(), "run.completed_at"),
            )
        except Exception as error:
            logger.error(
                "collector failed to finalize run platform=%s code=%s",
                self.platform.value,
                sanitize_error_code(error),
            )


class PlatformSupervisor:
    """Run platforms independently so one gateway/repository outage cannot fan out."""

    def __init__(self, coordinators: Iterable[PollCycleCoordinator]):
        items = tuple(coordinators)
        platforms = [item.platform for item in items]
        if len(platforms) != len(set(platforms)):
            raise ValueError("only one coordinator per platform is allowed")
        self.coordinators = items

    async def run_all(
        self, scheduled_at: datetime | None = None,
    ) -> dict[Platform, PlatformOutcome]:
        async def run_one(coordinator: PollCycleCoordinator) -> PlatformOutcome:
            try:
                summary = await coordinator.run(scheduled_at)
                return PlatformOutcome(coordinator.platform, summary)
            except Exception as error:
                code = sanitize_error_code(error)
                logger.error(
                    "collector platform failed platform=%s code=%s",
                    coordinator.platform.value,
                    code,
                )
                return PlatformOutcome(coordinator.platform, None, code)

        outcomes = await asyncio.gather(*(run_one(item) for item in self.coordinators))
        return {outcome.platform: outcome for outcome in outcomes}
