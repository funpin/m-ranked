"""Post-level M1/M2 evidence at prespecified ages.

One interval is selected for each checkpoint by observation time alone. The
post rank uses a union bound over the full checkpoint plan, so a post cannot
become more unusual simply because it was checked repeatedly. Event context
may weaken M1 evidence, but cannot create a new positive finding. All ranks
still require validated interval references and complete successful reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal
from uuid import UUID

from .event_adjusted_tail import FeedObservedGrowth, PairedTailRank


@dataclass(frozen=True, slots=True)
class Checkpoint:
    name: str
    age_seconds: int
    tolerance_seconds: int


EARLY_CHECKPOINTS = (
    Checkpoint("1h", 3600, 30 * 60),
    Checkpoint("6h", 6 * 3600, 60 * 60),
    Checkpoint("24h", 24 * 3600, 2 * 3600),
    Checkpoint("48h", 48 * 3600, 4 * 3600),
    Checkpoint("72h", 72 * 3600, 6 * 3600),
)

LATE_CHECKPOINTS = (
    Checkpoint("4d", 4 * 86400, 6 * 3600),
    Checkpoint("5d", 5 * 86400, 6 * 3600),
    Checkpoint("7d", 7 * 86400, 8 * 3600),
    Checkpoint("14d", 14 * 86400, 12 * 3600),
)


@dataclass(frozen=True, slots=True)
class CheckpointEvidence:
    name: str
    interval_rank: float
    m1_rank: float
    m2_rank: float | None
    context_reduced: bool


@dataclass(frozen=True, slots=True)
class PostTailResult:
    publication_id: UUID
    status: str
    planned_checks: int
    observed_checks: int
    reason: str | None
    minimum_interval_rank: float | None
    m1_post_rank_bound: float | None
    post_rank_bound: float | None
    evidence: tuple[CheckpointEvidence, ...]


def _validate_plan(checkpoints: tuple[Checkpoint, ...]) -> None:
    if not checkpoints:
        raise ValueError("checkpoint plan cannot be empty")
    if len({item.name for item in checkpoints}) != len(checkpoints):
        raise ValueError("checkpoint names must be unique")
    previous_end = -1
    for item in checkpoints:
        if item.age_seconds <= 0 or item.tolerance_seconds < 0:
            raise ValueError("checkpoint ages and tolerances must be valid")
        if item.age_seconds - item.tolerance_seconds <= previous_end:
            raise ValueError("checkpoint windows must be ordered and disjoint")
        previous_end = item.age_seconds + item.tolerance_seconds


def _rank(row: FeedObservedGrowth, paired: PairedTailRank) -> tuple[float | None, str | None,
                                                                   float | None, bool]:
    m1 = paired.m1
    if m1.status == "observed_zero":
        return 1.0, None, None, False
    if m1.status != "ranked" or m1.upper_tail_rank is None:
        return None, f"m1:{m1.status}", None, False
    if row.nearest_event_distance is None:
        return m1.upper_tail_rank, None, None, False
    m2 = paired.m2
    if m2.status != "ranked" or m2.upper_tail_rank is None:
        return None, f"m2:{m2.status}", None, False
    # The event-conditioned reference can only temper a pre-existing M1 tail.
    # max(p1,p2) is conservative if p1 is valid, without independence of p1/p2.
    effective = max(m1.upper_tail_rank, m2.upper_tail_rank)
    return effective, None, m2.upper_tail_rank, effective > m1.upper_tail_rank


def score_post(
    publication_id: UUID,
    observations: Iterable[tuple[FeedObservedGrowth, PairedTailRank]],
    checkpoints: tuple[Checkpoint, ...],
    *,
    source: Literal["complete_receipts", "change_only_shadow"],
) -> PostTailResult:
    """Score one post only when every prespecified checkpoint is usable.

    A caller must separately verify the receipt schedule and eligible-post
    denominator. Change-triggered snapshots are not complete poll receipts.
    """
    _validate_plan(checkpoints)
    if source not in {"complete_receipts", "change_only_shadow"}:
        raise ValueError("unknown observation source")
    rows = tuple(observations)
    seen = set()
    account_platform = set()
    for row, paired in rows:
        if row.interval.publication_id != publication_id:
            raise ValueError("mixed publications in one post score")
        key = (row.interval.start_at, row.interval.end_at)
        if key in seen:
            raise ValueError("duplicate read pair in one post score")
        seen.add(key)
        account_platform.add((row.interval.account_id, row.interval.platform))
        if (paired.m1.interval.platform != row.interval.platform
                or paired.m1.interval.displayed_delta != row.interval.displayed_delta_views
                or paired.m2.m1 != paired.m1.interval):
            raise ValueError("rank and observed interval disagree")
    if len(account_platform) > 1:
        raise ValueError("mixed account or platform in one post score")
    chosen: list[CheckpointEvidence] = []
    missing: list[str] = []
    for checkpoint in checkpoints:
        candidates = [
            (abs(row.interval.age_seconds + row.interval.elapsed_seconds
                 - checkpoint.age_seconds), row.interval.end_at, row, paired)
            for row, paired in rows
            if abs(row.interval.age_seconds + row.interval.elapsed_seconds
                   - checkpoint.age_seconds) <= checkpoint.tolerance_seconds
        ]
        if not candidates:
            missing.append(checkpoint.name)
            continue
        _distance, _time, row, paired = min(candidates, key=lambda value: value[:2])
        rank, reason, m2_rank, reduced = _rank(row, paired)
        if reason is not None or rank is None:
            missing.append(f"{checkpoint.name}:{reason}")
            continue
        m1_rank = paired.m1.upper_tail_rank if paired.m1.upper_tail_rank is not None else 1.0
        chosen.append(CheckpointEvidence(checkpoint.name, rank, m1_rank, m2_rank, reduced))
    if missing:
        return PostTailResult(publication_id, "insufficient_data", len(checkpoints),
                              len(chosen), ",".join(missing), None, None, None,
                              tuple(chosen))
    smallest = min(item.interval_rank for item in chosen)
    # Union bound over planned looks: no independence assumption across reads.
    bound = min(1.0, len(checkpoints) * smallest)
    m1_bound = min(1.0, len(checkpoints) * min(item.m1_rank for item in chosen))
    status = "research_ranked" if source == "complete_receipts" else "shadow_only"
    return PostTailResult(publication_id, status, len(checkpoints), len(chosen),
                          None, smallest, m1_bound, bound, tuple(chosen))
