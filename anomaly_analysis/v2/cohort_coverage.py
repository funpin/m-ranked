"""Prospective receipt coverage against the full eligible publication frame.

Every publication in the declared cohort appears in the result, including
posts with no successful reads. This is a readiness audit, not an anomaly
score. The caller must obtain the publication frame independently of receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal, Mapping
from uuid import UUID

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead

from .post_tail import Checkpoint, _validate_plan
from .receipt_panel import ObservedGrowth, consecutive_growth


@dataclass(frozen=True, slots=True)
class CheckpointCoverage:
    name: str
    status: str
    interval: ObservedGrowth | None


@dataclass(frozen=True, slots=True)
class PostCoverage:
    publication_id: UUID
    account_id: UUID
    platform: str
    status: str
    checkpoints: tuple[CheckpointCoverage, ...]


def audit_cohort_coverage(
    publications: Iterable[PublishedPost],
    reads: Iterable[SuccessfulRead],
    platform_by_account: Mapping[UUID, str],
    account_ids: frozenset[UUID],
    checkpoints: tuple[Checkpoint, ...],
    *,
    cohort_start: datetime,
    cohort_end: datetime,
    observed_through: datetime,
    max_gap_by_platform: Mapping[str, timedelta],
    source: Literal["successful_poll_receipts"],
) -> tuple[PostCoverage, ...]:
    """Report whether each due post has a usable read pair at every checkpoint.

    `cohort_start` is inclusive and `cohort_end` exclusive. A checkpoint is
    due only after its full tolerance window has elapsed; later reads cannot
    silently replace an unobserved checkpoint. Missing or bad reads abstain.
    The returned denominator is the catalog frame, never the receipt table.
    """
    _validate_plan(checkpoints)
    if source != "successful_poll_receipts":
        raise ValueError("coverage requires successful per-post poll receipts")
    for value in (cohort_start, cohort_end, observed_through):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cohort timestamps must be timezone-aware")
    start = cohort_start.astimezone(timezone.utc)
    end = cohort_end.astimezone(timezone.utc)
    through = observed_through.astimezone(timezone.utc)
    if start >= end or through < start:
        raise ValueError("invalid cohort window")
    frame = tuple(sorted(
        (post for post in publications
         if post.account_id in account_ids and start <= post.published_at < end),
        key=lambda post: (post.published_at, post.publication_id),
    ))
    ids = {post.publication_id for post in frame}
    if len(ids) != len(frame):
        raise ValueError("duplicate publication in eligible frame")
    for post in frame:
        if post.account_id not in platform_by_account:
            raise ValueError("eligible account has no platform")
        if platform_by_account[post.account_id] not in max_gap_by_platform:
            raise ValueError("eligible platform has no gap limit")
    selected_reads = tuple(read for read in reads
                           if read.publication_id in ids and read.observed_at <= through)
    intervals = consecutive_growth(
        selected_reads, frame, platform_by_account,
        max_gap_by_platform=max_gap_by_platform,
    )
    by_post: dict[UUID, list[ObservedGrowth]] = {post_id: [] for post_id in ids}
    for interval in intervals:
        by_post[interval.publication_id].append(interval)
    result: list[PostCoverage] = []
    for post in frame:
        checks: list[CheckpointCoverage] = []
        for check in checkpoints:
            if through < post.published_at + timedelta(
                seconds=check.age_seconds + check.tolerance_seconds
            ):
                checks.append(CheckpointCoverage(check.name, "not_due", None))
                continue
            candidates = [
                row for row in by_post[post.publication_id]
                if row.end_at <= through and abs(
                    (row.end_at - post.published_at).total_seconds() - check.age_seconds
                ) <= check.tolerance_seconds
            ]
            if not candidates:
                checks.append(CheckpointCoverage(check.name, "missing_read_pair", None))
                continue
            chosen = min(candidates, key=lambda row: (
                abs((row.end_at - post.published_at).total_seconds() - check.age_seconds),
                row.end_at,
            ))
            checks.append(CheckpointCoverage(
                check.name, "usable" if chosen.usable else chosen.status, chosen,
            ))
        if any(check.status == "not_due" for check in checks):
            status = "not_due"
        elif all(check.status == "usable" for check in checks):
            status = "complete"
        else:
            status = "insufficient_data"
        result.append(PostCoverage(post.publication_id, post.account_id,
                                   platform_by_account[post.account_id],
                                   status, tuple(checks)))
    return tuple(result)
