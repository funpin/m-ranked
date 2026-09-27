"""Conservative view-growth bounds from successful exact or compact reads.

The compact-display bound permits up to one visible unit in either direction.
It covers ordinary nearest-unit rounding and truncation, but still needs a
future exact-versus-public-Web overlap check before it can support alerts.
Unknown historical precision always abstains.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from anomaly_analysis.neighbor_exposure import SuccessfulRead


@dataclass(frozen=True, slots=True)
class ViewRange:
    lower: int
    upper: int


@dataclass(frozen=True, slots=True)
class BoundedViewGrowth:
    status: str
    lower_delta: int | None
    upper_delta: int | None
    positive_growth_guaranteed: bool
    exact_zero_observed: bool


def view_range(read: SuccessfulRead) -> ViewRange | None:
    count = read.views_count
    if count is None or read.interval_uncertain:
        return None
    if read.views_quality == "exact":
        return ViewRange(count, count)
    if read.views_quality == "rounded" and read.views_display_unit is not None:
        unit = read.views_display_unit
        if count % unit != 0:
            return None
        return ViewRange(max(0, count - unit), count + unit)
    return None


def bounded_view_growth(
    before: SuccessfulRead, after: SuccessfulRead, *, max_gap: timedelta,
) -> BoundedViewGrowth:
    if before.publication_id != after.publication_id or before.account_id != after.account_id:
        raise ValueError("reads must belong to the same post and account")
    if max_gap <= timedelta(0) or before.observed_at >= after.observed_at:
        raise ValueError("read gap must be positive")
    if after.observed_at - before.observed_at > max_gap:
        return BoundedViewGrowth("excessive_gap", None, None, False, False)
    if before.views_count is None or after.views_count is None:
        return BoundedViewGrowth("missing_views", None, None, False, False)
    if before.interval_uncertain or after.interval_uncertain:
        return BoundedViewGrowth("uncertain_interval", None, None, False, False)
    if after.views_count < before.views_count:
        return BoundedViewGrowth("negative_correction_or_reset", None, None, False, False)
    first, last = view_range(before), view_range(after)
    if first is None or last is None:
        return BoundedViewGrowth("unknown_rounding_precision", None, None, False, False)
    lower = last.lower - first.upper
    upper = last.upper - first.lower
    return BoundedViewGrowth(
        "bounded", lower, upper, lower > 0,
        lower == upper == 0 and before.views_quality == after.views_quality == "exact",
    )
