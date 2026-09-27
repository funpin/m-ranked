"""Research-only upper-tail comparison for bounded rounded view increments.

Each reference account-day contributes its largest *upper* growth rate in the
same age/exposure cell. A later interval contributes only its *lower* rate.
This cannot make an uncertain compact display look more unusual than exact
values consistent with it. The result is an interval diagnostic, not a post
alert: coverage, repeated test intervals and changing day patterns still need
separate validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Iterable, Literal
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead

from .interval_baseline import age_band, exposure_band
from .rounded_growth import bounded_view_growth


Source = Literal["successful_poll_receipts", "change_only_shadow"]
Cell = tuple[UUID, str, str]


@dataclass(frozen=True, slots=True)
class BoundedInterval:
    platform: str
    post: PublishedPost
    before: SuccessfulRead
    after: SuccessfulRead


@dataclass(frozen=True, slots=True)
class BoundedTailRank:
    status: str
    upper_tail_rank: float | None
    lower_rate_per_hour: float | None
    calibration_days: int
    calibration_posts: int


class _UnavailableBound(ValueError):
    def __init__(self, status: str):
        super().__init__(f"bounded interval unavailable: {status}")
        self.status = status


def _features(row: BoundedInterval, max_gap: timedelta) -> tuple[Cell, date, float, float]:
    if (row.before.publication_id != row.post.publication_id
            or row.after.publication_id != row.post.publication_id
            or row.before.account_id != row.post.account_id
            or row.after.account_id != row.post.account_id):
        raise ValueError("bounded interval and publication metadata disagree")
    if row.before.observed_at < row.post.published_at:
        raise ValueError("read predates publication")
    before_day = row.before.observed_at.astimezone(timezone.utc).date()
    after_day = row.after.observed_at.astimezone(timezone.utc).date()
    if before_day != after_day:
        raise ValueError("bounded interval crosses a UTC day")
    growth = bounded_view_growth(row.before, row.after, max_gap=max_gap)
    if growth.status != "bounded":
        raise _UnavailableBound(growth.status)
    elapsed = (row.after.observed_at - row.before.observed_at).total_seconds()
    cell = (row.post.account_id,
            age_band((row.before.observed_at - row.post.published_at).total_seconds()),
            exposure_band(elapsed))
    hours = elapsed / 3600
    return (cell, after_day,
            max(0, growth.lower_delta) / hours,
            max(0, growth.upper_delta) / hours)


class BoundedTailReference:
    """Account-specific daily upper bounds, without cross-platform pooling."""

    def __init__(self, platform: str, source: Source,
                 blocks: dict[Cell, dict[date, float]],
                 posts: dict[Cell, frozenset[UUID]],
                 publication_ids: frozenset[UUID], latest_day: date,
                 max_gap: timedelta, min_days: int, min_posts: int):
        self.platform = platform
        self.source = source
        self.blocks = blocks
        self.posts = posts
        self.publication_ids = publication_ids
        self.latest_day = latest_day
        self.max_gap = max_gap
        self.min_days = min_days
        self.min_posts = min_posts

    @classmethod
    def fit(cls, rows: Iterable[BoundedInterval], *, source: Source,
            max_gap: timedelta = timedelta(hours=2), min_days: int = 7,
            min_posts: int = 5) -> "BoundedTailReference":
        if source not in {"successful_poll_receipts", "change_only_shadow"}:
            raise ValueError("unknown read source")
        if min_days < 2 or min_posts < 2:
            raise ValueError("reference needs at least two days and posts")
        items = tuple(rows)
        if not items:
            raise ValueError("bounded reference cannot be empty")
        platform = items[0].platform
        blocks: dict[Cell, dict[date, float]] = {}
        posts: dict[Cell, set[UUID]] = {}
        ids: set[UUID] = set()
        days: set[date] = set()
        for row in items:
            if row.platform != platform:
                raise ValueError("bounded reference cannot mix platforms")
            cell, day, _lower, upper = _features(row, max_gap)
            per_day = blocks.setdefault(cell, {})
            per_day[day] = max(per_day.get(day, 0.0), upper)
            posts.setdefault(cell, set()).add(row.post.publication_id)
            ids.add(row.post.publication_id)
            days.add(day)
        return cls(platform, source, blocks,
                   {cell: frozenset(values) for cell, values in posts.items()},
                   frozenset(ids), max(days), max_gap, min_days, min_posts)

    def rank(self, row: BoundedInterval) -> BoundedTailRank:
        if row.platform != self.platform:
            raise ValueError("test platform differs from reference")
        if row.post.publication_id in self.publication_ids:
            raise ValueError("test post appears in reference")
        try:
            cell, day, lower, _upper = _features(row, self.max_gap)
        except _UnavailableBound as error:
            return BoundedTailRank(error.status, None, None, 0, 0)
        if day <= self.latest_day:
            raise ValueError("test interval must follow reference on a later UTC day")
        reference = self.blocks.get(cell, {})
        days = len(reference)
        posts = len(self.posts.get(cell, frozenset()))
        if days < self.min_days or posts < self.min_posts:
            return BoundedTailRank("insufficient_reference", None, lower, days, posts)
        tail = (1 + sum(upper >= lower for upper in reference.values())) / (days + 1)
        status = "research_ranked" if self.source == "successful_poll_receipts" else "shadow_only"
        return BoundedTailRank(status, tail, lower, days, posts)
