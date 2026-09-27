"""Offline M1 validation on future, actually observed receipt intervals.

The baseline, calibration ranks and future evaluation use separate calendar
days. Repeated reads of one account within a day contribute only their largest
positive residual to the calibration reference. Ranks are diagnostics, not
probabilities of manipulation or a public anomaly decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable
from uuid import UUID

from .interval_baseline import ConditionalIntervalBaseline, IntervalScore
from .receipt_panel import ObservedGrowth


CellKey = tuple[str, str, str]
BlockKey = tuple[UUID, date]


@dataclass(frozen=True, slots=True)
class TailRank:
    status: str
    interval: IntervalScore
    upper_tail_rank: float | None
    calibration_blocks: int
    calibration_accounts: int
    smallest_resolvable_rank: float | None
    unseen_account: bool


class BlockedTailReference:
    """Empirical upper tail of account-day maxima within each M1 cell."""

    def __init__(
        self,
        baseline: ConditionalIntervalBaseline,
        blocks: dict[CellKey, dict[BlockKey, float]],
        *,
        min_blocks: int,
        min_accounts: int,
    ) -> None:
        self.baseline = baseline
        self.blocks = blocks
        self.min_blocks = min_blocks
        self.min_accounts = min_accounts

    @classmethod
    def fit(
        cls,
        baseline: ConditionalIntervalBaseline,
        calibration: Iterable[ObservedGrowth],
        *,
        min_blocks: int = 20,
        min_accounts: int = 3,
    ) -> "BlockedTailReference":
        if min_blocks < 2 or min_accounts < 2:
            raise ValueError("calibration requires at least two blocks and accounts")
        blocks: dict[CellKey, dict[BlockKey, float]] = {}
        for row in calibration:
            result = baseline.score(row)
            if result.status != "scored_positive" or result.positive_residual is None:
                continue
            cell = (result.platform, result.age, result.exposure)
            block = (row.account_id, row.end_at.date())
            own = blocks.setdefault(cell, {})
            own[block] = max(result.positive_residual, own.get(block, float("-inf")))
        return cls(baseline, blocks, min_blocks=min_blocks, min_accounts=min_accounts)

    def rank(self, row: ObservedGrowth) -> TailRank:
        result = self.baseline.score(row)
        cell = (result.platform, result.age, result.exposure)
        reference = self.blocks.get(cell, {})
        block_count = len(reference)
        account_count = len({account for account, _ in reference})
        fitted = self.baseline.cells.get(cell)
        unseen = fitted is not None and str(row.account_id) not in fitted.account_effects
        resolution = 1 / (block_count + 1) if block_count else None
        if result.status != "scored_positive" or result.positive_residual is None:
            return TailRank(result.status, result, None, block_count, account_count,
                            resolution, unseen)
        if block_count < self.min_blocks or account_count < self.min_accounts:
            return TailRank("insufficient_calibration", result, None, block_count,
                            account_count, resolution, unseen)
        tail = (1 + sum(value >= result.positive_residual for value in reference.values())) / (
            block_count + 1
        )
        return TailRank("ranked", result, tail, block_count, account_count,
                        resolution, unseen)


@dataclass(frozen=True, slots=True)
class TemporalM1Validation:
    baseline: ConditionalIntervalBaseline
    reference: BlockedTailReference
    holdout: tuple[TailRank, ...]


def validate_future_m1(
    training: Iterable[ObservedGrowth],
    calibration: Iterable[ObservedGrowth],
    holdout: Iterable[ObservedGrowth],
    *,
    min_fit_intervals: int = 20,
    min_fit_accounts: int = 2,
    min_calibration_blocks: int = 20,
    min_calibration_accounts: int = 3,
) -> TemporalM1Validation:
    """Reject split leakage and report ranks/abstentions on a future holdout.

    Boundaries are strict calendar dates so one account-day cannot straddle
    fitting, calibration and evaluation. The caller must still report eligible
    posts that produced no receipt pair; this function cannot infer them.
    """
    train, cal, future = tuple(training), tuple(calibration), tuple(holdout)
    if not train or not cal or not future:
        raise ValueError("training, calibration and holdout must all be nonempty")
    for name, rows in (("training", train), ("calibration", cal), ("holdout", future)):
        if any(row.start_at.tzinfo is None or row.start_at.utcoffset() is None
               or row.end_at.tzinfo is None or row.end_at.utcoffset() is None
               for row in rows):
            raise ValueError(f"{name} contains a timezone-naive interval")
        if any(row.start_at >= row.end_at for row in rows):
            raise ValueError(f"{name} contains a nonpositive interval")
    def utc_day(value: datetime) -> date:
        return value.astimezone(timezone.utc).date()

    if max(utc_day(row.end_at) for row in train) >= min(utc_day(row.start_at) for row in cal):
        raise ValueError("training and calibration must occupy separate ordered days")
    if max(utc_day(row.end_at) for row in cal) >= min(utc_day(row.start_at) for row in future):
        raise ValueError("calibration and holdout must occupy separate ordered days")
    post_sets = [
        {row.publication_id for row in rows}
        for rows in (train, cal, future)
    ]
    if (post_sets[0] & post_sets[1] or post_sets[0] & post_sets[2]
            or post_sets[1] & post_sets[2]):
        raise ValueError("publication leakage across fit, calibration and holdout")
    baseline = ConditionalIntervalBaseline.fit(
        train, min_intervals=min_fit_intervals, min_accounts=min_fit_accounts,
    )
    reference = BlockedTailReference.fit(
        baseline, cal, min_blocks=min_calibration_blocks,
        min_accounts=min_calibration_accounts,
    )
    return TemporalM1Validation(baseline, reference,
                                tuple(reference.rank(row) for row in future))
