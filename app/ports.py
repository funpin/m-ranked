from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


ObservationRow = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SnapshotDelta:
    delta_total: int | None
    spike: bool


@runtime_checkable
class CollectorAdapter(Protocol):
    """One independently scheduled collector cycle."""

    async def poll_cycle(self) -> None:
        ...


@runtime_checkable
class ClosableCollectorAdapter(CollectorAdapter, Protocol):
    async def close(self) -> None:
        ...


@runtime_checkable
class TelegramObservationTransaction(Protocol):
    """Atomic Telegram observation writes used by collectors."""

    def add_post(
        self,
        channel_id: int,
        logical_key: str,
        message_ids: Sequence[int],
        grouped_id: int | None,
        published_at: datetime,
        discovered_at: datetime,
        first_age_seconds: int,
        history_complete: bool,
        post_type: str,
        ambiguous: bool,
        is_repost: bool = False,
    ) -> int:
        ...

    def mark_post_available(self, post_id: int) -> None:
        ...

    def ensure_publication_baseline(
        self,
        post_id: int,
        published_at: datetime,
        first_age_seconds: int,
        max_age_seconds: int,
    ) -> bool:
        ...

    def set_post_repost(self, post_id: int, is_repost: bool) -> None:
        ...

    def insert_snapshot(
        self,
        post_id: int,
        measured_at: datetime,
        age_seconds: int,
        total: int,
        reactions: Mapping[str, int],
        raw_state: Any,
        poll_interval_minutes: int,
        jump_min_abs: int,
        jump_min_ratio: float,
        comments_count: int | None = None,
        views_count: int | None = None,
        bucket_at: datetime | None = None,
    ) -> bool:
        ...

    def latest_snapshot_delta(self, post_id: int) -> SnapshotDelta | None:
        ...


@runtime_checkable
class PlatformObservationTransaction(Protocol):
    """Atomic VK/MAX/Rutube observation writes used by collectors."""

    def mark_platform_post_available(self, post_id: int) -> None:
        ...

    def record_platform_post_missing(
        self,
        post_id: int,
        detected_at: datetime,
        reason: str,
        confirmation_checks: int,
    ) -> tuple[int, bool]:
        ...

    def upsert_platform_post(
        self,
        platform_account_id: int,
        external_id: str,
        published_at: datetime,
        discovered_at: datetime,
        post_type: str,
        url: str | None,
        raw: Any,
        *,
        history_complete: bool = False,
        source_external_id: str | None = None,
        is_joint: bool = False,
        additional_author_count: int = 0,
        is_repost: bool = False,
    ) -> int:
        ...

    def latest_platform_snapshot_timing(
        self, platform_post_id: int,
    ) -> tuple[str | None, int | None]:
        ...

    def platform_metric_high_watermarks(
        self, platform_post_id: int,
    ) -> dict[str, int | None]:
        ...

    def insert_platform_snapshot(
        self,
        platform_post_id: int,
        measured_at: datetime,
        age_seconds: int,
        poll_interval_minutes: int,
        *,
        views_count: int | None,
        reactions_count: int | None,
        comments_count: int | None,
        shares_count: int | None,
        raw: Any,
        bucket_at: datetime | None = None,
    ) -> bool:
        ...


@runtime_checkable
class ObservationTransaction(
    TelegramObservationTransaction,
    PlatformObservationTransaction,
    Protocol,
):
    """Composite implemented by the current SQLite unit of work."""


@runtime_checkable
class TransactionBoundary(Protocol):
    """Context boundary that commits on success and rolls back on failure."""

    def __enter__(self) -> ObservationTransaction:
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        ...


@runtime_checkable
class ObservationRepository(Protocol):
    """Common observation capabilities; platform-specific methods stay split."""

    def transaction(self) -> TransactionBoundary:
        ...

    def set_state(self, key: str, value: str) -> None:
        ...

    def get_state(self, key: str) -> str | None:
        ...


@runtime_checkable
class TelegramObservationRepository(ObservationRepository, Protocol):
    def list_channels(self, enabled_only: bool = False) -> list[ObservationRow]:
        ...

    def update_channel_identity(
        self, channel_id: int, telegram_id: int, title: str, username: str,
    ) -> None:
        ...

    def update_channel_public_metadata(
        self,
        channel_id: int,
        title: str | None,
        subscribers: int | None,
        display: str | None,
    ) -> None:
        ...

    def update_channel_title(self, channel_id: int, title: str | None) -> None:
        ...

    def finish_channel_check(
        self, channel_id: int, last_seen: int, error: str | None = None,
    ) -> None:
        ...

    def active_posts(self, channel_id: int, cutoff_iso: str) -> list[ObservationRow]:
        ...

    def post_message_ids(self, post_id: int) -> list[int]:
        ...

    def record_post_missing(
        self,
        post_id: int,
        detected_at: datetime,
        reason: str,
        confirmation_checks: int,
    ) -> tuple[int, bool]:
        ...

    def expired_posts(self, cutoff_iso: str) -> list[ObservationRow]:
        ...

    def archive_rows(self, post_id: int) -> list[ObservationRow]:
        ...

    def delete_post(self, post_id: int) -> None:
        ...


@runtime_checkable
class PlatformObservationRepository(ObservationRepository, Protocol):
    def list_platform_accounts(
        self,
        institution_id: int | None = None,
        platform: str | None = None,
        enabled_only: bool = False,
    ) -> list[ObservationRow]:
        ...

    def update_platform_account_metadata(
        self,
        account_id: int,
        *,
        native_id: str,
        username: str,
        title: str,
        url: str,
        subscriber_count: int | None,
        measured_at: datetime,
    ) -> None:
        ...

    def finish_platform_account_check(
        self,
        account_id: int,
        measured_at: datetime,
        error: str | None = None,
    ) -> None:
        ...

    def list_platform_posts(
        self,
        *,
        platform: str | None = None,
        institution_id: int | None = None,
        account_id: int | None = None,
        published_after: datetime | None = None,
        limit: int | None = None,
        include_deleted: bool = True,
    ) -> list[ObservationRow]:
        ...


@runtime_checkable
class AnalyticsReadRepository(Protocol):
    """Small read-side port required by the current platform analytics SQL."""

    def query(
        self, sql: str, params: Sequence[Any] = (),
    ) -> list[ObservationRow]:
        ...

    def list_institutions(self) -> list[ObservationRow]:
        ...

    def list_platform_accounts(
        self,
        institution_id: int | None = None,
        platform: str | None = None,
        enabled_only: bool = False,
    ) -> list[ObservationRow]:
        ...


@runtime_checkable
class AnalyticsQueryService(Protocol):
    """High-level analytics seam consumed by HTTP handlers."""

    def rating_data(
        self, platform: str, cutoff: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ...

    def activity_cards(
        self,
        platform: str,
        start: datetime,
        previous_start: datetime,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        ...
