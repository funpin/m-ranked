from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.interval_baseline import ConditionalIntervalBaseline
from anomaly_analysis.v2.receipt_panel import ObservedGrowth


START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def interval(index: int, *, platform: str = "vk", age_days: float = 3,
             delta: int = 10, rounded: bool = False, status: str = "usable") -> ObservedGrowth:
    account = UUID(f"00000000-0000-4000-8000-{index % 3 + 1:012d}")
    publication = UUID(f"10000000-0000-4000-8000-{index + 1:012d}")
    return ObservedGrowth(
        platform, account, publication, START, START + timedelta(minutes=15),
        age_days * 86400, 900, 100, 100 + delta, delta, None, rounded,
        status == "usable" and delta == 0 and not rounded, status,
    )


def test_interval_baseline_conditions_on_platform_age_and_exposure() -> None:
    training = [interval(i, delta=10 + i % 4) for i in range(24)]
    training += [interval(30 + i, age_days=5, delta=100 + i % 4) for i in range(24)]
    model = ConditionalIntervalBaseline.fit(training)
    ordinary = model.score(interval(100, delta=12))
    high = model.score(interval(101, delta=300))
    late_vk = model.score(interval(102, age_days=5, delta=102))
    assert ordinary.status == high.status == late_vk.status == "scored_positive"
    assert high.positive_residual > ordinary.positive_residual
    assert late_vk.expected_positive_per_hour > ordinary.expected_positive_per_hour * 5
    assert model.score(interval(103, platform="telegram")).status == "insufficient_reference"
    assert model.score(interval(104, age_days=1)).status == "insufficient_reference"
    assert model.score(replace(interval(105), elapsed_seconds=3600)).status == "insufficient_reference"


def test_unobserved_or_rounded_values_cannot_train_or_score_as_zeros() -> None:
    valid = [interval(i, delta=10) for i in range(22)] + [interval(30 + i, delta=0) for i in range(3)]
    invalid = [interval(50 + i, delta=0, rounded=True) for i in range(40)]
    invalid += [interval(100 + i, delta=0, status="excessive_gap") for i in range(40)]
    model = ConditionalIntervalBaseline.fit(valid + invalid)
    cell = next(iter(model.cells.values()))
    assert cell.interval_count == 25
    assert cell.exact_zero_share == 3 / 25
    assert model.score(interval(200, delta=0)).status == "observed_zero"
    assert model.score(interval(201, delta=0)).positive_residual is None
    assert model.score(interval(202, delta=0, rounded=True)).status == "unusable_interval"
    assert model.score(interval(203, delta=0, status="excessive_gap")).status == "unusable_interval"
