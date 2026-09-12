"""Deterministic publication anomaly analysis.

The package owns derived judgments only.  It deliberately has no HTTP surface
and its analytical modules do not import database or runtime configuration.
"""

from .aggregation import AGGREGATOR_VERSION, AggregateResult, aggregate
from .config import AnalysisManifest, default_manifest
from .domain import (
    Abstained,
    Clean,
    Finding,
    Metric,
    MetricObservation,
    ObservationQuality,
    PublicationHistory,
    Severity,
)

__all__ = [
    "AGGREGATOR_VERSION",
    "Abstained",
    "AggregateResult",
    "AnalysisManifest",
    "Clean",
    "Finding",
    "Metric",
    "MetricObservation",
    "ObservationQuality",
    "PublicationHistory",
    "Severity",
    "aggregate",
    "default_manifest",
]
