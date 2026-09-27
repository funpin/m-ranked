"""Research M2: rank M1 residuals conditional on a new post's feed distance.

The inputs must be actual successful-read intervals from a future cohort.
Train M1 on earlier days, fit these account-day maxima on later calibration
days, then evaluate on a separate future holdout. An event is an observed
publication between two reads, not a measured referral or causal explanation.
No score from this module is a public anomaly verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping
from uuid import UUID

from anomaly_analysis.neighbor_exposure import NeighborInterval, SuccessfulRead

from .interval_baseline import ConditionalIntervalBaseline, IntervalScore
from .receipt_panel import ObservedGrowth


def feed_band(distance: int | None) -> str:
    if distance is None:
        return "no_event_within_scope"
    if distance < 1:
        raise ValueError("feed distance must be positive")
    if distance == 1:
        return "next_post"
    if distance == 2:
        return "second_post"
    if distance <= 4:
        return "third_or_fourth"
    return "farther_post"


@dataclass(frozen=True, slots=True)
class FeedObservedGrowth:
    interval: ObservedGrowth
    nearest_event_distance: int | None
    complete_order: bool
    new_post_views: int | None = None


def feed_observation(interval: ObservedGrowth, exposure: NeighborInterval,
                     new_post_reads: Mapping[UUID, SuccessfulRead] | None = None) -> FeedObservedGrowth:
    """Join the real read pair, feed order and measured new-post reach.

    A new post's displayed views are an exposure proxy, not observed referrals.
    Every new post in the interval needs a trustworthy read by its end; an
    incomplete set is retained as missing and cannot enter M2 calibration.
    """
    if interval.start_at != exposure.start_at or interval.end_at != exposure.end_at:
        raise ValueError("growth and feed exposure must describe the same read pair")
    if (interval.elapsed_seconds != exposure.elapsed_seconds
            or interval.displayed_delta_views != exposure.displayed_delta_views):
        raise ValueError("growth and feed exposure disagree on the read pair")
    if bool(exposure.event_publication_ids) != (exposure.nearest_event_distance is not None):
        raise ValueError("event IDs and feed distance disagree")
    views = 0 if not exposure.event_publication_ids else None
    if exposure.event_publication_ids and new_post_reads is not None:
        measured = [new_post_reads.get(publication_id)
                    for publication_id in exposure.event_publication_ids]
        if all(read is not None and read.account_id == interval.account_id
               and interval.start_at <= read.observed_at <= interval.end_at
               and read.views_quality == "exact" and not read.interval_uncertain
               and read.views_count is not None for read in measured):
            views = sum(read.views_count for read in measured if read is not None)
    return FeedObservedGrowth(interval, exposure.nearest_event_distance,
                              exposure.status != "incomplete_publication_order", views)


def reach_band(row: FeedObservedGrowth) -> str | None:
    if row.nearest_event_distance is None:
        return "no_new_post"
    if row.new_post_views is None or row.interval.before_views is None:
        return None
    ratio = row.new_post_views / max(1, row.interval.before_views)
    if ratio < 0.1:
        return "low_reach"
    if ratio < 0.5:
        return "medium_reach"
    return "high_reach"


@dataclass(frozen=True, slots=True)
class FeedTailRank:
    status: str
    m1: IntervalScore
    feed_band: str | None
    reach_band: str | None
    upper_tail_rank: float | None
    calibration_blocks: int
    calibration_accounts: int


CellKey = tuple[str, str, str, str, str]
BlockKey = tuple[UUID, date]


class EventAdjustedTail:
    """Empirical account-day tail of M1 residuals at similar feed exposure.

    Sparse cells abstain. They never borrow a different platform, age,
    exposure, or feed position. The rank measures rarity among observed
    intervals, not the probability of artificial activity.
    """

    def __init__(self, m1: ConditionalIntervalBaseline,
                 blocks: dict[CellKey, dict[BlockKey, float]],
                 min_blocks: int, min_accounts: int):
        self.m1 = m1
        self.blocks = blocks
        self.min_blocks = min_blocks
        self.min_accounts = min_accounts

    @classmethod
    def fit(cls, m1: ConditionalIntervalBaseline,
            calibration: tuple[FeedObservedGrowth, ...], *,
            min_blocks: int = 20, min_accounts: int = 3) -> "EventAdjustedTail":
        if min_blocks < 2 or min_accounts < 2:
            raise ValueError("calibration requires at least two blocks and accounts")
        blocks: dict[CellKey, dict[BlockKey, float]] = {}
        for row in calibration:
            if not row.complete_order:
                continue
            reach = reach_band(row)
            if reach is None:
                continue
            score = m1.score(row.interval)
            if score.status != "scored_positive" or score.positive_residual is None:
                continue
            cell = (score.platform, score.age, score.exposure,
                    feed_band(row.nearest_event_distance), reach)
            block = (row.interval.account_id, row.interval.end_at.date())
            own = blocks.setdefault(cell, {})
            own[block] = max(score.positive_residual, own.get(block, float("-inf")))
        return cls(m1, blocks, min_blocks, min_accounts)

    def rank(self, row: FeedObservedGrowth) -> FeedTailRank:
        score = self.m1.score(row.interval)
        if not row.complete_order:
            return FeedTailRank("incomplete_publication_order", score, None, None, None, 0, 0)
        band = feed_band(row.nearest_event_distance)
        reach = reach_band(row)
        if reach is None:
            return FeedTailRank("missing_new_post_reach", score, band, None, None, 0, 0)
        reference = self.blocks.get((score.platform, score.age, score.exposure, band, reach), {})
        count = len(reference)
        accounts = len({account for account, _day in reference})
        if score.status != "scored_positive" or score.positive_residual is None:
            return FeedTailRank(score.status, score, band, reach, None, count, accounts)
        if count < self.min_blocks or accounts < self.min_accounts:
            return FeedTailRank("insufficient_calibration", score, band, reach, None, count, accounts)
        rank = (1 + sum(value >= score.positive_residual for value in reference.values())) / (count + 1)
        return FeedTailRank("ranked", score, band, reach, rank, count, accounts)
