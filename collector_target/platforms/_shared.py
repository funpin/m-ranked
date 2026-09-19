from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, TypeVar

from collector_runtime.analytics import age_seconds
from collector_runtime.config import Settings
from collector_runtime.public_web import snapshot_interval_minutes

from ..model import AccountRef, HistoryCompleteness, utc
from ..ports import PublicationTrackingReader, UtcClock


Interval = int | Callable[[datetime], int]
T = TypeVar("T")


def reference(account: AccountRef) -> str:
    return (
        account.current_url
        or account.current_username
        or account.canonical_external_id
    )


def sampling_interval(
    settings: Settings,
    observed_at: datetime,
    *,
    platform: str | None = None,
) -> Callable[[datetime], int]:
    def seconds(published_at: datetime) -> int:
        return 60 * snapshot_interval_minutes(
            age_seconds(published_at, observed_at),
            settings,
            platform=platform,
        )

    return seconds


def observation_times(clock: UtcClock) -> tuple[datetime, datetime]:
    observed = utc(clock.now(), "gateway.observed_at")
    collected = utc(clock.now(), "gateway.collected_at")
    if collected < observed:
        raise ValueError("gateway clock moved backwards")
    return observed, collected


def tracking_reader(value: Any) -> PublicationTrackingReader | None:
    return value if callable(getattr(value, "tracked_publications", None)) else None


def deduplicate(values: list[T], key: Callable[[T], Any]) -> list[T]:
    result: dict[Any, T] = {}
    for value in values:
        result[key(value)] = value
    return list(result.values())


def interval_seconds(value: Interval, published_at: datetime) -> int:
    interval = value(published_at) if callable(value) else value
    interval = int(interval)
    if interval <= 0:
        raise ValueError("sampling interval must be positive")
    return interval


def history_completeness(
    published_at: datetime,
    discovered_at: datetime,
    complete_history_max_first_age_seconds: int,
) -> HistoryCompleteness:
    age = max(0, int((discovered_at - published_at).total_seconds()))
    return (
        HistoryCompleteness.COMPLETE
        if age <= complete_history_max_first_age_seconds
        else HistoryCompleteness.INCOMPLETE
    )
