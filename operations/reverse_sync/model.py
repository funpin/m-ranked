from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import UUID


STATE_VERSION = 3
ACTIVE_STATES = frozenset({"active", "drained", "verified"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reverse-sync datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Revision:
    id: int
    cause: str
    source_run_id: UUID | None
    committed_at: datetime
    correlation_id: UUID
    metadata: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return canonical_value({
            "id": self.id,
            "cause": self.cause,
            "sourceRunId": self.source_run_id,
            "committedAt": self.committed_at,
            "correlationId": self.correlation_id,
            "metadata": self.metadata,
        })


@dataclass(frozen=True, slots=True)
class SyncPlan:
    baseline_revision_ids: tuple[int, ...]
    revision_ids: tuple[int, ...]
    revisions: tuple[Revision, ...]
    accounts: tuple[Mapping[str, Any], ...]
    publications: tuple[Mapping[str, Any], ...]
    snapshots: tuple[Mapping[str, Any], ...]
    collection_runs: tuple[Mapping[str, Any], ...]
    generated_at: datetime

    @property
    def digest(self) -> str:
        return payload_sha256(self.canonical_payload())

    def canonical_payload(self) -> dict[str, Any]:
        return canonical_value({
            "baselineRevisionIds": self.baseline_revision_ids,
            "revisionIds": self.revision_ids,
            "revisions": [revision.as_dict() for revision in self.revisions],
            "accounts": self.accounts,
            "publications": self.publications,
            "snapshots": self.snapshots,
            "collectionRuns": self.collection_runs,
        })

    def counts(self) -> dict[str, int]:
        return {
            "revisions": len(self.revisions),
            "accounts": len(self.accounts),
            "publications": len(self.publications),
            "snapshots": len(self.snapshots),
            "collectionRuns": len(self.collection_runs),
        }


@dataclass(frozen=True, slots=True)
class JournalState:
    status: str
    source_namespace: str
    operator: str
    ticket: str
    started_at: datetime
    rollback_deadline: datetime
    s_final_batch_id: UUID
    s_final_source_sha256: str
    plan_digest: str | None = None
    drained_at: datetime | None = None
    verified_at: datetime | None = None
    stopped_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return canonical_value({
            "status": self.status,
            "sourceNamespace": self.source_namespace,
            "operator": self.operator,
            "ticket": self.ticket,
            "startedAt": self.started_at,
            "rollbackDeadline": self.rollback_deadline,
            "sFinalBatchId": self.s_final_batch_id,
            "sFinalSourceSha256": self.s_final_source_sha256,
            "planDigest": self.plan_digest,
            "drainedAt": self.drained_at,
            "verifiedAt": self.verified_at,
            "stoppedAt": self.stopped_at,
        })


def require_nonempty(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    if any(character in normalized for character in ("\n", "\r", "\x00")):
        raise ValueError(f"{field} contains a control character")
    return normalized


def require_revision_ids(values: Sequence[int]) -> tuple[int, ...]:
    result = tuple(sorted({int(value) for value in values}))
    if any(value <= 0 for value in result):
        raise ValueError("revision ids must be positive")
    return result
