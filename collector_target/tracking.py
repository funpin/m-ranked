from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Collection, Sequence

from app.analytics import age_seconds
from app.public_web import snapshot_interval_minutes, snapshot_is_due

from .model import (
    AccountRef,
    CollectionContext,
    DeletionProbeOutcome,
    Platform,
    RawDeletionProbe,
    TrackedPublication,
    utc,
)
from .ports import PublicationTrackingReader


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    publications: tuple[TrackedPublication, ...]
    next_cursor: str | None


def _positive_setting(settings: Any, name: str, default: int) -> int:
    value = int(getattr(settings, name, default))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def deletion_confirmation_threshold(settings: Any) -> int:
    value = _positive_setting(settings, "deletion_confirmation_checks", 2)
    if value < 2:
        raise ValueError("deletion_confirmation_checks must be at least two")
    return value


def validate_tracking_policy(settings: Any) -> None:
    refresh_limit = _positive_setting(settings, "collector_refresh_limit", 100)
    scan_limit = _positive_setting(settings, "collector_refresh_scan_limit", 400)
    if scan_limit < refresh_limit:
        raise ValueError("collector_refresh_scan_limit must not be below refresh limit")
    _positive_setting(settings, "track_post_for_hours", 960)
    deletion_confirmation_threshold(settings)


def plan_refresh(
    *,
    tracking: PublicationTrackingReader | None,
    account: AccountRef,
    context: CollectionContext,
    settings: Any,
    observed_at: datetime,
    discovered_external_ids: Collection[str],
) -> RefreshPlan:
    """Select due tracked objects from one bounded round-robin scan.

    Discovery has already consumed its own independent provider request before
    this function runs. The durable cursor advances only through rows examined
    here and is committed atomically with the resulting account batch. When the
    point-refresh budget is exhausted, the cursor stops at the last selected
    row, so remaining due rows are first in the next circular page.
    """

    if tracking is None:
        return RefreshPlan((), None)
    observed = utc(observed_at, "refresh.observed_at")
    validate_tracking_policy(settings)
    refresh_limit = _positive_setting(settings, "collector_refresh_limit", 100)
    scan_limit = _positive_setting(settings, "collector_refresh_scan_limit", 400)
    track_hours = _positive_setting(settings, "track_post_for_hours", 960)
    page = tracking.tracked_publications(
        account,
        published_after=observed - timedelta(hours=track_hours),
        limit=scan_limit,
    )
    discovered = {str(value) for value in discovered_external_ids}
    selected: list[TrackedPublication] = []
    cursor: str | None = None
    for publication in page:
        cursor = publication.cursor
        if publication.external_id in discovered:
            continue
        interval_minutes = snapshot_interval_minutes(
            age_seconds(publication.published_at, observed),
            settings,
            platform=(
                Platform.RUTUBE.value
                if account.platform == Platform.RUTUBE else None
            ),
        )
        latest = (
            publication.latest_observed_at.isoformat()
            if publication.latest_observed_at is not None else None
        )
        if not snapshot_is_due(
            latest,
            context.scheduled_at,
            interval_minutes,
            last_measurement_bucket=publication.latest_sampling_bucket,
        ):
            continue
        selected.append(publication)
        if len(selected) >= refresh_limit:
            break
    return RefreshPlan(tuple(selected), cursor)


def missing_probe(
    publication: TrackedPublication,
    observed_at: datetime,
    settings: Any,
    reason_code: str,
) -> RawDeletionProbe:
    return RawDeletionProbe(
        publication.id,
        utc(observed_at, "probe.observed_at"),
        DeletionProbeOutcome.MISSING,
        reason_code,
        deletion_confirmation_threshold(settings),
    )


def unsupported_probe(
    publication: TrackedPublication,
    observed_at: datetime,
    settings: Any,
    reason_code: str,
) -> RawDeletionProbe:
    return RawDeletionProbe(
        publication.id,
        utc(observed_at, "probe.observed_at"),
        DeletionProbeOutcome.UNSUPPORTED,
        reason_code,
        deletion_confirmation_threshold(settings),
    )


def transient_probe(
    publication: TrackedPublication,
    observed_at: datetime,
    settings: Any,
    provider: str,
    error: BaseException,
) -> RawDeletionProbe:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    error_name = error.__class__.__name__.casefold()
    if status in {401, 403} or "auth" in error_name:
        suffix = "auth_error"
    elif status == 429 or "flood" in error_name or "ratelimit" in error_name:
        suffix = "rate_limited"
    elif isinstance(status, int) and status >= 500:
        suffix = "transient_http"
    elif error.__class__.__name__ in {
        "ConnectError", "ConnectTimeout", "ReadError", "ReadTimeout",
        "RemoteProtocolError", "TimeoutError",
    }:
        suffix = "transport_error"
    else:
        suffix = "probe_error"
    return RawDeletionProbe(
        publication.id,
        utc(observed_at, "probe.observed_at"),
        DeletionProbeOutcome.TRANSIENT_ERROR,
        f"{provider}_{suffix}",
        deletion_confirmation_threshold(settings),
    )


def by_chunks(values: Sequence[Any], size: int) -> tuple[tuple[Any, ...], ...]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    return tuple(
        tuple(values[offset:offset + size])
        for offset in range(0, len(values), size)
    )
