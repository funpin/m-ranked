from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
from uuid import UUID

import pytest

from anomaly_analysis.aggregation import aggregate
from anomaly_analysis.config import DelayedSpikeConfig, default_manifest
from anomaly_analysis.coordinator import AnalysisCoordinator, WorkerConfig, analysis_input_hash
from anomaly_analysis.detectors import DelayedSpikeDetector, LinearGrowthDetector, PeriodicJumpsDetector
from anomaly_analysis.domain import Abstained, Clean, Finding, Metric, MetricObservation, ObservationQuality, PublicationHistory
from anomaly_analysis.preprocessing import prepare_metric
from anomaly_analysis.registry import DetectorRegistry
from anomaly_analysis.postgres import Candidate, SourceRevision
from anomaly_analysis.metrics import TextfileMetrics

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLICATION = UUID("10000000-0000-0000-0000-000000000001")
INSTITUTION = UUID("20000000-0000-0000-0000-000000000002")
ACCOUNT = UUID("30000000-0000-0000-0000-000000000003")


def observations(values, seconds=300, *, quality=ObservationQuality.EXACT, uncertain=()):
    return tuple(MetricObservation(
        str(index + 1), BASE + timedelta(seconds=index * seconds), index * seconds,
        value, quality, interval_uncertain=index in uncertain,
    ) for index, value in enumerate(values))


def history(rows, *, completeness="complete", cadence=300, metric=Metric.VIEWS):
    return PublicationHistory(
        PUBLICATION, INSTITUTION, ACCOUNT, "telegram", BASE, completeness,
        7, BASE + timedelta(days=1), 1, 1, {metric: tuple(rows)},
        expected_sampling_seconds=cadence,
    )


def evaluate(detector, rows, metric=Metric.VIEWS, **kwargs):
    source = history(rows, metric=metric, **kwargs)
    return detector.evaluate(source, metric, prepare_metric(source.series[metric]))


def test_delayed_spike_after_plateau_and_organic_single_jump():
    detector = DelayedSpikeDetector(default_manifest().delayed_spike)
    finding = evaluate(detector, observations([100, 101, 102, 103, 104, 105, 500]))
    assert isinstance(finding, Finding)
    assert finding.explanation_code == "large_rate_jump_after_plateau"
    assert finding.suspicious_interval.start_snapshot_id == "6"
    organic = evaluate(detector, observations([100, 150, 210, 280, 360, 450, 900]))
    assert isinstance(organic, Clean)


def test_linear_growth_immediate_and_delayed_onset():
    detector = LinearGrowthDetector(default_manifest().linear_growth)
    immediate = evaluate(detector, observations([100 + index * 50 for index in range(12)]))
    assert isinstance(immediate, Finding)
    delayed = evaluate(detector, observations([10, 20, 45, 80] + [100 + index * 50 for index in range(10)]))
    assert isinstance(delayed, Finding)
    assert delayed.evidence["onsetObservationIndex"] >= 1
    noisy = evaluate(detector, observations([100, 113, 171, 190, 315, 326, 502, 520, 710, 745]))
    assert isinstance(noisy, Clean)


def test_periodic_jumps_and_irregular_jumps():
    detector = PeriodicJumpsDetector(default_manifest().periodic_jumps)
    # Small organic intervals separate three regular prominent jumps.
    periodic = observations([0, 5, 10, 210, 215, 220, 420, 425, 430, 630, 635, 640], 600)
    result = evaluate(detector, periodic, cadence=700)
    assert isinstance(result, Finding)
    irregular = observations([0, 5, 205, 210, 215, 415, 420, 425, 430, 435, 635, 640], 600)
    assert not isinstance(evaluate(detector, irregular, cadence=700), Finding)


@pytest.mark.parametrize("rows,reason", [
    (observations([1, 2, 3]), "insufficient_observations"),
    (observations([1, None, None, None, None, None, None, 2]), "insufficient_quality_coverage"),
])
def test_abstention_is_not_clean(rows, reason):
    result = evaluate(DelayedSpikeDetector(default_manifest().delayed_spike), rows)
    assert isinstance(result, Abstained)
    assert result.reason_code == reason


def test_missing_metric_and_incomplete_history_abstain():
    detector = DelayedSpikeDetector(default_manifest().delayed_spike)
    source = history(observations(range(8)))
    missing = detector.evaluate(source, Metric.COMMENTS, prepare_metric(()))
    assert isinstance(missing, Abstained) and missing.reason_code == "metric_unavailable"
    incomplete = evaluate(detector, observations(range(8)), completeness="forced_incomplete")
    assert isinstance(incomplete, Abstained) and incomplete.reason_code == "incomplete_history"


def test_preprocessing_preserves_null_synthetic_and_breaks_negative_delta():
    rows = list(observations([0, 10, None, 20, 5, 15]))
    rows[0] = replace(rows[0], synthetic=True, quality=ObservationQuality.ESTIMATED)
    prepared = prepare_metric(reversed(rows))
    assert prepared.observations[2].value is None
    assert all(segment.start.snapshot_id != "1" for segment in prepared.segments)
    negative = next(segment for segment in prepared.segments if segment.delta < 0)
    assert negative.break_reason == "negative_delta"


def test_duplicate_timestamp_has_no_rate_and_permutation_is_deterministic():
    rows = observations([10, 20, 30, 40, 50, 60, 70, 80])
    duplicate_time = replace(rows[2], observed_at=rows[1].observed_at)
    prepared = prepare_metric((rows[5], duplicate_time, *rows[:2], *rows[3:5], *rows[6:]))
    assert all(segment.elapsed_seconds > 0 and math.isfinite(segment.rate_per_second)
               for segment in prepared.segments)
    detector = LinearGrowthDetector(default_manifest().linear_growth)
    ordered = evaluate(detector, rows)
    permuted_source = history(tuple(reversed(rows)))
    permuted = detector.evaluate(permuted_source, Metric.VIEWS, prepare_metric(permuted_source.series[Metric.VIEWS]))
    assert ordered == permuted


def test_time_normalized_linear_sampling_density_is_consistent():
    detector = LinearGrowthDetector(default_manifest().linear_growth)
    dense = observations([index * 50 for index in range(13)], 300)
    sparse = observations([index * 100 for index in range(8)], 600)
    assert isinstance(evaluate(detector, dense), Finding)
    assert isinstance(evaluate(detector, sparse), Finding)


def test_uncertain_and_degraded_intervals_do_not_create_finding():
    detector = DelayedSpikeDetector(default_manifest().delayed_spike)
    uncertain = observations([100, 101, 102, 103, 104, 105, 500], uncertain=(6,))
    assert isinstance(evaluate(detector, uncertain), Abstained)
    degraded = observations([100, 101, 102, 103, 104, 105, 500], quality=ObservationQuality.DEGRADED)
    assert isinstance(evaluate(detector, degraded), Abstained)


def test_duration_gap_rounded_and_degraded_quality_gates_are_conservative():
    manifest = default_manifest()
    too_short = observations([100, 101, 102, 103, 104, 105, 500], seconds=120)
    result = evaluate(DelayedSpikeDetector(manifest.delayed_spike), too_short, cadence=120)
    assert isinstance(result, Abstained) and result.reason_code == "insufficient_duration"

    rows = list(observations([index * 50 for index in range(12)]))
    rows[6] = replace(rows[6], observed_at=rows[5].observed_at + timedelta(hours=3))
    for index in range(7, len(rows)):
        rows[index] = replace(rows[index], observed_at=rows[6].observed_at + timedelta(minutes=5 * (index - 6)))
    gap = evaluate(LinearGrowthDetector(manifest.linear_growth), tuple(rows), cadence=300)
    assert isinstance(gap, Abstained) and gap.reason_code == "excessive_sampling_gap"

    exact = evaluate(LinearGrowthDetector(manifest.linear_growth), observations([index * 50 for index in range(12)]))
    rounded = evaluate(LinearGrowthDetector(manifest.linear_growth), observations(
        [index * 50 for index in range(12)], quality=ObservationQuality.ROUNDED))
    degraded = evaluate(LinearGrowthDetector(manifest.linear_growth), observations(
        [index * 50 for index in range(12)], quality=ObservationQuality.DEGRADED))
    assert isinstance(exact, Finding) and isinstance(rounded, Finding)
    assert rounded.score < exact.score and "rounded_counter_conservative" in rounded.quality_codes
    assert isinstance(degraded, Abstained) and degraded.reason_code == "insufficient_trusted_observations"


def test_input_bound_is_explicit_and_does_not_silently_analyze():
    rows = observations(range(20))
    prepared = prepare_metric(rows, max_points=10)
    result = DelayedSpikeDetector(default_manifest().delayed_spike).evaluate(history(rows), Metric.VIEWS, prepared)
    assert isinstance(result, Abstained) and result.reason_code == "input_bound_exceeded"


def test_manifest_hash_and_registry_are_stable_and_duplicate_rejected():
    manifest = default_manifest()
    assert manifest.sha256 == default_manifest().sha256
    assert len(manifest.sha256) == 64
    registry = DetectorRegistry.from_manifest(manifest)
    assert len(registry.detectors) == 3
    with pytest.raises(ValueError, match="duplicate detector id"):
        DetectorRegistry.validated((registry.detectors[0], registry.detectors[0]))
    with pytest.raises(ValueError):
        DelayedSpikeConfig(minimum_coverage=2)


def test_aggregation_preserves_null_zero_and_score_range():
    detector = LinearGrowthDetector(default_manifest().linear_growth)
    finding = evaluate(detector, observations([index * 50 for index in range(12)]))
    clean = Clean("other", "1", Metric.VIEWS)
    abstained = Abstained("third", "1", Metric.VIEWS, "insufficient")
    result = aggregate((finding, clean, abstained))
    assert 0 <= result.suspicion_score <= 1  # type: ignore[operator]
    assert result.status == "partial"
    assert aggregate((clean,)).suspicion_score == 0
    assert aggregate((abstained,)).suspicion_score is None


class FakeMetrics:
    def __init__(self): self.events = []
    def processed(self, outcome, duration): self.events.append(("processed", outcome))
    def detector(self, detector_id, outcome): self.events.append((detector_id, outcome))
    def revision(self, analysis_revision, source_revision): self.events.append(("revision", analysis_revision, source_revision))
    def batch(self, size): self.events.append(("batch", size))
    def finding(self, detector_id, metric, severity): self.events.append(("finding", detector_id, metric, severity))
    def operational(self, values): self.events.append(("operational", values))


class FakeRepository:
    def __init__(self, source_history, *, unchanged=False, fail_publish=False):
        self.source_history = source_history; self.is_unchanged = unchanged; self.fail_publish = fail_publish
        self.candidate = Candidate(source_history.publication_id, 2, 0, False)
        self.successes = []; self.failures = []; self.noops = 0
    def latest_source_revision(self): return SourceRevision(7, BASE + timedelta(days=1))
    def seed_backfill(self, limit, manifest_hash): return 0
    def operational_snapshot(self): return {"candidate_backlog": 1}
    def claim(self, limit, lease_seconds, token): return (self.candidate,)
    def extract(self, publication_ids, source_revision, max_points): return {self.source_history.publication_id: self.source_history}
    def unchanged(self, publication_id, input_hash, manifest_hash): return self.is_unchanged
    def complete_noop(self, candidate, token): self.noops += 1; return True
    def publish_success(self, *args):
        if self.fail_publish: raise RuntimeError("secret database detail")
        self.successes.append(args); return 4
    def publish_failure(self, *args): self.failures.append(args); return 5


def test_coordinator_success_noop_and_failure_are_distinct():
    source = history(observations([100 + index * 50 for index in range(12)]))
    metrics = FakeMetrics(); repository = FakeRepository(source)
    assert AnalysisCoordinator(repository, default_manifest(), WorkerConfig(), metrics).run_once() == 1
    assert len(repository.successes) == 1 and not repository.failures
    repository = FakeRepository(source, unchanged=True)
    AnalysisCoordinator(repository, default_manifest(), WorkerConfig(), FakeMetrics()).run_once()
    assert repository.noops == 1 and not repository.successes and not repository.failures
    repository = FakeRepository(source, fail_publish=True)
    AnalysisCoordinator(repository, default_manifest(), WorkerConfig(), FakeMetrics()).run_once()
    assert len(repository.failures) == 1
    assert repository.failures[0][-2] == "analysis_processing_failed"


def test_input_hash_is_deterministic_versioned_and_order_insensitive_after_preparation():
    manifest = default_manifest()
    source = history(observations(range(8)))
    assert analysis_input_hash(source, manifest.sha256) == analysis_input_hash(source, manifest.sha256)
    permuted = replace(source, series={Metric.VIEWS: tuple(reversed(source.series[Metric.VIEWS]))})
    assert analysis_input_hash(source, manifest.sha256) == analysis_input_hash(permuted, manifest.sha256)
    changed = replace(source, capability_version=2)
    assert analysis_input_hash(source, manifest.sha256) != analysis_input_hash(changed, manifest.sha256)
    newer_revision = replace(source, source_dataset_revision=8)
    assert analysis_input_hash(source, manifest.sha256) == analysis_input_hash(newer_revision, manifest.sha256)


def test_textfile_metrics_are_atomic_bounded_and_contain_no_entity_labels(tmp_path: Path):
    destination = tmp_path / "anomaly.prom"
    metrics = TextfileMetrics(destination)
    metrics.batch(3)
    metrics.detector("periodic_large_jumps", "finding")
    metrics.finding("periodic_large_jumps", "views", "high")
    metrics.revision(12, 34)
    metrics.operational({"candidate_backlog": 7, "expired_leases": 1})
    metrics.processed("succeeded", 0.25)
    content = destination.read_text()
    assert 'detector="periodic_large_jumps"' in content
    assert "mranked_anomaly_candidate_backlog 7" in content
    assert "mranked_anomaly_latest_analysis_revision 12" in content
    assert str(PUBLICATION) not in content
    assert len([line for line in content.splitlines() if not line.startswith("#")]) <= 20
    assert destination.stat().st_mode & 0o777 == 0o640


def test_detectors_and_hash_remain_bounded_on_the_maximum_series():
    import time
    values = [100 + index * 3 + (index % 7) * (1 + index % 3) for index in range(4096)]
    source = history(observations(values))
    started = time.perf_counter()
    prepared = prepare_metric(source.series[Metric.VIEWS], max_points=4096)
    outcomes = [detector.evaluate(source, Metric.VIEWS, prepared)
                for detector in DetectorRegistry.from_manifest(default_manifest()).detectors]
    analysis_input_hash(source, default_manifest().sha256)
    assert not prepared.bound_exceeded and len(outcomes) == 3
    assert all(0 <= item.score <= 1 for item in outcomes if isinstance(item, Finding))
    assert time.perf_counter() - started < 10


def test_coordinator_only_evaluates_metrics_supported_by_the_seeded_capability_matrix():
    rows = observations([100 + index * 50 for index in range(12)])
    limited = replace(history(rows), platform="rutube",
                      series={Metric.VIEWS: rows, Metric.SHARES: rows},
                      supported_metrics=frozenset({Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS}))
    metrics = FakeMetrics()
    AnalysisCoordinator(FakeRepository(limited), default_manifest(), WorkerConfig(), metrics).run_once()
    detector_ids = {"delayed_spike_after_plateau", "suspiciously_linear_growth", "periodic_large_jumps"}
    evaluated = [event for event in metrics.events if event[0] in detector_ids]
    # three detectors x (views, reactions, comments); the unsupported shares
    # series is present in the input but never evaluated
    assert len(evaluated) == 9
    with pytest.raises(ValueError):
        replace(limited, supported_metrics=frozenset({"subscribers"}))
