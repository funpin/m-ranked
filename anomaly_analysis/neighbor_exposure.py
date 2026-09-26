"""Offline event and poll-exposure features for neighboring publications.

This module does not score or publish anomalies. It requires actual successful
post reads. A missing receipt cannot be interpreted as a zero view increment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SuccessfulRead:
    publication_id: UUID
    account_id: UUID
    observed_at: datetime
    views_count: int | None
    views_quality: str
    interval_uncertain: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc(self.observed_at))
        if self.views_count is not None and self.views_count < 0:
            raise ValueError("views_count must be nonnegative")


@dataclass(frozen=True, slots=True)
class PublishedPost:
    publication_id: UUID
    account_id: UUID
    published_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "published_at", _utc(self.published_at))


@dataclass(frozen=True, slots=True)
class NeighborInterval:
    start_at: datetime
    end_at: datetime
    elapsed_seconds: float
    displayed_delta_views: int | None
    status: str
    event_publication_ids: tuple[UUID, ...]
    nearest_event_distance: int | None
    # Exact zero is a zero *net counter change between reads*, not proof that
    # no one opened the post. Counters can be revised or duplicate views ignored.
    exact_zero_observed: bool

    @property
    def requires_event_conditioning(self) -> bool:
        return bool(self.event_publication_ids)


def interval_for_reads(
    before: SuccessfulRead,
    after: SuccessfulRead,
    publication_order: tuple[PublishedPost, ...],
    *,
    max_gap: timedelta,
    complete_order: bool,
    max_neighbor_distance: int = 4,
) -> NeighborInterval:
    """Summarize one real read pair without treating displayed counts as exact.

    `complete_order` must be established independently from collection metadata.
    If it is false, position in the feed is not trusted and the interval
    abstains from the neighbor test.
    """
    if before.publication_id != after.publication_id or before.account_id != after.account_id:
        raise ValueError("reads must belong to the same publication and account")
    if max_gap <= timedelta(0) or not 1 <= max_neighbor_distance <= 32:
        raise ValueError("invalid exposure bounds")
    elapsed = (after.observed_at - before.observed_at).total_seconds()
    if elapsed <= 0:
        raise ValueError("reads must be in time order")

    own = [post for post in publication_order
           if post.account_id == before.account_id]
    own.sort(key=lambda post: (post.published_at, post.publication_id))
    positions = {post.publication_id: index for index, post in enumerate(own)}
    if len(positions) != len(own):
        raise ValueError("publication order contains duplicate IDs")
    old_position = positions.get(before.publication_id) if complete_order else None
    order_usable = (complete_order and old_position is not None
                    and own[old_position].published_at <= before.observed_at)
    events = [
        (post, positions[post.publication_id] - old_position)
        for post in own
        if order_usable and post.publication_id != before.publication_id
        and 0 < positions[post.publication_id] - old_position <= max_neighbor_distance
        and before.observed_at < post.published_at <= after.observed_at
    ]
    events.sort(key=lambda item: (item[0].published_at, item[0].publication_id))
    near_ids = tuple(post.publication_id for post, _ in events)
    distance = min((position for _, position in events), default=None)

    delta = None if before.views_count is None or after.views_count is None else (
        after.views_count - before.views_count)
    if not order_usable:
        status = "incomplete_publication_order"
    elif elapsed > max_gap.total_seconds():
        status = "excessive_gap"
    elif delta is None:
        status = "missing_views"
    elif before.views_quality not in {"exact", "rounded"} or after.views_quality not in {"exact", "rounded"}:
        status = "untrusted_quality"
    elif before.interval_uncertain or after.interval_uncertain:
        status = "uncertain_interval"
    elif delta < 0:
        status = "negative_correction_or_reset"
    else:
        status = "usable"

    exact_zero = (status == "usable" and delta == 0
                  and before.views_quality == after.views_quality == "exact")
    return NeighborInterval(
        before.observed_at, after.observed_at, elapsed, delta, status,
        near_ids, distance, exact_zero,
    )
