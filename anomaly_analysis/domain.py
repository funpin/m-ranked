from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Mapping, TypeAlias
from uuid import UUID


class Metric(str, Enum):
    VIEWS = "views"
    REACTIONS = "reactions"
    COMMENTS = "comments"
    SHARES = "shares"


class ObservationQuality(str, Enum):
    UNKNOWN = "unknown"
    ROUNDED = "rounded"
    ESTIMATED = "estimated"
    EXACT = "exact"
    DEGRADED = "degraded"
    SUSPECTED_RESET = "suspected_reset"
    INVALID = "invalid"

    @property
    def usable(self) -> bool:
        return self not in {self.INVALID, self.SUSPECTED_RESET}

    @property
    def trusted_derivative(self) -> bool:
        return self in {self.EXACT, self.ROUNDED}


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MetricObservation:
    snapshot_id: str
    observed_at: datetime
    age_seconds: int
    value: int | None
    quality: ObservationQuality
    synthetic: bool = False
    interval_uncertain: bool = False
    correction_sequence: int = 0
    supersedes_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be blank")
        object.__setattr__(self, "observed_at", utc(self.observed_at, "observed_at"))
        if self.age_seconds < 0 or self.correction_sequence < 0:
            raise ValueError("age_seconds and correction_sequence must be non-negative")
        if self.value is not None and self.value < 0:
            raise ValueError("cumulative metric value must be non-negative")


@dataclass(frozen=True, slots=True)
class MetricSegment:
    start: MetricObservation
    end: MetricObservation
    elapsed_seconds: float
    delta: int
    rate_per_second: float
    trusted: bool
    break_reason: str | None = None

    def __post_init__(self) -> None:
        if self.elapsed_seconds <= 0 or not isfinite(self.rate_per_second):
            raise ValueError("segment elapsed time and rate must be finite and positive")


@dataclass(frozen=True, slots=True)
class PublicationHistory:
    publication_id: UUID
    institution_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    history_completeness: str
    source_dataset_revision: int
    source_revision_at: datetime
    metric_semantics_version: int
    capability_version: int
    series: Mapping[Metric, tuple[MetricObservation, ...]]
    deleted_at: datetime | None = None
    expected_sampling_seconds: int | None = None
    # Seeded analytics.platform_metric_capability as of the pinned revision.
    # Unsupported metrics are never analyzed and never treated as zero.
    supported_metrics: frozenset[Metric] = frozenset(Metric)

    def __post_init__(self) -> None:
        if self.platform not in {"telegram", "vk", "max", "rutube"}:
            raise ValueError("unsupported platform")
        if any(metric not in Metric for metric in self.supported_metrics):
            raise ValueError("supported_metrics contains unsupported metric")
        object.__setattr__(self, "supported_metrics", frozenset(self.supported_metrics))
        if self.source_dataset_revision <= 0:
            raise ValueError("source_dataset_revision must be positive")
        if self.metric_semantics_version <= 0 or self.capability_version <= 0:
            raise ValueError("semantic and capability versions must be positive")
        object.__setattr__(self, "published_at", utc(self.published_at, "published_at"))
        object.__setattr__(self, "source_revision_at", utc(self.source_revision_at, "source_revision_at"))
        if self.deleted_at is not None:
            object.__setattr__(self, "deleted_at", utc(self.deleted_at, "deleted_at"))
        if self.expected_sampling_seconds is not None and self.expected_sampling_seconds <= 0:
            raise ValueError("expected_sampling_seconds must be positive")
        copied = {metric: tuple(observations) for metric, observations in self.series.items()}
        if any(metric not in Metric for metric in copied):
            raise ValueError("series contains unsupported metric")
        object.__setattr__(self, "series", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class EvidenceInterval:
    start_snapshot_id: str
    end_snapshot_id: str
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_at", utc(self.start_at, "start_at"))
        object.__setattr__(self, "end_at", utc(self.end_at, "end_at"))
        if self.end_at <= self.start_at:
            raise ValueError("evidence interval must have positive duration")


@dataclass(frozen=True, slots=True)
class Finding:
    detector_id: str
    detector_version: str
    metric: Metric
    score: float
    severity: Severity
    explanation_code: str
    suspicious_interval: EvidenceInterval
    evidence: Mapping[str, int | float | str | bool | None]
    quality_codes: tuple[str, ...] = ()
    alternative_explanation_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1 or not isfinite(self.score):
            raise ValueError("finding score must be finite and in [0,1]")
        if len(self.evidence) > 32:
            raise ValueError("finding evidence must be bounded")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class Clean:
    detector_id: str
    detector_version: str
    metric: Metric
    evidence_code: str = "evaluated_no_finding"


@dataclass(frozen=True, slots=True)
class Abstained:
    detector_id: str
    detector_version: str
    metric: Metric
    reason_code: str


DetectorOutcome: TypeAlias = Finding | Clean | Abstained


def severity_for(score: float) -> Severity:
    if score >= 0.8:
        return Severity.HIGH
    if score >= 0.5:
        return Severity.MEDIUM
    return Severity.LOW
