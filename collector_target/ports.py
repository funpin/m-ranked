from __future__ import annotations

from datetime import datetime
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .model import (
    AccountRef,
    CanonicalAccountBatch,
    CollectionContext,
    IngestionResult,
    Platform,
    RawCollectionBatch,
    RunSummary,
    TrackedPublication,
)


@runtime_checkable
class PlatformCollector(Protocol):
    platform: Platform

    async def collect(
        self,
        account: AccountRef,
        context: CollectionContext,
    ) -> RawCollectionBatch:
        ...


@runtime_checkable
class CollectorRepository(Protocol):
    def start_run(self, context: CollectionContext) -> None:
        ...

    def record_skipped_run(self, context: CollectionContext) -> RunSummary:
        ...

    def resumable_scheduled_at(
        self,
        platform: Platform,
        partition_key: str,
        collector_version: str,
    ) -> datetime | None:
        ...

    def enabled_accounts(
        self, platform: Platform, partition_key: str,
    ) -> Sequence[AccountRef]:
        ...

    def begin_account(
        self, context: CollectionContext, account: AccountRef, started_at: datetime,
    ) -> bool:
        """Return false when this account already succeeded in a resumed run."""
        ...

    def persist_account_batch(self, batch: CanonicalAccountBatch) -> IngestionResult:
        ...

    def record_account_failure(
        self,
        context: CollectionContext,
        account: AccountRef,
        completed_at: datetime,
        error_code: str,
    ) -> None:
        ...

    def finish_run(self, context: CollectionContext, completed_at: datetime) -> RunSummary:
        ...

    def fail_run(
        self, context: CollectionContext, completed_at: datetime,
    ) -> RunSummary:
        ...


@runtime_checkable
class MetricHistoryReader(Protocol):
    def metric_high_watermarks(
        self,
        account: AccountRef,
        external_ids: Sequence[str],
    ) -> Mapping[str, Mapping[str, int | None]]:
        ...


@runtime_checkable
class PublicationTrackingReader(Protocol):
    def tracked_publications(
        self,
        account: AccountRef,
        *,
        published_after: datetime,
        limit: int,
    ) -> Sequence[TrackedPublication]:
        """Return one circular, cursor-ordered page of active publications."""

        ...


@runtime_checkable
class LeaseHandle(Protocol):
    key: str

    def release(self) -> None:
        ...


@runtime_checkable
class LeaseProvider(Protocol):
    def acquire(self, platform: Platform, partition_key: str) -> LeaseHandle | None:
        ...


@runtime_checkable
class UtcClock(Protocol):
    def now(self) -> datetime:
        ...
