from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.post_calibration import PostRankInput, PostTailCalibration
from anomaly_analysis.v2.post_tail import CheckpointEvidence, PostTailResult


START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def post(number: int, day: int, bound: float, *, platform: str = "max",
         plan: tuple[str, ...] = ("1h", "6h"), status: str = "research_ranked",
         account: int | None = None, model_id: str = "fixed-m1-m2-v1") -> PostRankInput:
    checks = tuple(CheckpointEvidence(name, bound, 1 / 101, bound, None, False)
                   for name in plan)
    score = PostTailResult(UUID(int=number), status, len(plan), len(checks), None,
                           bound / len(plan), 2 / 101, bound, bound, checks)
    published_at = START + timedelta(days=day)
    return PostRankInput(UUID(int=(account if account is not None else number % 3) + 1), platform,
                         published_at, published_at + timedelta(hours=26), model_id, score)


def fit(rows, **kwargs):
    return PostTailCalibration.fit(rows, interval_reference_through=START - timedelta(days=1),
                                   source="complete_receipts", **kwargs)


def cohort() -> tuple[PostRankInput, ...]:
    # Two posts per account-day must count as one calibration opportunity.
    return tuple(post(1000 + day * 6 + account * 2 + duplicate, day,
                      .10 if duplicate else .40, account=account)
                 for day in range(8) for account in range(3)
                 for duplicate in range(2))


def test_calibrates_whole_posts_with_one_extreme_per_account_day():
    reference = fit(cohort(), min_blocks=20, min_days=5)
    rare = reference.rank(post(9999, 9, .01))
    ordinary = reference.rank(post(9998, 9, .40))
    assert rare.status == "research_ranked"
    assert rare.calibration_blocks == 24
    assert rare.calibration_accounts == 3
    assert rare.calibration_days == 8
    assert rare.upper_tail_rank == rare.smallest_resolvable_rank == 1 / 25
    assert rare.conservative_rank == 1 / 25
    assert ordinary.upper_tail_rank == 1
    assert ordinary.conservative_rank == 1


def test_sparse_reference_abstains_and_rejects_leakage_or_shadow_scores():
    reference = fit(cohort(), min_blocks=40)
    result = reference.rank(post(9999, 9, .01))
    assert result.status == "insufficient_calibration"
    assert result.upper_tail_rank is None
    assert result.conservative_rank is None
    with pytest.raises(ValueError, match="later UTC day"):
        reference.rank(post(9998, 7, .01))
    with pytest.raises(ValueError, match="calibration cohort"):
        reference.rank(cohort()[0])
    with pytest.raises(ValueError, match="research_ranked scores for complete_receipts"):
        reference.rank(post(9997, 9, .01, status="shadow_only"))


def test_platform_and_horizon_are_separate_and_duplicate_posts_fail():
    rows = cohort()
    with pytest.raises(ValueError, match="mix platforms"):
        fit((*rows, post(9997, 8, .20, platform="vk")))
    with pytest.raises(ValueError, match="platforms, plans"):
        fit((*rows, post(9997, 8, .20, plan=("4d", "5d"))))
    with pytest.raises(ValueError, match="fitted models"):
        fit((*rows, post(9997, 8, .20, model_id="another-fit")))
    with pytest.raises(ValueError, match="duplicate publication"):
        fit((*rows, rows[0]))
    reference = fit(rows, min_blocks=20, min_days=5)
    with pytest.raises(ValueError, match="another platform"):
        reference.rank(post(9997, 9, .01, platform="vk"))
    with pytest.raises(ValueError, match="another platform, checkpoint plan"):
        reference.rank(post(9997, 9, .01, plan=("4d", "5d")))
    with pytest.raises(ValueError, match="fitted model"):
        reference.rank(post(9997, 9, .01, model_id="another-fit"))


def test_publication_time_must_be_timezone_aware():
    row = post(9999, 9, .01)
    with pytest.raises(ValueError, match="timezone"):
        fit((replace(row, published_at=row.published_at.replace(tzinfo=None)),))
    with pytest.raises(ValueError, match="availability time must include a timezone"):
        fit((replace(row, score_available_at=row.score_available_at.replace(tzinfo=None)),))


def test_post_calibration_must_follow_interval_reference():
    with pytest.raises(ValueError, match="interval model reference"):
        PostTailCalibration.fit(cohort(), source="complete_receipts",
                                interval_reference_through=START)
    with pytest.raises(ValueError, match="timezone"):
        PostTailCalibration.fit(cohort(), source="complete_receipts",
                                interval_reference_through=START.replace(tzinfo=None))


def test_change_only_archive_stays_shadow_even_with_small_rank():
    rows = tuple(replace(item, score=replace(item.score, status="shadow_only"))
                 for item in cohort())
    reference = PostTailCalibration.fit(rows, source="change_only_shadow",
                                        interval_reference_through=START - timedelta(days=1),
                                        min_blocks=20, min_days=5)
    test = post(9999, 9, .01, status="shadow_only")
    result = reference.rank(test)
    assert result.status == "shadow_only"
    assert result.upper_tail_rank == 1 / 25
    assert result.conservative_rank == 1 / 25
    with pytest.raises(ValueError, match="shadow_only scores for change_only_shadow"):
        reference.rank(replace(test, score=replace(test.score, status="research_ranked")))


def test_empirical_post_rank_keeps_information_lost_by_clipped_union_bound():
    rows = tuple(replace(item, score=replace(item.score,
                                            minimum_interval_rank=.2,
                                            post_rank_bound=1.0))
                 for item in cohort())
    reference = fit(rows, min_blocks=20, min_days=5)
    test = post(9999, 9, .5)
    rare = replace(test, score=replace(test.score,
                                       minimum_interval_rank=.1,
                                       post_rank_bound=1.0))
    ordinary = replace(test, score=replace(test.score,
                                           minimum_interval_rank=.5,
                                           post_rank_bound=1.0))
    assert reference.rank(rare).upper_tail_rank == 1 / 25
    assert reference.rank(rare).conservative_rank == .1
    assert reference.rank(ordinary).upper_tail_rank == 1.0


def test_calibration_scores_must_be_complete_before_test_post():
    rows = cohort()
    last = rows[-1]
    late = replace(last, score_available_at=START + timedelta(days=10))
    reference = fit((*rows[:-1], late), min_blocks=20, min_days=5)
    with pytest.raises(ValueError, match="predates a completed calibration score"):
        reference.rank(post(9999, 9, .01))
