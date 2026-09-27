"""Feed-conditioned M2 keeps unlike exposure windows apart."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from math import log1p
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import NeighborInterval, SuccessfulRead
from anomaly_analysis.v2.event_adjusted_tail import (
    EventAdjustedTail, FeedObservedGrowth, feed_observation, validate_future_m2,
)
from anomaly_analysis.v2.interval_baseline import ConditionalCell, ConditionalIntervalBaseline
from anomaly_analysis.v2.receipt_panel import ObservedGrowth


ACCOUNTS = (UUID("40000000-0000-4000-8000-000000000001"),
            UUID("40000000-0000-4000-8000-000000000002"))
M1 = ConditionalIntervalBaseline({
    ("telegram", "2-4d", "30m-2h"): ConditionalCell(
        "telegram", "2-4d", "30m-2h", 40, 2, 0, log1p(10), 1, {}),
})


def observed(account: UUID, day: int, delta: int, distance: int | None,
             *, complete: bool = True, new_views: int | None = 200) -> FeedObservedGrowth:
    start = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
    growth = ObservedGrowth("telegram", account, UUID(int=day + account.int % 100),
                            start, start + timedelta(hours=1), 3 * 86400, 3600,
                            1000, 1000 + delta, delta, log1p(1000 + delta) - log1p(1000),
                            False, False, "usable")
    return FeedObservedGrowth(growth, distance, complete,
                              new_views if distance is not None else 0)


def test_same_m1_residual_has_different_tail_after_feed_position_conditioning():
    cal = (observed(ACCOUNTS[0], 15, 100, 1), observed(ACCOUNTS[1], 16, 120, 1),
           observed(ACCOUNTS[0], 15, 10, None), observed(ACCOUNTS[1], 16, 20, None))
    model = EventAdjustedTail.fit(M1, cal, min_blocks=2, min_accounts=2)
    with_new_post = model.rank(observed(ACCOUNTS[0], 18, 50, 1))
    without_new_post = model.rank(observed(ACCOUNTS[0], 18, 50, None))
    assert with_new_post.status == without_new_post.status == "ranked"
    assert with_new_post.upper_tail_rank == 1
    assert without_new_post.upper_tail_rank == 1 / 3


def test_same_feed_position_is_conditioned_on_measured_new_post_reach():
    cal = (observed(ACCOUNTS[0], 15, 100, 1, new_views=50),
           observed(ACCOUNTS[1], 16, 120, 1, new_views=50),
           observed(ACCOUNTS[0], 15, 10, 1, new_views=200),
           observed(ACCOUNTS[1], 16, 20, 1, new_views=200))
    model = EventAdjustedTail.fit(M1, cal, min_blocks=2, min_accounts=2)
    low = model.rank(observed(ACCOUNTS[0], 18, 50, 1, new_views=50))
    medium = model.rank(observed(ACCOUNTS[0], 18, 50, 1, new_views=200))
    assert low.status == medium.status == "ranked"
    assert low.upper_tail_rank == 1
    assert medium.upper_tail_rank == 1 / 3


def test_missing_order_and_sparse_depth_abstain():
    cal = (observed(ACCOUNTS[0], 15, 100, 1), observed(ACCOUNTS[1], 16, 120, 1))
    model = EventAdjustedTail.fit(M1, cal, min_blocks=2, min_accounts=2)
    assert model.rank(observed(ACCOUNTS[0], 18, 50, 1, complete=False)).status == \
        "incomplete_publication_order"
    assert model.rank(observed(ACCOUNTS[0], 18, 50, 2)).status == \
        "insufficient_calibration"
    assert model.rank(observed(ACCOUNTS[0], 18, 50, 1, new_views=None)).status == \
        "missing_new_post_reach"
    assert model.rank(observed(ACCOUNTS[0], 18, 50, 1, new_views=900)).status == \
        "insufficient_calibration"


def test_feed_feature_must_match_the_same_successful_read_pair():
    row = observed(ACCOUNTS[0], 18, 50, 1).interval
    exposure = NeighborInterval(row.start_at, row.end_at, 3600, 50, "usable",
                                (UUID(int=999),), 1, False)
    assert feed_observation(row, exposure).nearest_event_distance == 1
    assert feed_observation(row, exposure).new_post_views is None
    event_read = SuccessfulRead(UUID(int=999), row.account_id, row.end_at, 220, "exact")
    assert feed_observation(row, exposure, {UUID(int=999): event_read}).new_post_views == 220
    stale = NeighborInterval(row.start_at - timedelta(minutes=1), row.end_at, 3660, 50,
                             "usable", (UUID(int=999),), 1, False)
    try:
        feed_observation(row, stale)
    except ValueError:
        pass
    else:
        raise AssertionError("different read pairs cannot be joined")


def test_future_m2_uses_same_holdout_as_m1_and_rejects_time_leakage():
    train = (observed(ACCOUNTS[0], 10, 10, None).interval,
             observed(ACCOUNTS[1], 10, 20, None).interval)
    cal = (observed(ACCOUNTS[0], 15, 100, 1), observed(ACCOUNTS[1], 16, 120, 1),
           observed(ACCOUNTS[0], 15, 10, None), observed(ACCOUNTS[1], 16, 20, None))
    future = (observed(ACCOUNTS[0], 18, 50, 1), observed(ACCOUNTS[0], 18, 50, None),
              observed(ACCOUNTS[1], 18, 50, 1, new_views=None))
    result = validate_future_m2(train, cal, future, min_fit_intervals=2,
                                min_calibration_blocks=2, min_calibration_accounts=2)
    assert [row.m1.status for row in result.holdout] == ["ranked"] * 3
    assert [row.m2.status for row in result.holdout] == [
        "ranked", "ranked", "missing_new_post_reach"]
    assert result.paired_ranked_count == 2
    assert result.holdout[0].m2.upper_tail_rank == 1
    assert result.holdout[1].m2.upper_tail_rank == 1 / 3
    with pytest.raises(ValueError, match="training and calibration"):
        validate_future_m2(train + (cal[0].interval,), cal, future,
                           min_fit_intervals=2, min_calibration_blocks=2,
                           min_calibration_accounts=2)


def test_vk_event_tail_abstains_until_its_separate_late_model_exists():
    model = EventAdjustedTail.fit(M1, (observed(ACCOUNTS[0], 15, 100, 1),
                                       observed(ACCOUNTS[1], 16, 120, 1)),
                                  min_blocks=2, min_accounts=2)
    vk = observed(ACCOUNTS[0], 18, 50, 1)
    assert model.rank(replace(vk, interval=replace(vk.interval, platform="vk"))).status == \
        "unsupported_platform"
