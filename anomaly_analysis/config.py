from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DelayedSpikeConfig:
    minimum_observations: int = 6
    minimum_duration_seconds: int = 1800
    minimum_plateau_seconds: int = 900
    minimum_absolute_delta: int = 50
    minimum_relative_delta: float = 0.20
    minimum_rate_ratio: float = 8.0
    minimum_coverage: float = 0.75
    maximum_gap_factor: float = 3.5

    def __post_init__(self) -> None:
        _validate_common(self.minimum_observations, self.minimum_duration_seconds,
                         self.minimum_coverage)
        if self.minimum_plateau_seconds <= 0 or self.minimum_absolute_delta <= 0:
            raise ValueError("delayed-spike thresholds must be positive")
        if self.minimum_relative_delta <= 0 or self.minimum_rate_ratio <= 1 or self.maximum_gap_factor <= 1:
            raise ValueError("delayed-spike ratios are invalid")


@dataclass(frozen=True, slots=True)
class LinearGrowthConfig:
    minimum_observations: int = 8
    minimum_duration_seconds: int = 1800
    minimum_total_growth: int = 100
    minimum_r_squared: float = 0.985
    maximum_normalized_rmse: float = 0.035
    maximum_rate_cv: float = 0.18
    minimum_coverage: float = 0.80
    maximum_candidate_windows: int = 24

    def __post_init__(self) -> None:
        _validate_common(self.minimum_observations, self.minimum_duration_seconds,
                         self.minimum_coverage)
        if self.minimum_total_growth <= 0 or not 0 < self.minimum_r_squared <= 1:
            raise ValueError("linear-growth thresholds are invalid")
        if not 0 < self.maximum_normalized_rmse < 1 or not 0 < self.maximum_rate_cv < 1:
            raise ValueError("linear-growth error bounds are invalid")
        if not 1 <= self.maximum_candidate_windows <= 128:
            raise ValueError("linear-growth candidate bound is invalid")


@dataclass(frozen=True, slots=True)
class PeriodicJumpsConfig:
    minimum_observations: int = 10
    minimum_duration_seconds: int = 3600
    minimum_jump_delta: int = 50
    minimum_prominence_ratio: float = 5.0
    minimum_repetitions: int = 3
    maximum_spacing_cv: float = 0.20
    maximum_magnitude_cv: float = 0.50
    cadence_confounded_tolerance: float = 0.08
    minimum_coverage: float = 0.80

    def __post_init__(self) -> None:
        _validate_common(self.minimum_observations, self.minimum_duration_seconds,
                         self.minimum_coverage)
        if self.minimum_jump_delta <= 0 or self.minimum_prominence_ratio <= 1:
            raise ValueError("periodic-jump thresholds are invalid")
        if not 3 <= self.minimum_repetitions <= 32:
            raise ValueError("periodic-jump repetition bound is invalid")
        if not 0 < self.maximum_spacing_cv < 1 or not 0 < self.maximum_magnitude_cv <= 1:
            raise ValueError("periodic-jump variation bounds are invalid")
        if not 0 <= self.cadence_confounded_tolerance <= 0.5:
            raise ValueError("periodic-jump cadence tolerance is invalid")


def _validate_common(observations: int, duration: int, coverage: float) -> None:
    if observations < 2 or duration <= 0 or not 0 < coverage <= 1:
        raise ValueError("detector common bounds are invalid")


@dataclass(frozen=True, slots=True)
class AnalysisManifest:
    manifest_version: str
    preprocessing_version: str
    aggregator_version: str
    delayed_spike: DelayedSpikeConfig
    linear_growth: LinearGrowthConfig
    periodic_jumps: PeriodicJumpsConfig

    def __post_init__(self) -> None:
        for value in (self.manifest_version, self.preprocessing_version, self.aggregator_version):
            if not value or len(value) > 64:
                raise ValueError("manifest versions must be bounded non-empty values")

    def canonical_dict(self) -> Mapping[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def default_manifest() -> AnalysisManifest:
    from .aggregation import AGGREGATOR_VERSION
    from .preprocessing import PREPROCESSING_VERSION

    return AnalysisManifest(
        "1.0.0", PREPROCESSING_VERSION, AGGREGATOR_VERSION,
        DelayedSpikeConfig(), LinearGrowthConfig(), PeriodicJumpsConfig(),
    )
