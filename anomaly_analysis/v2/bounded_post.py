"""Prospective post-level rank from complete successful poll receipts only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead

from .cohort_coverage import PostCoverage
from .rounded_tail import BoundedInterval, BoundedTailReference


@dataclass(frozen=True, slots=True)
class BoundedPostEvidence:
    checkpoint: str
    upper_tail_rank: float
    reference_days: int
    reference_posts: int


@dataclass(frozen=True, slots=True)
class BoundedPostResult:
    publication_id: UUID
    status: str
    reason: str | None
    planned_checks: int
    observed_checks: int
    post_rank_bound: float | None
    best_attainable_bound: float | None
    evidence: tuple[BoundedPostEvidence, ...]


def score_bounded_post(
    post: PublishedPost, coverage: PostCoverage,
    reads: Iterable[SuccessfulRead], reference: BoundedTailReference,
) -> BoundedPostResult:
    """Use exactly the receipt pair chosen by the independent coverage audit.

    The reference must have been built from complete receipts on earlier days;
    a change-only archive reference is refused even when its ranks exist.
    """
    if reference.source != "successful_poll_receipts":
        raise ValueError("post scoring requires successful poll receipt reference")
    if (post.publication_id != coverage.publication_id
            or post.account_id != coverage.account_id
            or coverage.platform != reference.platform):
        raise ValueError("publication, coverage and reference disagree")
    plan_size = len(coverage.checkpoints)
    if not plan_size:
        raise ValueError("coverage has no checkpoint plan")
    if coverage.status != "complete" or any(
        check.status != "usable" for check in coverage.checkpoints
    ):
        return BoundedPostResult(
            post.publication_id, "insufficient_data", "incomplete_receipt_coverage",
            plan_size, 0, None, None, (),
        )
    by_time = {}
    for read in reads:
        if read.publication_id != post.publication_id or read.account_id != post.account_id:
            raise ValueError("read belongs to another publication or account")
        if read.observed_at in by_time:
            raise ValueError("duplicate receipt timestamp")
        by_time[read.observed_at] = read
    evidence = []
    for check in coverage.checkpoints:
        interval = check.interval
        if interval is None or interval.publication_id != post.publication_id:
            raise ValueError("complete coverage has no matching interval")
        before, after = by_time.get(interval.start_at), by_time.get(interval.end_at)
        if before is None or after is None:
            return BoundedPostResult(
                post.publication_id, "insufficient_data", "receipt_pair_missing",
                plan_size, len(evidence), None, None, tuple(evidence),
            )
        if (before.views_count != interval.before_views
                or after.views_count != interval.after_views):
            raise ValueError("receipt values differ from the coverage audit")
        rank = reference.rank(BoundedInterval(reference.platform, post, before, after))
        if rank.status != "research_ranked" or rank.upper_tail_rank is None:
            return BoundedPostResult(
                post.publication_id, "insufficient_data", rank.status,
                plan_size, len(evidence), None, None, tuple(evidence),
            )
        evidence.append(BoundedPostEvidence(
            check.name, rank.upper_tail_rank,
            rank.calibration_days, rank.calibration_posts,
        ))
    bound = min(1.0, plan_size * min(item.upper_tail_rank for item in evidence))
    resolution = min(1.0, plan_size * min(
        1 / (item.reference_days + 1) for item in evidence
    ))
    return BoundedPostResult(
        post.publication_id, "research_ranked", None, plan_size, plan_size,
        bound, resolution, tuple(evidence),
    )
