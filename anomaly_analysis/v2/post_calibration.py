"""Calibrate a fixed-horizon post statistic on earlier account-day blocks.

This is a research rank, not a probability of manipulation. Complete receipts
and change-only archive scores remain separate; archive ranks are shadow-only.
The calibration cohort must be later than the interval model's reference and
earlier than the tested post.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Literal
from uuid import UUID

from .post_tail import PostTailResult


@dataclass(frozen=True, slots=True)
class PostRankInput:
    account_id: UUID
    platform: str
    published_at: datetime
    score_available_at: datetime
    model_id: str
    score: PostTailResult


@dataclass(frozen=True, slots=True)
class CalibratedPostRank:
    status: str
    upper_tail_rank: float | None
    smallest_resolvable_rank: float | None
    calibration_blocks: int
    calibration_accounts: int
    calibration_days: int


Source = Literal["complete_receipts", "change_only_shadow"]


def _plan(row: PostRankInput, source: Source) -> tuple[str, ...]:
    if row.published_at.tzinfo is None or row.published_at.utcoffset() is None:
        raise ValueError("post publication time must include a timezone")
    if row.score_available_at.tzinfo is None or row.score_available_at.utcoffset() is None:
        raise ValueError("post score availability time must include a timezone")
    if row.score_available_at < row.published_at:
        raise ValueError("post score cannot be available before publication")
    expected = "research_ranked" if source == "complete_receipts" else "shadow_only"
    if row.score.status != expected or row.score.minimum_interval_rank is None:
        raise ValueError(f"post calibration requires {expected} scores for {source}")
    if not row.model_id.strip():
        raise ValueError("post score must identify its fitted interval model")
    names = tuple(check.name for check in row.score.evidence)
    if len(names) != row.score.planned_checks or len(set(names)) != len(names):
        raise ValueError("post score has an incomplete checkpoint plan")
    if not 0 < row.score.minimum_interval_rank <= 1:
        raise ValueError("post score rank must be in (0, 1]")
    return names


class PostTailCalibration:
    """Compare a post's raw best checkpoint with earlier account-day minima.

    The fixed checkpoint plan is repeated in each calibration post. Empirical
    ranking therefore accounts for repeated looks without first clipping a
    Bonferroni bound at one. One extreme per account-day limits the reference
    contribution of prolific accounts and repeated posts on the same day.
    """

    def __init__(
        self, platform: str, plan: tuple[str, ...], model_id: str, source: Source,
        block_minima: dict[tuple[UUID, date], float],
        publication_ids: frozenset[UUID], latest_day: date,
        latest_score_available_at: datetime,
        *, min_blocks: int, min_accounts: int, min_days: int,
    ) -> None:
        self.platform = platform
        self.plan = plan
        self.model_id = model_id
        self.source = source
        self.block_minima = block_minima
        self.publication_ids = publication_ids
        self.latest_day = latest_day
        self.latest_score_available_at = latest_score_available_at
        self.min_blocks = min_blocks
        self.min_accounts = min_accounts
        self.min_days = min_days

    @classmethod
    def fit(
        cls, rows: Iterable[PostRankInput], *, source: Source,
        interval_reference_through: datetime,
        min_blocks: int = 40, min_accounts: int = 3, min_days: int = 7,
    ) -> "PostTailCalibration":
        if min_blocks < 2 or min_accounts < 2 or min_days < 2:
            raise ValueError("post calibration needs at least two blocks, accounts and days")
        if source not in {"complete_receipts", "change_only_shadow"}:
            raise ValueError("unknown post score source")
        if (interval_reference_through.tzinfo is None
                or interval_reference_through.utcoffset() is None):
            raise ValueError("interval reference cutoff must include a timezone")
        items = tuple(rows)
        if not items:
            raise ValueError("post calibration cohort cannot be empty")
        platform, plan = items[0].platform, _plan(items[0], source)
        model_id = items[0].model_id
        minima: dict[tuple[UUID, date], float] = {}
        ids: set[UUID] = set()
        for row in items:
            if row.platform != platform or _plan(row, source) != plan or row.model_id != model_id:
                raise ValueError("post calibration cannot mix platforms, plans or fitted models")
            if row.published_at.astimezone(timezone.utc) <= interval_reference_through.astimezone(timezone.utc):
                raise ValueError("post calibration must follow the interval model reference")
            if row.score.publication_id in ids:
                raise ValueError("duplicate publication in post calibration cohort")
            ids.add(row.score.publication_id)
            day = row.published_at.astimezone(timezone.utc).date()
            block = (row.account_id, day)
            minima[block] = min(minima.get(block, 1.0), row.score.minimum_interval_rank)
        return cls(platform, plan, model_id, source, minima, frozenset(ids),
                   max(day for _account, day in minima),
                   max(row.score_available_at for row in items),
                   min_blocks=min_blocks, min_accounts=min_accounts, min_days=min_days)

    def rank(self, row: PostRankInput) -> CalibratedPostRank:
        if (row.platform != self.platform or _plan(row, self.source) != self.plan
                or row.model_id != self.model_id):
            raise ValueError("tested post has another platform, checkpoint plan or fitted model")
        if row.score.publication_id in self.publication_ids:
            raise ValueError("post appears in its calibration cohort")
        if row.published_at.astimezone(timezone.utc).date() <= self.latest_day:
            raise ValueError("tested post must follow calibration on a later UTC day")
        if row.published_at <= self.latest_score_available_at:
            raise ValueError("tested post predates a completed calibration score")
        blocks = len(self.block_minima)
        accounts = len({account for account, _day in self.block_minima})
        days = len({day for _account, day in self.block_minima})
        resolution = 1 / (blocks + 1)
        if (blocks < self.min_blocks or accounts < self.min_accounts
                or days < self.min_days):
            return CalibratedPostRank("insufficient_calibration", None, resolution,
                                      blocks, accounts, days)
        tail = (1 + sum(bound <= row.score.minimum_interval_rank
                        for bound in self.block_minima.values())) / (blocks + 1)
        status = "research_ranked" if self.source == "complete_receipts" else "shadow_only"
        return CalibratedPostRank(status, tail, resolution,
                                  blocks, accounts, days)
