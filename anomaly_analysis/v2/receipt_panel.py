"""Observed view-growth intervals for the future platform-conditioned M1 model.

Only consecutive successful reads of the *same post* form an interval. This
module does not score anomalies and never invents zero growth for missing reads.
The publication event/neighbor exposure is added separately by M2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log1p
from typing import Iterable, Mapping
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead

TRUSTED_VIEW_QUALITY = frozenset({"exact", "rounded"})


@dataclass(frozen=True, slots=True)
class ObservedGrowth:
    platform: str
    account_id: UUID
    publication_id: UUID
    start_at: datetime
    end_at: datetime
    age_seconds: float
    elapsed_seconds: float
    before_views: int | None
    after_views: int | None
    displayed_delta_views: int | None
    log_growth: float | None
    rounded: bool
    exact_zero_observed: bool
    status: str

    @property
    def usable(self) -> bool:
        return self.status == "usable"


def consecutive_growth(
    reads: Iterable[SuccessfulRead],
    publications: Iterable[PublishedPost],
    platform_by_account: Mapping[UUID, str],
    *,
    max_gap_by_platform: Mapping[str, timedelta],
) -> tuple[ObservedGrowth, ...]:
    """Build a measured risk set without interpreting missing rows as zeros.

    The caller must supply the complete set of *eligible* posts separately for
    coverage reporting; a post with fewer than two reads produces no interval.
    Gap limits are explicit per platform, because RuTube's poll cadence differs
    from Telegram/VK/MAX. No default or cross-platform substitution is allowed.
    """
    posts = {item.publication_id: item for item in publications}
    grouped: dict[UUID, list[SuccessfulRead]] = {}
    for read in reads:
        if read.publication_id not in posts:
            raise ValueError("receipt has no publication metadata")
        if posts[read.publication_id].account_id != read.account_id:
            raise ValueError("receipt and publication belong to different accounts")
        grouped.setdefault(read.publication_id, []).append(read)

    intervals: list[ObservedGrowth] = []
    for publication_id, post_reads in grouped.items():
        post = posts[publication_id]
        platform = platform_by_account.get(post.account_id)
        if platform is None or platform not in max_gap_by_platform:
            raise ValueError("platform or platform-specific gap limit is missing")
        max_gap = max_gap_by_platform[platform]
        if max_gap <= timedelta(0):
            raise ValueError("maximum read gap must be positive")
        post_reads.sort(key=lambda item: item.observed_at)
        for before, after in zip(post_reads, post_reads[1:]):
            elapsed = (after.observed_at - before.observed_at).total_seconds()
            if elapsed <= 0:
                raise ValueError("duplicate or reversed read timestamps")
            age = (before.observed_at - post.published_at).total_seconds()
            delta = (after.views_count - before.views_count
                     if before.views_count is not None and after.views_count is not None else None)
            if age < 0:
                status = "before_publication"
            elif elapsed > max_gap.total_seconds():
                status = "excessive_gap"
            elif delta is None:
                status = "missing_views"
            elif before.views_quality not in TRUSTED_VIEW_QUALITY or after.views_quality not in TRUSTED_VIEW_QUALITY:
                status = "untrusted_quality"
            elif before.interval_uncertain or after.interval_uncertain:
                status = "uncertain_interval"
            elif delta < 0:
                status = "negative_correction_or_reset"
            else:
                status = "usable"
            rounded = before.views_quality == "rounded" or after.views_quality == "rounded"
            intervals.append(ObservedGrowth(
                platform, post.account_id, publication_id,
                before.observed_at, after.observed_at, age, elapsed,
                before.views_count, after.views_count, delta,
                log1p(after.views_count) - log1p(before.views_count) if status == "usable" else None,
                rounded, status == "usable" and delta == 0 and not rounded, status,
            ))
    return tuple(sorted(intervals, key=lambda item: (item.account_id, item.publication_id, item.start_at)))
