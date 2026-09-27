"""Bounded M2 event contrast on real successful-read intervals.

This is a descriptive feature extractor, not a public verdict or a probability.
It abstains unless publication order, a new post, a same-post quiet control, and
at least two measured older peers are all available. No missing read is zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Iterable, Mapping
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost
from anomaly_analysis.v2.receipt_panel import ObservedGrowth

HOUR = 3600.0
QUIET_LOOKBACK = timedelta(hours=24)
EVENT_EMBARGO = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class EventContrast:
    status: str
    reason: str
    event_publication_ids: tuple[UUID, ...]
    target_extra_per_hour: float | None = None
    peer_extra_median_per_hour: float | None = None
    residual_per_hour: float | None = None
    matched_peer_count: int = 0
    rounded: bool = False


def _rate(interval: ObservedGrowth) -> float:
    assert interval.usable and interval.displayed_delta_views is not None
    return interval.displayed_delta_views / (interval.elapsed_seconds / HOUR)


def _quiet_match(
    event: ObservedGrowth,
    history: Iterable[ObservedGrowth],
    publication_times: tuple,
) -> ObservedGrowth | None:
    candidates = []
    for row in history:
        if (row.publication_id != event.publication_id or row.account_id != event.account_id
                or row.platform != event.platform or not row.usable):
            continue
        if not event.start_at - QUIET_LOOKBACK <= row.start_at:
            continue
        if row.end_at > event.start_at - EVENT_EMBARGO:
            continue
        if not 0.75 <= row.elapsed_seconds / event.elapsed_seconds <= 1.25:
            continue
        if any(row.start_at - EVENT_EMBARGO <= at <= row.end_at + EVENT_EMBARGO
               for at in publication_times):
            continue
        candidates.append(row)
    return max(candidates, key=lambda row: row.end_at, default=None)


def _aligned(target: ObservedGrowth, peer: ObservedGrowth) -> bool:
    overlap = (min(target.end_at, peer.end_at) - max(target.start_at, peer.start_at)).total_seconds()
    return overlap >= 0.5 * min(target.elapsed_seconds, peer.elapsed_seconds)


def event_contrast(
    target: ObservedGrowth,
    peer_event_intervals: Iterable[ObservedGrowth],
    histories: Mapping[UUID, Iterable[ObservedGrowth]],
    publication_order: Iterable[PublishedPost],
    *,
    complete_order: bool,
    max_neighbor_distance: int = 4,
) -> EventContrast:
    """Compare event-minus-quiet rates with the median of older same-account posts.

    The caller supplies a small, preselected risk set. It must report cohort
    coverage separately; this extractor cannot infer unseen posts or failed
    polls from the supplied intervals. Future M1 residuals and holdout
    calibration are needed before the feature can affect a saved status.
    """
    if not 1 <= max_neighbor_distance <= 32:
        raise ValueError("invalid neighbor distance")
    if not complete_order:
        return EventContrast("insufficient_data", "incomplete_publication_order", ())
    if not target.usable:
        return EventContrast("insufficient_data", "unusable_target_interval", ())

    posts = sorted((post for post in publication_order if post.account_id == target.account_id),
                   key=lambda post: (post.published_at, post.publication_id))
    positions = {post.publication_id: index for index, post in enumerate(posts)}
    if len(positions) != len(posts):
        raise ValueError("duplicate publication in order")
    position = positions.get(target.publication_id)
    if position is None or posts[position].published_at > target.start_at:
        return EventContrast("insufficient_data", "target_missing_from_order", ())
    event_ids = tuple(post.publication_id for index, post in enumerate(posts)
                      if 0 < index - position <= max_neighbor_distance
                      and target.start_at < post.published_at <= target.end_at)
    if not event_ids:
        return EventContrast("insufficient_data", "no_nearby_new_post", ())

    times = tuple(post.published_at for post in posts)
    quiet_target = _quiet_match(target, histories.get(target.publication_id, ()), times)
    if quiet_target is None:
        return EventContrast("insufficient_data", "no_target_quiet_control", event_ids)
    target_extra = _rate(target) - _rate(quiet_target)

    extras: list[float] = []
    rounded = target.rounded or quiet_target.rounded
    used: set[UUID] = set()
    for peer in peer_event_intervals:
        peer_position = positions.get(peer.publication_id)
        if (not peer.usable or peer.platform != target.platform or peer.account_id != target.account_id
                or peer_position is None or peer_position >= position
                or peer.publication_id in used or not _aligned(target, peer)):
            continue
        quiet = _quiet_match(peer, histories.get(peer.publication_id, ()), times)
        if quiet is None:
            continue
        used.add(peer.publication_id)
        extras.append(_rate(peer) - _rate(quiet))
        rounded = rounded or peer.rounded or quiet.rounded
    if len(extras) < 2:
        return EventContrast("insufficient_data", "fewer_than_two_matched_peers", event_ids,
                             matched_peer_count=len(extras), rounded=rounded)
    peer_median = median(extras)
    return EventContrast("contrast_available", "descriptive_only", event_ids,
                         target_extra, peer_median, target_extra - peer_median,
                         len(extras), rounded)
