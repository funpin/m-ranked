from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import AnalysisManifest
from .detectors import DelayedSpikeDetector, LinearGrowthDetector, PeriodicJumpsDetector
from .detectors.base import Detector


@dataclass(frozen=True, slots=True)
class DetectorRegistry:
    detectors: tuple[Detector, ...]

    def __post_init__(self) -> None:
        identities: set[tuple[str, str]] = set()
        ids: set[str] = set()
        for detector in self.detectors:
            metadata = detector.metadata
            if not metadata.detector_id.strip() or not metadata.implementation_version.strip():
                raise ValueError("detector identity must not be blank")
            if metadata.detector_id in ids:
                raise ValueError(f"duplicate detector id: {metadata.detector_id}")
            identity = (metadata.detector_id, metadata.implementation_version)
            if identity in identities or not metadata.supported_metrics:
                raise ValueError("conflicting detector identity or empty metric set")
            ids.add(metadata.detector_id)
            identities.add(identity)

    @classmethod
    def from_manifest(cls, manifest: AnalysisManifest) -> "DetectorRegistry":
        return cls((
            DelayedSpikeDetector(manifest.delayed_spike),
            LinearGrowthDetector(manifest.linear_growth),
            PeriodicJumpsDetector(manifest.periodic_jumps),
        ))

    @classmethod
    def validated(cls, detectors: Iterable[Detector]) -> "DetectorRegistry":
        return cls(tuple(detectors))
