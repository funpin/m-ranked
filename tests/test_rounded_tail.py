from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.rounded_tail import (
    BoundedInterval, BoundedTailReference, summarize_daily_upper_bounds,
)


ACCOUNT = UUID(int=1)
START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def interval(number: int, day: int, before: int, after: int,
             *, unit: int | None = 100, platform: str = "telegram") -> BoundedInterval:
    published = START + timedelta(days=day)
    post = PublishedPost(UUID(int=number), ACCOUNT, published)
    first = SuccessfulRead(post.publication_id, ACCOUNT, published + timedelta(hours=1),
                           before, "rounded", views_display_unit=unit)
    last = SuccessfulRead(post.publication_id, ACCOUNT,
                          published + timedelta(hours=1, minutes=15),
                          after, "rounded", views_display_unit=unit)
    return BoundedInterval(platform, post, first, last)


def test_daily_upper_reference_ranks_only_certain_growth_of_later_post():
    calibration = tuple(interval(100 + day, day, 1000, 1100) for day in range(8))
    reference = BoundedTailReference.fit(calibration, source="successful_poll_receipts")
    unusual = reference.rank(interval(999, 9, 1000, 2000))
    ordinary = reference.rank(interval(998, 9, 1000, 1100))
    assert unusual.status == "research_ranked"
    assert unusual.calibration_days == 8
    assert unusual.calibration_posts == 8
    assert unusual.lower_rate_per_hour < 3200
    assert unusual.lower_rate_per_hour > 3199.999999999
    assert unusual.upper_tail_rank == 1 / 9
    assert ordinary.upper_tail_rank == 1
    assert ordinary.lower_rate_per_hour == 0


def test_missing_precision_abstains_and_sparse_history_does_not_rank():
    calibration = tuple(interval(100 + day, day, 1000, 1100) for day in range(3))
    reference = BoundedTailReference.fit(calibration, source="change_only_shadow")
    missing = reference.rank(interval(999, 9, 1000, 2000, unit=None))
    assert missing.status == "unknown_rounding_precision"
    assert missing.upper_tail_rank is None
    sparse = reference.rank(interval(999, 9, 1000, 2000))
    assert sparse.status == "insufficient_reference"
    assert sparse.calibration_days == 3
    lower_threshold = BoundedTailReference.fit(
        calibration, source="change_only_shadow", min_days=3, min_posts=3,
    )
    assert lower_threshold.rank(interval(999, 9, 1000, 2000)).status == "shadow_only"


def test_reference_rejects_missing_bounds_platform_mixing_and_time_leakage():
    calibration = tuple(interval(100 + day, day, 1000, 1100) for day in range(8))
    with pytest.raises(ValueError, match="unknown_rounding_precision"):
        BoundedTailReference.fit((*calibration, interval(200, 8, 1000, 1200,
                                                        unit=None)),
                                 source="successful_poll_receipts")
    with pytest.raises(ValueError, match="mix platforms"):
        BoundedTailReference.fit((*calibration,
                                  interval(200, 8, 1000, 1200, platform="max")),
                                 source="successful_poll_receipts")
    reference = BoundedTailReference.fit(calibration, source="successful_poll_receipts")
    with pytest.raises(ValueError, match="appears in reference"):
        reference.rank(calibration[0])
    with pytest.raises(ValueError, match="later UTC day"):
        reference.rank(interval(999, 7, 1000, 2000))
    with pytest.raises(ValueError, match="platform differs"):
        reference.rank(interval(999, 9, 1000, 2000, platform="max"))


def test_daily_summary_retains_same_rank_and_source_after_raw_reads_expire():
    calibration = tuple(interval(100 + day, day, 1000, 1100) for day in range(8))
    duplicate_post = calibration[3].post
    later_pair = BoundedInterval(
        "telegram", duplicate_post,
        SuccessfulRead(duplicate_post.publication_id, ACCOUNT,
                       duplicate_post.published_at + timedelta(minutes=90),
                       1100, "rounded", views_display_unit=100),
        SuccessfulRead(duplicate_post.publication_id, ACCOUNT,
                       duplicate_post.published_at + timedelta(minutes=105),
                       1600, "rounded", views_display_unit=100),
    )
    rows = (*calibration, later_pair)
    daily = summarize_daily_upper_bounds(rows, source="successful_poll_receipts")
    assert len(daily) == 8
    assert daily[3].upper_rate_per_hour > 2800
    assert daily[3].upper_rate_per_hour < 2800.000000001
    from_reads = BoundedTailReference.fit(rows, source="successful_poll_receipts")
    from_summary = BoundedTailReference.fit_daily(daily, source="successful_poll_receipts")
    tested = interval(999, 9, 1000, 2000)
    assert from_reads.rank(tested) == from_summary.rank(tested)
    with pytest.raises(ValueError, match="source differs"):
        BoundedTailReference.fit_daily(
            (replace(daily[0], source="change_only_shadow"), *daily[1:]),
            source="successful_poll_receipts",
        )


def test_daily_summary_skips_unknown_precision_without_inventing_zero():
    known = interval(101, 1, 1000, 1200)
    unknown = interval(102, 2, 1000, 1200, unit=None)
    daily = summarize_daily_upper_bounds(
        (known, unknown), source="successful_poll_receipts",
    )
    assert len(daily) == 1
    assert daily[0].publication_id == known.post.publication_id
