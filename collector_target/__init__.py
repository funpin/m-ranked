"""Canonical PostgreSQL collector runtime for the target M-Ranked stack."""

from .coordinator import PlatformSupervisor, PollCycleCoordinator
from .model import (
    AccountRef,
    CollectionContext,
    DeletionProbeOutcome,
    HistoryCompleteness,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    RunStatus,
    TrackedPublication,
)
from .normalize import CanonicalNormalizer
from .repository import PostgresCollectorRepository

__all__ = [
    "AccountRef",
    "CanonicalNormalizer",
    "CollectionContext",
    "DeletionProbeOutcome",
    "HistoryCompleteness",
    "ObservationQuality",
    "Platform",
    "PlatformSupervisor",
    "PollCycleCoordinator",
    "PostgresCollectorRepository",
    "RawAccountObservation",
    "RawCollectionBatch",
    "RawDeletionProbe",
    "RawPublication",
    "RunStatus",
    "TrackedPublication",
]
