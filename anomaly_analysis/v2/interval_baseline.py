"""Research M1: a platform/age/exposure baseline for *observed* intervals.

This is deliberately an uncalibrated score. Fit and evaluation must use
different calendar periods and account blocks before any public decision.
Missing receipts, rounded counters, corrections and long gaps never become
zero-growth examples. M2 adds publication events after this background model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import expm1, log1p
from statistics import median
from typing import Iterable

from .receipt_panel import ObservedGrowth


def age_band(seconds: float) -> str:
    if seconds < 6 * 3600:
        return "0-6h"
    if seconds < 24 * 3600:
        return "6-24h"
    if seconds < 2 * 86400:
        return "1-2d"
    if seconds < 4 * 86400:
        return "2-4d"
    if seconds < 7 * 86400:
        return "4-7d"
    return "7d+"


def exposure_band(seconds: float) -> str:
    if seconds <= 30 * 60:
        return "<=30m"
    if seconds <= 2 * 3600:
        return "30m-2h"
    if seconds <= 8 * 3600:
        return "2-8h"
    return "8h+"


@dataclass(frozen=True, slots=True)
class ConditionalCell:
    platform: str
    age: str
    exposure: str
    interval_count: int
    account_count: int
    exact_zero_share: float
    positive_center: float | None
    positive_scale: float | None
    account_effects: dict[str, float]


@dataclass(frozen=True, slots=True)
class IntervalScore:
    status: str
    platform: str
    age: str
    exposure: str
    displayed_delta: int | None
    observed_per_hour: float | None
    expected_positive_per_hour: float | None
    positive_residual: float | None
    reference_intervals: int
    reference_accounts: int


class ConditionalIntervalBaseline:
    """Robust first stage for fit on a past receipt cohort, per platform.

    Separate 2-4 and 4-7 day VK cells leave room for its recommendation wave.
    Sparse cells abstain instead of borrowing Telegram or another age window.
    Exact zeros contribute to exposure diagnostics but are never negative
    evidence about viewers or a proof that another post did not grow.
    """

    def __init__(self, cells: dict[tuple[str, str, str], ConditionalCell]):
        self.cells = cells

    @classmethod
    def fit(cls, intervals: Iterable[ObservedGrowth], *, min_intervals: int = 20,
            min_accounts: int = 2) -> "ConditionalIntervalBaseline":
        if min_intervals < 2 or min_accounts < 2:
            raise ValueError("fit requires at least two intervals and accounts")
        groups: dict[tuple[str, str, str], list[ObservedGrowth]] = {}
        for interval in intervals:
            if not interval.usable or interval.rounded or interval.displayed_delta_views is None:
                continue
            key = (interval.platform, age_band(interval.age_seconds),
                   exposure_band(interval.elapsed_seconds))
            groups.setdefault(key, []).append(interval)

        cells = {}
        for key, rows in groups.items():
            accounts = {str(row.account_id) for row in rows}
            if len(rows) < min_intervals or len(accounts) < min_accounts:
                continue
            positive = [row for row in rows if row.displayed_delta_views > 0]
            values = [log1p(row.displayed_delta_views / (row.elapsed_seconds / 3600))
                      for row in positive]
            center = median(values) if values else None
            effects: dict[str, float] = {}
            if center is not None:
                for account in accounts:
                    own = [log1p(row.displayed_delta_views / (row.elapsed_seconds / 3600))
                           for row in positive if str(row.account_id) == account]
                    if own:
                        effects[account] = len(own) / (len(own) + 8) * (median(own) - center)
            errors = [abs(value - center - effects.get(str(row.account_id), 0))
                      for value, row in zip(values, positive, strict=True)] if center is not None else []
            cells[key] = ConditionalCell(
                *key, len(rows), len(accounts), (len(rows) - len(positive)) / len(rows),
                center, max(0.25, 1.4826 * median(errors)) if errors else None, effects,
            )
        return cls(cells)

    def score(self, interval: ObservedGrowth) -> IntervalScore:
        age = age_band(interval.age_seconds)
        exposure = exposure_band(interval.elapsed_seconds)
        cell = self.cells.get((interval.platform, age, exposure))
        common = (interval.platform, age, exposure, interval.displayed_delta_views)
        if not interval.usable or interval.rounded or interval.displayed_delta_views is None:
            return IntervalScore("unusable_interval", *common, None, None, None, 0, 0)
        if cell is None or cell.positive_center is None or cell.positive_scale is None:
            return IntervalScore("insufficient_reference", *common, None, None, None,
                                 cell.interval_count if cell else 0,
                                 cell.account_count if cell else 0)
        rate = interval.displayed_delta_views / (interval.elapsed_seconds / 3600)
        expected_log = cell.positive_center + cell.account_effects.get(str(interval.account_id), 0)
        return IntervalScore(
            "observed_zero" if interval.exact_zero_observed else "scored_positive",
            *common, rate, max(0.0, expm1(expected_log)),
            (log1p(rate) - expected_log) / cell.positive_scale if rate > 0 else None,
            cell.interval_count, cell.account_count,
        )
