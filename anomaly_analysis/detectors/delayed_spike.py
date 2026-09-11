from __future__ import annotations

from dataclasses import dataclass

from ..config import DelayedSpikeConfig
from ..domain import Abstained, Clean, EvidenceInterval, Finding, Metric, PublicationHistory, severity_for
from ..preprocessing import PreparedSeries, median_absolute_deviation, robust_median
from .base import DetectorMetadata


@dataclass(frozen=True, slots=True)
class DelayedSpikeDetector:
    config: DelayedSpikeConfig
    metadata = DetectorMetadata(
        "delayed_spike_after_plateau", "1.0.0", frozenset(Metric), 6, 1800
    )

    def evaluate(self, history: PublicationHistory, metric: Metric, prepared: PreparedSeries):
        reason = _common_abstention(history, metric, prepared, self.config.minimum_observations,
                                    self.config.minimum_duration_seconds, self.config.minimum_coverage)
        if reason:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric, reason)
        if (history.expected_sampling_seconds
                and prepared.maximum_gap_seconds > history.expected_sampling_seconds * self.config.maximum_gap_factor):
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "excessive_sampling_gap")
        required_intervals = min(self.config.minimum_observations,
                                 len(prepared.real_observations) - 1)
        if sum(segment.delta >= 0 and segment.trusted for segment in prepared.segments) < required_intervals:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "insufficient_trusted_intervals")
        expected = history.expected_sampling_seconds
        usable = tuple(segment for segment in prepared.segments if segment.delta >= 0)
        for index in range(3, len(usable)):
            jump = usable[index]
            prior = usable[max(0, index - 5):index]
            plateau_seconds = sum(segment.elapsed_seconds for segment in prior)
            if plateau_seconds < self.config.minimum_plateau_seconds:
                continue
            if not jump.trusted or any(not segment.trusted for segment in prior):
                continue
            rates = tuple(segment.rate_per_second for segment in prior)
            baseline = robust_median(rates)
            dispersion = median_absolute_deviation(rates)
            effective_baseline = max(baseline + 3 * dispersion, 1 / max(plateau_seconds, 1))
            rate_ratio = jump.rate_per_second / effective_baseline
            prior_value = jump.start.value or 0
            relative = jump.delta / max(1, prior_value)
            if (jump.delta < self.config.minimum_absolute_delta
                    or relative < self.config.minimum_relative_delta
                    or rate_ratio < self.config.minimum_rate_ratio):
                continue
            plateau_growth = sum(segment.delta for segment in prior)
            if plateau_growth / max(1, prior_value) > 0.12:
                continue
            strength = min(1.0, 0.35 + 0.25 * min(rate_ratio / 20, 1)
                           + 0.2 * min(relative, 1) + 0.2 * prepared.coverage)
            return Finding(
                self.metadata.detector_id, self.metadata.implementation_version, metric,
                strength, severity_for(strength), "large_rate_jump_after_plateau",
                EvidenceInterval(jump.start.snapshot_id, jump.end.snapshot_id,
                                 jump.start.observed_at, jump.end.observed_at),
                {"delta": jump.delta, "durationSeconds": jump.elapsed_seconds,
                 "ratePerSecond": jump.rate_per_second, "baselineRatePerSecond": baseline,
                 "baselineMad": dispersion, "rateRatio": rate_ratio,
                 "relativeDelta": relative, "plateauDurationSeconds": plateau_seconds,
                 "coverage": prepared.coverage},
                alternative_explanation_codes=("external_referral", "provider_batching", "legitimate_promotion"),
            )
        return Clean(self.metadata.detector_id, self.metadata.implementation_version, metric)


def _common_abstention(history, metric, prepared, minimum_observations, minimum_duration, minimum_coverage):
    if metric not in history.series:
        return "metric_unavailable"
    if prepared.bound_exceeded:
        return "input_bound_exceeded"
    if len(prepared.real_observations) < minimum_observations:
        return "insufficient_observations"
    duration = (prepared.real_observations[-1].observed_at - prepared.real_observations[0].observed_at).total_seconds()
    if duration < minimum_duration:
        return "insufficient_duration"
    if prepared.coverage < minimum_coverage:
        return "insufficient_quality_coverage"
    if history.history_completeness != "complete":
        return "incomplete_history"
    return None
