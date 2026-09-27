from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.receipt_panel import ObservedGrowth
from anomaly_analysis.v2.temporal_validation import validate_future_m1


DAY = datetime(2026, 9, 1, tzinfo=timezone.utc)


def interval(day: int, account: int, post: int, delta: int = 10, *,
             rounded: bool = False) -> ObservedGrowth:
    start = DAY + timedelta(days=day, hours=12, minutes=post % 10)
    return ObservedGrowth(
        "vk", UUID(f"00000000-0000-4000-8000-{account:012d}"),
        UUID(f"10000000-0000-4000-8000-{post:012d}"),
        start, start + timedelta(minutes=15), 3 * 86400, 900,
        100, 100 + delta, delta, None, rounded, delta == 0 and not rounded,
        "usable",
    )


def test_future_tail_uses_account_day_maxima_and_abstains_without_blocks() -> None:
    train = [interval(0, i % 3 + 1, i, 10 + i % 3) for i in range(24)]
    cal = [interval(1 + day, account, 100 + day * 10 + account, 12 + day)
           for day in range(3) for account in (1, 2, 3)]
    cal += [interval(1, 1, 500, 200)]  # Same account-day: one block, its maximum.
    future = [interval(5, 4, 600, 150), interval(5, 4, 601, 0),
              interval(5, 4, 602, 150, rounded=True)]
    result = validate_future_m1(
        train, cal, future, min_calibration_blocks=9,
    )
    high, zero, rounded = result.holdout
    assert high.status == "ranked" and high.upper_tail_rank == 2 / 10
    assert high.calibration_blocks == 9 and high.calibration_accounts == 3
    assert high.smallest_resolvable_rank == 1 / 10 and high.unseen_account
    assert zero.status == "observed_zero" and zero.upper_tail_rank is None
    assert rounded.status == "unusable_interval" and rounded.upper_tail_rank is None

    sparse = validate_future_m1(train, cal, future, min_calibration_blocks=10)
    assert sparse.holdout[0].status == "insufficient_calibration"
    assert sparse.holdout[0].upper_tail_rank is None


def test_temporal_validation_rejects_leakage_across_calendar_days() -> None:
    train = [interval(0, i % 3 + 1, i) for i in range(24)]
    cal = [interval(1, 1, 101)]
    future = [interval(2, 2, 201)]
    with pytest.raises(ValueError, match="training and calibration"):
        validate_future_m1(train + [interval(1, 1, 99)], cal, future)
    with pytest.raises(ValueError, match="calibration and holdout"):
        validate_future_m1(train, cal, cal)
    with pytest.raises(ValueError, match="nonpositive interval"):
        validate_future_m1(train, cal, [replace(future[0], end_at=future[0].start_at)])


def test_temporal_validation_rejects_same_post_in_different_periods() -> None:
    train = [interval(0, i % 3 + 1, i) for i in range(24)]
    cal = [interval(2, i % 3 + 1, 100 + i) for i in range(24)]
    future = [interval(4, i % 3 + 1, 200 + i) for i in range(24)]
    with pytest.raises(ValueError, match="publication leakage"):
        validate_future_m1(train, cal + [replace(cal[0], publication_id=train[0].publication_id)],
                           future)
    with pytest.raises(ValueError, match="publication leakage"):
        validate_future_m1(train, cal, future + [replace(future[0],
                                                         publication_id=cal[0].publication_id)])
    with pytest.raises(ValueError, match="timezone-naive"):
        validate_future_m1(train, cal, [replace(future[0], start_at=future[0].start_at.replace(
            tzinfo=None))])
