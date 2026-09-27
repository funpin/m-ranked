from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.event_adjusted_tail import (
    FeedObservedGrowth, FeedTailRank, PairedTailRank,
)
from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.cohort_coverage import (
    CheckpointCoverage, PostCoverage, audit_cohort_coverage,
)
from anomaly_analysis.v2.interval_baseline import IntervalScore, age_band, exposure_band
from anomaly_analysis.v2.post_tail import Checkpoint, score_post
from anomaly_analysis.v2.receipt_panel import ObservedGrowth
from anomaly_analysis.v2.temporal_validation import TailRank


ACCOUNT = UUID(int=1)
POST = UUID(int=2)
START = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
CHECKS = (Checkpoint("1h", 3600, 600), Checkpoint("6h", 21600, 600))


def score(*args):
    rows, plan = args[1], args[2]
    checks = []
    for item in plan:
        candidates = [row.interval for row, _paired in rows
                      if abs(row.interval.age_seconds + row.interval.elapsed_seconds
                             - item.age_seconds) <= item.tolerance_seconds]
        chosen = min(candidates, key=lambda interval: (
            abs(interval.age_seconds + interval.elapsed_seconds - item.age_seconds),
            interval.end_at,
        )) if candidates else None
        checks.append(CheckpointCoverage(item.name,
                                         "usable" if chosen else "missing_read_pair", chosen))
    coverage = PostCoverage(POST, ACCOUNT, "max",
                            "complete" if all(check.interval for check in checks)
                            else "insufficient_data", tuple(checks))
    return score_post(*args, source="complete_receipts", coverage=coverage)


def observation(age_end: int, m1_rank: float | None, m2_rank: float | None = None,
                *, event: bool = False, m2_status: str = "ranked", delta: int = 20):
    end = START + timedelta(seconds=age_end)
    interval = ObservedGrowth("max", ACCOUNT, POST, end - timedelta(minutes=5), end,
                              age_end - 300, 300, 100, 100 + delta, delta, None,
                              False, delta == 0, "usable")
    score = IntervalScore("observed_zero" if delta == 0 else "scored_positive",
                          "max", "0-6h", "<=30m", delta, 240, 20, 1, 100, 5)
    m1_status = "observed_zero" if delta == 0 else "ranked"
    m1 = TailRank(m1_status, score, m1_rank, 40, 5, 1 / 41, False)
    m2 = FeedTailRank(m2_status, score, "next_post" if event else None,
                      "high_reach" if event else None, m2_rank, 30, 4)
    return FeedObservedGrowth(interval, 1 if event else None, True,
                              200 if event else 0), PairedTailRank(interval, m1, m2)


def test_context_only_reduces_evidence_and_post_bound_counts_planned_looks():
    event = observation(3600, .01, .40, event=True)
    later = observation(21600, .02)
    result = score(POST, (event, later), CHECKS)
    assert result.status == "research_ranked"
    assert result.evidence[0].context_reduced
    assert result.evidence[0].interval_rank == .40
    assert result.minimum_interval_rank == .02
    assert result.smallest_resolvable_post_rank == 2 / 41
    assert result.m1_post_rank_bound == .02
    assert result.post_rank_bound == .04


def test_new_event_cannot_create_signal_when_m2_rank_is_smaller():
    event = observation(3600, .80, .01, event=True)
    later = observation(21600, .50)
    result = score(POST, (event, later), CHECKS)
    assert result.evidence[0].interval_rank == .80
    assert result.m1_post_rank_bound == 1.0
    assert result.post_rank_bound == 1.0


def test_checkpoint_selection_uses_age_not_most_extreme_rank():
    closest = observation(3600, .30)
    tempting = observation(3200, .001)
    later = observation(21600, .20)
    result = score(POST, (tempting, later, closest), CHECKS)
    assert result.status == "research_ranked"
    assert result.evidence[0].interval_rank == .30
    assert result.post_rank_bound == .40


def test_missing_or_unranked_checkpoint_abstains():
    first = observation(3600, .01)
    assert score(POST, (first,), CHECKS).status == "insufficient_data"
    sparse = observation(21600, .02, event=True, m2_status="insufficient_calibration")
    result = score(POST, (first, sparse), CHECKS)
    assert result.status == "insufficient_data"
    assert result.post_rank_bound is None
    assert "m2:insufficient_calibration" in result.reason


def test_incomplete_publication_order_cannot_be_called_no_new_post():
    first = observation(3600, .01)
    later = observation(21600, .20)
    unknown_order = replace(first[0], complete_order=False)
    result = score(POST, ((unknown_order, first[1]), later), CHECKS)
    assert result.status == "insufficient_data"
    assert result.post_rank_bound is None
    assert "incomplete_publication_order" in result.reason


def test_observed_zero_is_neutral_not_missing():
    first = observation(3600, None, event=True, delta=0, m2_status="observed_zero")
    later = observation(21600, .20)
    result = score(POST, (first, later), CHECKS)
    assert result.status == "research_ranked"
    assert result.evidence[0].interval_rank == 1.0
    assert result.post_rank_bound == .40


def test_rejects_mixed_or_mismatched_pairs_and_overlapping_plan():
    first = observation(3600, .01)
    later = observation(21600, .20)
    with pytest.raises(ValueError, match="duplicate"):
        score(POST, (first, first, later), CHECKS)
    with pytest.raises(ValueError, match="mixed publications"):
        score(POST, (first, (replace(later[0], interval=replace(
            later[0].interval, publication_id=UUID(int=3))), later[1])), CHECKS)
    with pytest.raises(ValueError, match="rank and observed interval"):
        score(POST, (first, (replace(later[0], interval=replace(
            later[0].interval, displayed_delta_views=999)), later[1])), CHECKS)
    with pytest.raises(ValueError, match="rank and observed interval"):
        score(POST, (first, (later[0], replace(later[1], interval=first[0].interval))), CHECKS)
    with pytest.raises(ValueError, match="disjoint"):
        score(POST, (first, later), (Checkpoint("a", 3600, 3000),
                                         Checkpoint("b", 7200, 3000)))


def test_change_only_archive_cannot_return_a_full_receipt_status():
    result = score_post(POST, (observation(3600, .01), observation(21600, .20)),
                        CHECKS, source="change_only_shadow")
    assert result.status == "shadow_only"
    assert result.post_rank_bound == .02


def test_reference_resolution_is_reported_after_multiple_checks():
    first = observation(3600, .10)
    later = observation(21600, .20)
    sparse = tuple((row, replace(paired, m1=replace(
        paired.m1, smallest_resolvable_rank=.10))) for row, paired in (first, later))
    result = score(POST, sparse, CHECKS)
    assert result.smallest_resolvable_post_rank == .20
    assert result.post_rank_bound == .20


def test_complete_receipts_require_matching_full_frame_coverage():
    rows = (observation(3600, .01), observation(21600, .20))
    good = PostCoverage(POST, ACCOUNT, "max", "complete",
                        tuple(CheckpointCoverage(check.name, "usable", row.interval)
                              for check, (row, _paired) in zip(CHECKS, rows, strict=True)))
    with pytest.raises(ValueError, match="cohort coverage audit"):
        score_post(POST, rows, CHECKS, source="complete_receipts")
    wrong = replace(good, publication_id=UUID(int=3))
    with pytest.raises(ValueError, match="another publication"):
        score_post(POST, rows, CHECKS, source="complete_receipts", coverage=wrong)
    incomplete = replace(wrong, publication_id=POST, status="insufficient_data")
    result = score_post(POST, rows, CHECKS, source="complete_receipts",
                        coverage=incomplete)
    assert result.status == "insufficient_data"
    assert result.reason == "incomplete_receipt_coverage"
    assert result.post_rank_bound is None
    with pytest.raises(ValueError, match="account or platform"):
        score_post(POST, rows, CHECKS, source="complete_receipts",
                   coverage=replace(good, account_id=UUID(int=4)))
    with pytest.raises(ValueError, match="audited receipt pair"):
        score_post(POST, rows, CHECKS, source="complete_receipts",
                   coverage=replace(good, checkpoints=(
                       replace(good.checkpoints[0], interval=replace(
                           good.checkpoints[0].interval, before_views=99)),
                       good.checkpoints[1],
                   )))
    with pytest.raises(ValueError, match="no usable audited interval"):
        score_post(POST, rows, CHECKS, source="complete_receipts",
                   coverage=replace(good, checkpoints=(
                       replace(good.checkpoints[0], interval=None), good.checkpoints[1],
                   )))


def test_real_receipt_audit_binds_the_post_score_to_the_full_cohort():
    unread = UUID(int=3)
    publications = (PublishedPost(POST, ACCOUNT, START),
                    PublishedPost(unread, ACCOUNT, START))
    reads = tuple(SuccessfulRead(POST, ACCOUNT, START + timedelta(minutes=minute),
                                 views, "exact")
                  for minute, views in ((45, 100), (60, 120), (345, 150), (360, 170)))
    coverage = audit_cohort_coverage(
        publications, reads, {ACCOUNT: "max"}, frozenset({ACCOUNT}), CHECKS,
        cohort_start=START, cohort_end=START + timedelta(days=1),
        observed_through=START + timedelta(hours=8),
        max_gap_by_platform={"max": timedelta(minutes=30)},
        source="successful_poll_receipts",
    )
    assert [row.status for row in coverage] == ["complete", "insufficient_data"]
    rows = []
    for check, rank in zip(coverage[0].checkpoints, (.01, .20), strict=True):
        interval = check.interval
        score = IntervalScore("scored_positive", interval.platform,
                              age_band(interval.age_seconds),
                              exposure_band(interval.elapsed_seconds),
                              interval.displayed_delta_views, 80, 20, 1, 100, 5)
        m1 = TailRank("ranked", score, rank, 40, 5, 1 / 41, False)
        m2 = FeedTailRank("ranked", score, None, None, rank, 30, 4)
        rows.append((FeedObservedGrowth(interval, None, True, 0),
                     PairedTailRank(interval, m1, m2)))
    result = score_post(POST, rows, CHECKS, source="complete_receipts",
                        coverage=coverage[0])
    assert result.status == "research_ranked"
    assert result.post_rank_bound == .02
    with pytest.raises(ValueError, match="audited receipt pair"):
        tampered = replace(rows[0][0].interval, before_views=99)
        score_post(POST, ((replace(rows[0][0], interval=tampered),
                           replace(rows[0][1], interval=tampered)), rows[1]),
                   CHECKS, source="complete_receipts", coverage=coverage[0])
