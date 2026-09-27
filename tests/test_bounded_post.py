from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.bounded_post import score_bounded_post
from anomaly_analysis.v2.cohort_coverage import audit_cohort_coverage
from anomaly_analysis.v2.post_tail import Checkpoint
from anomaly_analysis.v2.rounded_tail import BoundedInterval, BoundedTailReference


START = datetime(2026, 9, 1, tzinfo=timezone.utc)
ACCOUNT = UUID(int=1)
CHECKS = (Checkpoint("75m", 75 * 60, 60),)


def measured(number, day, before, after, *, unit=100):
    post = PublishedPost(UUID(int=number), ACCOUNT, START + timedelta(days=day))
    first = SuccessfulRead(post.publication_id, ACCOUNT,
                           post.published_at + timedelta(minutes=60),
                           before, "rounded", views_display_unit=unit)
    last = SuccessfulRead(post.publication_id, ACCOUNT,
                          post.published_at + timedelta(minutes=75),
                          after, "rounded", views_display_unit=unit)
    return post, first, last


def coverage(post, reads):
    return audit_cohort_coverage(
        (post,), reads, {ACCOUNT: "telegram"}, frozenset({ACCOUNT}), CHECKS,
        cohort_start=post.published_at,
        cohort_end=post.published_at + timedelta(days=1),
        observed_through=post.published_at + timedelta(hours=2),
        max_gap_by_platform={"telegram": timedelta(minutes=30)},
        source="successful_poll_receipts", require_bounded_views=True,
    )[0]


def test_post_rank_uses_audited_pair_and_reports_resolution():
    calibration = [measured(100 + day, day, 1000, 1100) for day in range(8)]
    reference = BoundedTailReference.fit(
        (BoundedInterval("telegram", *row) for row in calibration),
        source="successful_poll_receipts",
    )
    post, first, last = measured(999, 9, 1000, 2000)
    result = score_bounded_post(post, coverage(post, (first, last)),
                                (first, last), reference)
    assert result.status == "research_ranked"
    assert result.planned_checks == result.observed_checks == 1
    assert result.post_rank_bound == result.best_attainable_bound == 1 / 9
    assert result.evidence[0].reference_days == 8

    missing = score_bounded_post(post, coverage(post, (first,)), (first,), reference)
    assert missing.status == "insufficient_data"
    assert missing.reason == "incomplete_receipt_coverage"

    shadow = BoundedTailReference.fit(
        (BoundedInterval("telegram", *row) for row in calibration),
        source="change_only_shadow",
    )
    with pytest.raises(ValueError, match="successful poll receipt reference"):
        score_bounded_post(post, coverage(post, (first, last)),
                           (first, last), shadow)
