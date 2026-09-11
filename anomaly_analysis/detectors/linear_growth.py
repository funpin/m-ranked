from __future__ import annotations

from dataclasses import dataclass

from ..config import LinearGrowthConfig
from ..domain import Abstained, Clean, EvidenceInterval, Finding, Metric, PublicationHistory, severity_for
from ..preprocessing import PreparedSeries, linear_fit, robust_median
from .base import DetectorMetadata
from .delayed_spike import _common_abstention


@dataclass(frozen=True, slots=True)
class LinearGrowthDetector:
    config: LinearGrowthConfig
    metadata = DetectorMetadata("suspiciously_linear_growth", "1.0.0", frozenset(Metric), 8, 1800)

    def evaluate(self, history: PublicationHistory, metric: Metric, prepared: PreparedSeries):
        reason = _common_abstention(history, metric, prepared, self.config.minimum_observations,
                                    self.config.minimum_duration_seconds, self.config.minimum_coverage)
        if reason:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric, reason)
        if (history.expected_sampling_seconds
                and prepared.maximum_gap_seconds > history.expected_sampling_seconds * 4):
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "excessive_sampling_gap")
        points = tuple(item for item in prepared.real_observations
                       if item.value is not None and item.quality.trusted_derivative
                       and not item.interval_uncertain)
        if len(points) < self.config.minimum_observations:
            return Abstained(self.metadata.detector_id, self.metadata.implementation_version, metric,
                             "insufficient_trusted_observations")
        latest_start = max(0, len(points) - self.config.minimum_observations)
        starts = sorted(set([0] + [round(i * latest_start / max(1, self.config.maximum_candidate_windows - 1))
                                   for i in range(self.config.maximum_candidate_windows)]))
        best = None
        for start in starts:
            window = points[start:]
            if len(window) < self.config.minimum_observations:
                continue
            duration = (window[-1].observed_at - window[0].observed_at).total_seconds()
            growth = (window[-1].value or 0) - (window[0].value or 0)
            if duration < self.config.minimum_duration_seconds or growth < self.config.minimum_total_growth:
                continue
            fit = linear_fit(window)
            if fit is None or fit.slope <= 0:
                continue
            rates = []
            for left, right in zip(window, window[1:]):
                elapsed = (right.observed_at - left.observed_at).total_seconds()
                if elapsed > 0:
                    rates.append(((right.value or 0) - (left.value or 0)) / elapsed)
            center = robust_median(rates)
            rate_cv = (sum((rate - center) ** 2 for rate in rates) / len(rates)) ** 0.5 / max(abs(center), 1e-12)
            if (fit.r_squared < self.config.minimum_r_squared
                    or fit.normalized_rmse > self.config.maximum_normalized_rmse
                    or rate_cv > self.config.maximum_rate_cv):
                continue
            score = min(1.0, 0.4 + 0.3 * fit.r_squared
                        + 0.2 * (1 - min(rate_cv / self.config.maximum_rate_cv, 1))
                        + 0.1 * min(duration / 86400, 1))
            if any(point.quality.value == "rounded" for point in window):
                score *= 0.85
            candidate = (score, start, window, fit, rate_cv, duration, growth)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return Clean(self.metadata.detector_id, self.metadata.implementation_version, metric)
        score, start, window, fit, rate_cv, duration, growth = best
        return Finding(
            self.metadata.detector_id, self.metadata.implementation_version, metric,
            score, severity_for(score), "stable_time_normalized_linear_growth",
            EvidenceInterval(window[0].snapshot_id, window[-1].snapshot_id,
                             window[0].observed_at, window[-1].observed_at),
            {"onsetObservationIndex": start, "sampleSize": len(window),
             "durationSeconds": duration, "totalGrowth": growth,
             "slopePerSecond": fit.slope, "rSquared": fit.r_squared,
             "normalizedRmse": fit.normalized_rmse, "rateCoefficientOfVariation": rate_cv,
             "coverage": prepared.coverage},
            quality_codes=("rounded_counter_conservative" if any(p.quality.value == "rounded" for p in window) else "exact_or_mixed",),
            alternative_explanation_codes=("scheduled_campaign", "provider_rounding"),
        )
