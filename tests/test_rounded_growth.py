from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import SuccessfulRead
from anomaly_analysis.v2.rounded_growth import bounded_view_growth, view_range


POST = UUID(int=1)
ACCOUNT = UUID(int=2)
START = datetime(2026, 9, 27, tzinfo=timezone.utc)


def read(minutes: int, count: int | None, quality: str = "rounded",
         unit: int | None = 100, *, uncertain: bool = False) -> SuccessfulRead:
    return SuccessfulRead(POST, ACCOUNT, START + timedelta(minutes=minutes),
                          count, quality, uncertain, unit)


def test_compact_counter_growth_uses_lower_and_upper_bounds():
    first, last = read(0, 1200), read(15, 1600)
    assert view_range(first).lower == 1100
    result = bounded_view_growth(first, last, max_gap=timedelta(minutes=30))
    assert result.status == "bounded"
    assert (result.lower_delta, result.upper_delta) == (200, 600)
    assert result.positive_growth_guaranteed
    assert not result.exact_zero_observed


def test_unchanged_compact_display_does_not_become_exact_zero_or_positive_growth():
    result = bounded_view_growth(read(0, 1200), read(15, 1200),
                                 max_gap=timedelta(minutes=30))
    assert (result.lower_delta, result.upper_delta) == (-200, 200)
    assert not result.positive_growth_guaranteed
    assert not result.exact_zero_observed


def test_exact_reads_remain_exact_and_unknown_legacy_precision_abstains():
    exact = bounded_view_growth(read(0, 10, "exact", None),
                                read(15, 10, "exact", None),
                                max_gap=timedelta(minutes=30))
    assert (exact.lower_delta, exact.upper_delta) == (0, 0)
    assert exact.exact_zero_observed
    legacy = bounded_view_growth(read(0, 1200, unit=None), read(15, 1600),
                                 max_gap=timedelta(minutes=30))
    assert legacy.status == "unknown_rounding_precision"
    assert legacy.lower_delta is None


def test_untrusted_or_out_of_order_reads_cannot_be_scored():
    assert bounded_view_growth(read(0, 1200), read(1, 1600),
                               max_gap=timedelta(minutes=30)).status == "short_gap"
    assert bounded_view_growth(read(0, 1200, "exact", None),
                               read(1, 1600, "exact", None),
                               max_gap=timedelta(minutes=30)).status == "bounded"
    assert bounded_view_growth(read(0, 1200), read(45, 1600),
                               max_gap=timedelta(minutes=30)).status == "excessive_gap"
    assert bounded_view_growth(read(0, 1200), read(15, 1600, uncertain=True),
                               max_gap=timedelta(minutes=30)).status == "uncertain_interval"
    assert bounded_view_growth(read(0, 1600), read(15, 1200),
                               max_gap=timedelta(minutes=30)).status == "negative_correction_or_reset"
    with pytest.raises(ValueError, match="display unit"):
        read(0, 1200, unit=7)
