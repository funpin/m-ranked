from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid5


RUN_NAMESPACE = UUID("aaeddd31-e391-5dd6-a377-d449f23550dc")
PUBLICATION_NAMESPACE = UUID("43ea4c3b-a155-5af1-96ea-54752772f901")
CONTENT_GROUP_NAMESPACE = UUID("e0420527-9900-5cf5-a36e-b2787d3a9b29")
PARTITION_NAMESPACE = UUID("f8d73cf8-79a8-5e19-b326-fd6770c91712")
RAW_PAYLOAD_NAMESPACE = UUID("6f7b083c-bcb4-5cf6-96ac-f26d4be93156")
CHECKPOINT_NAMESPACE = UUID("03861af5-ad24-5e84-8e2d-b768f5467095")


class Platform(str, Enum):
    TELEGRAM = "telegram"
    VK = "vk"
    MAX = "max"
    RUTUBE = "rutube"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ObservationQuality(str, Enum):
    UNKNOWN = "unknown"
    ROUNDED = "rounded"
    ESTIMATED = "estimated"
    EXACT = "exact"
    DEGRADED = "degraded"
    SUSPECTED_RESET = "suspected_reset"
    INVALID = "invalid"


class HistoryCompleteness(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FORCED_INCOMPLETE = "forced_incomplete"


class DeletionProbeOutcome(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    TRANSIENT_ERROR = "transient_error"
    CONFIRMED_DELETED = "confirmed_deleted"
    UNSUPPORTED = "unsupported"


class IdentityRole(str, Enum):
    PRIMARY = "primary"
    ALBUM_MEMBER = "album_member"
    JOINT_AUTHOR = "joint_author"
    SOURCE = "source"
    REPOST_SOURCE = "repost_source"


def utc(value: datetime, field_name: str) -> datetime:
    """Validate an instant and normalize it to UTC without guessing naive values."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def nonempty(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


@dataclass(frozen=True, slots=True)
class AccountRef:
    id: UUID
    institution_id: UUID
    platform: Platform
    canonical_external_id: str
    access_mode: str
    current_username: str | None = None
    current_title: str | None = None
    current_url: str | None = None
    native_external_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "canonical_external_id",
            nonempty(self.canonical_external_id, "canonical_external_id"),
        )
        object.__setattr__(self, "access_mode", nonempty(self.access_mode, "access_mode"))


@dataclass(frozen=True, slots=True)
class CollectionContext:
    run_id: UUID
    correlation_id: UUID
    platform: Platform
    partition_key: str
    collector_version: str
    scheduled_at: datetime
    started_at: datetime

    @classmethod
    def create(
        cls,
        platform: Platform,
        partition_key: str,
        collector_version: str,
        scheduled_at: datetime,
        started_at: datetime,
    ) -> "CollectionContext":
        partition = nonempty(partition_key, "partition_key")
        version = nonempty(collector_version, "collector_version")
        scheduled = utc(scheduled_at, "scheduled_at")
        started = utc(started_at, "started_at")
        if started < scheduled:
            raise ValueError("started_at must not precede scheduled_at")
        key = "|".join((platform.value, partition, version, scheduled.isoformat()))
        run_id = uuid5(RUN_NAMESPACE, f"run|{key}")
        correlation_id = uuid5(RUN_NAMESPACE, f"correlation|{key}")
        return cls(
            run_id, correlation_id, platform, partition, version, scheduled, started,
        )

    @property
    def partition_scope_id(self) -> UUID:
        return uuid5(
            PARTITION_NAMESPACE,
            f"{self.platform.value}|{self.partition_key}",
        )


@dataclass(frozen=True, slots=True)
class IdentityCandidate:
    external_id: str
    role: IdentityRole
    source_external_id: str | None = None
    public_url: str | None = None


@dataclass(frozen=True, slots=True)
class RawAccountObservation:
    observed_at: datetime
    collected_at: datetime
    subscriber_count: int | None
    subscriber_display: str | None = None
    quality: ObservationQuality = ObservationQuality.EXACT
    username: str | None = None
    title: str | None = None
    url: str | None = None
    native_external_id: str | None = None
    source: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawPublication:
    external_id: str
    published_at: datetime
    discovered_at: datetime
    observed_at: datetime
    collected_at: datetime
    publication_type: str
    metrics: Mapping[str, int | float | None]
    source: Mapping[str, Any]
    public_url: str | None = None
    source_external_id: str | None = None
    identities: tuple[IdentityCandidate, ...] = ()
    reaction_breakdown: Mapping[str, int] = field(default_factory=dict)
    quality: ObservationQuality = ObservationQuality.EXACT
    metric_quality: Mapping[str, ObservationQuality] = field(default_factory=dict)
    suspected_reset_metrics: frozenset[str] = frozenset()
    history_completeness: HistoryCompleteness = HistoryCompleteness.INCOMPLETE
    is_repost: bool = False
    group_key: str | None = None
    synthetic: bool = False
    interval_uncertain: bool = False
    sampling_interval_seconds: int = 300
    sampling_bucket: int | None = None
    quality_flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawDeletionProbe:
    """A point-lookup result; confirmation is derived by the repository.

    ``missing`` is allowed only for a successful provider-specific point lookup
    whose contract says that an omitted/not-found object is authoritative.
    Adapters must classify rate limits, authentication failures, transport
    failures, and ambiguous responses as ``transient_error`` instead.
    """

    publication_id: UUID
    observed_at: datetime
    outcome: DeletionProbeOutcome
    reason_code: str
    confirmation_threshold: int


@dataclass(frozen=True, slots=True)
class RawCollectionBatch:
    account: AccountRef
    account_observation: RawAccountObservation | None
    publications: tuple[RawPublication, ...]
    source_name: str
    source_version: str
    cursor: str | None = None
    deletion_probes: tuple[RawDeletionProbe, ...] = ()
    refresh_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalAccountObservation:
    observed_at: datetime
    collected_at: datetime
    subscriber_count: int | None
    subscriber_display: str | None
    quality: ObservationQuality
    source_fingerprint: str
    sanitized_source: Mapping[str, Any]
    username: str | None = None
    title: str | None = None
    url: str | None = None
    native_external_id: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalMetricSnapshot:
    observed_at: datetime
    collected_at: datetime
    age_seconds: int
    sampling_bucket: int
    published_month: date
    views_count: int | None
    reactions_count: int | None
    comments_count: int | None
    shares_count: int | None
    quality: ObservationQuality
    metric_quality: Mapping[str, ObservationQuality]
    interval_uncertain: bool
    synthetic: bool
    reaction_breakdown: Mapping[str, int]
    source_fingerprint: str
    sanitized_source: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalPublication:
    id: UUID
    account_id: UUID
    content_group_id: UUID | None
    external_id: str
    source_external_id: str | None
    identities: tuple[IdentityCandidate, ...]
    public_url: str | None
    published_at: datetime
    discovered_at: datetime
    publication_type: str
    is_repost: bool
    history_completeness: HistoryCompleteness
    synthetic_baseline_allowed: bool
    quality_flags: Mapping[str, Any]
    snapshot: CanonicalMetricSnapshot


@dataclass(frozen=True, slots=True)
class CanonicalDeletionProbe:
    publication_id: UUID
    observed_at: datetime
    outcome: DeletionProbeOutcome
    reason_code: str
    confirmation_threshold: int


@dataclass(frozen=True, slots=True)
class CanonicalAccountBatch:
    account: AccountRef
    context: CollectionContext
    account_observation: CanonicalAccountObservation | None
    publications: tuple[CanonicalPublication, ...]
    source_name: str
    source_version: str
    cursor: str | None
    deletion_probes: tuple[CanonicalDeletionProbe, ...] = ()
    refresh_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class TrackedPublication:
    """Repository view used by bounded, circular point-refresh planning."""

    id: UUID
    external_id: str
    source_external_id: str | None
    public_url: str | None
    published_at: datetime
    identity_external_ids: tuple[str, ...]
    latest_observed_at: datetime | None
    latest_sampling_bucket: int | None

    @property
    def cursor(self) -> str:
        return str(self.id)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: UUID
    account_id: UUID
    discovered_count: int
    snapshot_count: int
    revision_id: int | None


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: UUID
    platform: Platform
    status: RunStatus
    account_count: int
    error_count: int
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformOutcome:
    platform: Platform
    summary: RunSummary | None
    error_code: str | None = None


def publication_uuid(account_id: UUID, external_id: str) -> UUID:
    return uuid5(PUBLICATION_NAMESPACE, f"{account_id}|{nonempty(external_id, 'external_id')}")


def content_group_uuid(account_id: UUID, group_key: str) -> UUID:
    return uuid5(CONTENT_GROUP_NAMESPACE, f"{account_id}|{nonempty(group_key, 'group_key')}")


def raw_payload_uuid(
    run_id: UUID,
    owner_type: str,
    owner_id: UUID,
    fingerprint: str,
) -> UUID:
    key = f"{run_id}|{nonempty(owner_type, 'owner_type')}|{owner_id}|{fingerprint}"
    return uuid5(RAW_PAYLOAD_NAMESPACE, key)


def checkpoint_uuid(checkpoint_key: str, scope_type: str, scope_id: UUID) -> UUID:
    key = f"{nonempty(checkpoint_key, 'checkpoint_key')}|{scope_type}|{scope_id}"
    return uuid5(CHECKPOINT_NAMESPACE, key)
