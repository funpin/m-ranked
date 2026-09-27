from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.cohort_coverage import audit_cohort_coverage
from anomaly_analysis.v2.post_tail import Checkpoint


START = datetime(2026, 9, 1, tzinfo=timezone.utc)
ACCOUNT = UUID(int=1)
OTHER = UUID(int=2)
POSTS = (
    PublishedPost(UUID(int=11), ACCOUNT, START),
    PublishedPost(UUID(int=12), ACCOUNT, START + timedelta(minutes=1)),
    PublishedPost(UUID(int=13), ACCOUNT, START + timedelta(minutes=2)),
    PublishedPost(UUID(int=14), OTHER, START),
)
CHECKS = (Checkpoint("1h", 3600, 600), Checkpoint("6h", 21600, 600))


def read(post: PublishedPost, age_minutes: int, views: int, quality: str = "exact"):
    return SuccessfulRead(post.publication_id, post.account_id,
                          post.published_at + timedelta(minutes=age_minutes),
                          views, quality)


def audit(reads, *, through=START + timedelta(hours=8)):
    return audit_cohort_coverage(
        POSTS, reads, {ACCOUNT: "max", OTHER: "vk"}, frozenset({ACCOUNT}), CHECKS,
        cohort_start=START, cohort_end=START + timedelta(days=1),
        observed_through=through, max_gap_by_platform={"max": timedelta(minutes=30)},
        source="successful_poll_receipts",
    )


def test_full_catalog_frame_keeps_unread_posts_in_denominator():
    first, missing, bad = POSTS[:3]
    result = audit((read(first, 45, 100), read(first, 60, 100),
                    read(first, 345, 100), read(first, 360, 120),
                    read(bad, 45, 100), read(bad, 60, 120, "unknown"),
                    read(bad, 345, 120), read(bad, 360, 130)))
    assert [row.publication_id for row in result] == [post.publication_id for post in POSTS[:3]]
    assert [row.status for row in result] == ["complete", "insufficient_data", "insufficient_data"]
    assert result[0].checkpoints[0].interval.exact_zero_observed
    assert [check.status for check in result[1].checkpoints] == [
        "missing_read_pair", "missing_read_pair",
    ]
    assert result[2].checkpoints[0].status == "untrusted_quality"


def test_future_checkpoint_is_not_mislabeled_as_missing():
    result = audit((), through=START + timedelta(hours=2))
    assert all(row.status == "not_due" for row in result)
    assert all(row.checkpoints[0].status == "missing_read_pair" for row in result)
    assert all(row.checkpoints[1].status == "not_due" for row in result)


def test_nearest_read_is_selected_by_time_not_by_growth():
    post = POSTS[0]
    result = audit((read(post, 40, 100), read(post, 55, 100),
                    read(post, 60, 100), read(post, 345, 100), read(post, 360, 100)))
    assert result[0].status == "complete"
    assert result[0].checkpoints[0].interval.end_at == post.published_at + timedelta(hours=1)


def test_bounded_readiness_requires_compact_display_precision():
    post = POSTS[0]
    one_check = (CHECKS[0],)

    def checked(unit):
        reads = (
            SuccessfulRead(post.publication_id, ACCOUNT,
                           START + timedelta(minutes=45), 1000, "rounded",
                           views_display_unit=unit),
            SuccessfulRead(post.publication_id, ACCOUNT,
                           START + timedelta(minutes=60), 1200, "rounded",
                           views_display_unit=unit),
        )
        return audit_cohort_coverage(
            (post,), reads, {ACCOUNT: "telegram"}, frozenset({ACCOUNT}), one_check,
            cohort_start=START, cohort_end=START + timedelta(days=1),
            observed_through=START + timedelta(hours=2),
            max_gap_by_platform={"telegram": timedelta(minutes=30)},
            source="successful_poll_receipts", require_bounded_views=True,
        )[0]

    unknown = checked(None)
    assert unknown.status == "insufficient_data"
    assert unknown.checkpoints[0].status == "unknown_rounding_precision"
    assert checked(100).status == "complete"


def test_rejects_incomplete_frame_metadata_and_naive_time():
    with pytest.raises(ValueError, match="timezone"):
        audit_cohort_coverage(POSTS, (), {ACCOUNT: "max"}, frozenset({ACCOUNT}),
                              CHECKS, cohort_start=START.replace(tzinfo=None),
                              cohort_end=START + timedelta(days=1),
                              observed_through=START + timedelta(days=1),
                              max_gap_by_platform={"max": timedelta(minutes=30)},
                              source="successful_poll_receipts")
    with pytest.raises(ValueError, match="gap limit"):
        audit_cohort_coverage(POSTS, (), {ACCOUNT: "max"}, frozenset({ACCOUNT}),
                              CHECKS, cohort_start=START,
                              cohort_end=START + timedelta(days=1),
                              observed_through=START + timedelta(days=1),
                              max_gap_by_platform={"telegram": timedelta(minutes=30)},
                              source="successful_poll_receipts")
    with pytest.raises(ValueError, match="successful per-post poll receipts"):
        audit_cohort_coverage(POSTS, (), {ACCOUNT: "max"}, frozenset({ACCOUNT}),
                              CHECKS, cohort_start=START,
                              cohort_end=START + timedelta(days=1),
                              observed_through=START + timedelta(days=1),
                              max_gap_by_platform={"max": timedelta(minutes=30)},
                              source="change_only_shadow")
