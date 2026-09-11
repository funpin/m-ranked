from __future__ import annotations

from dataclasses import dataclass

from ..config import PeriodicJumpsConfig
from ..domain import Abstained, Clean, EvidenceInterval, Finding, Metric, PublicationHistory, severity_for
from ..preprocessing import PreparedSeries, robust_median
from .base import DetectorMetadata
from .delayed_spike import _common_abstention


@dataclass(frozen=True, slots=True)
class PeriodicJumpsDetector:
    config: PeriodicJumpsConfig
    metadata = DetectorMetadata("periodic_large_jumps", "1.0.0", frozenset(Metric), 10, 3600)

    def evaluate(self, history: PublicationHistory, metric: Metric, prepared: PreparedSeries):
        reason = _common_abstention(history, metric, prepared, self.config.minimum_observations,
                                    self.config.minimum_duration_seconds, self.config.minimum_coverage)
        if reason:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric, reason)
        if (history.expected_sampling_seconds
                and prepared.maximum_gap_seconds > history.expected_sampling_seconds * 4):
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "excessive_sampling_gap")
        trusted = tuple(segment for segment in prepared.segments if segment.delta >= 0 and segment.trusted)
        if len(trusted) < self.config.minimum_repetitions + 2:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "insufficient_trusted_intervals")
        baseline = robust_median(segment.rate_per_second for segment in trusted)
        jumps = tuple(segment for segment in trusted
                      if segment.delta >= self.config.minimum_jump_delta
                      and segment.rate_per_second >= max(1e-12, baseline) * self.config.minimum_prominence_ratio)
        if len(jumps) < self.config.minimum_repetitions:
            return Clean(self.metadata.detector_id, self.metadata.implementation_version, metric)
        midpoints = tuple((segment.start.observed_at.timestamp() + segment.end.observed_at.timestamp()) / 2
                          for segment in jumps)
        spacings = tuple(right - left for left, right in zip(midpoints, midpoints[1:]))
        period = robust_median(spacings)
        if period <= 0:
            return Clean(self.metadata.detector_id, self.metadata.implementation_version, metric)
        spacing_cv = (sum((value - period) ** 2 for value in spacings) / len(spacings)) ** 0.5 / period
        magnitude_center = robust_median(segment.delta for segment in jumps)
        magnitude_cv = (sum((segment.delta - magnitude_center) ** 2 for segment in jumps) / len(jumps)) ** 0.5 / max(1, magnitude_center)
        if spacing_cv > self.config.maximum_spacing_cv or magnitude_cv > self.config.maximum_magnitude_cv:
            return Clean(self.metadata.detector_id, self.metadata.implementation_version, metric)
        if history.expected_sampling_seconds:
            cadence_multiple = max(1, round(period / history.expected_sampling_seconds))
            cadence_distance = abs(period - cadence_multiple * history.expected_sampling_seconds) / period
            uncertainty = max(segment.elapsed_seconds for segment in jumps)
            if cadence_distance <= self.config.cadence_confounded_tolerance and uncertainty >= history.expected_sampling_seconds:
                return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                                 "collector_cadence_confounding")
        score = min(1.0, 0.4 + 0.12 * len(jumps)
                    + 0.25 * (1 - spacing_cv / self.config.maximum_spacing_cv)
                    + 0.1 * (1 - magnitude_cv / self.config.maximum_magnitude_cv))
        first, last = jumps[0], jumps[-1]
        return Finding(
            self.metadata.detector_id, self.metadata.implementation_version, metric,
            score, severity_for(score), "regular_repeated_prominent_jumps",
            EvidenceInterval(first.start.snapshot_id, last.end.snapshot_id,
                             first.start.observed_at, last.end.observed_at),
            {"jumpCount": len(jumps), "estimatedPeriodSeconds": period,
             "spacingCoefficientOfVariation": spacing_cv,
             "magnitudeCoefficientOfVariation": magnitude_cv,
             "baselineRatePerSecond": baseline, "medianJumpDelta": magnitude_center,
             "coverage": prepared.coverage},
            alternative_explanation_codes=("provider_batching", "collector_cadence", "scheduled_campaign"),
        )
