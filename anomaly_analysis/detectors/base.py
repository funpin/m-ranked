from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import DetectorOutcome, Metric, PublicationHistory
from ..preprocessing import PreparedSeries


@dataclass(frozen=True, slots=True)
class DetectorMetadata:
    detector_id: str
    implementation_version: str
    supported_metrics: frozenset[Metric]
    minimum_observations: int
    minimum_duration_seconds: int


class Detector(Protocol):
    metadata: DetectorMetadata

    def evaluate(
        self, history: PublicationHistory, metric: Metric, prepared: PreparedSeries
    ) -> DetectorOutcome: ...
