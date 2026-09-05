from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid5


# This namespace is immutable migration protocol state. Changing it would change every
# imported business identity and is therefore a breaking migration format change.
BRIDGE_NAMESPACE = UUID("45f74b35-89b2-5f43-82f2-f7c5d9db6d34")
BRIDGE_VERSION = "1.2.0"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def row_hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(row)).encode("utf-8")).hexdigest()


def stable_uuid(source_namespace: str, target_type: str, natural_key: Any) -> UUID:
    """Return the same UUID for the same immutable legacy identity."""

    name = canonical_json(
        {
            "source_namespace": source_namespace,
            "target_type": target_type,
            "natural_key": natural_key,
        }
    )
    return uuid5(BRIDGE_NAMESPACE, name)


def stable_bigint(source_namespace: str, target_type: str, natural_key: Any) -> int:
    """Return a deterministic negative bigint reserved for imported high-volume rows."""

    encoded = canonical_json(
        {
            "source_namespace": source_namespace,
            "target_type": target_type,
            "natural_key": natural_key,
        }
    ).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") & ((1 << 63) - 1)
    return -(value or 1)


@dataclass(frozen=True)
class BridgeOptions:
    source: Path
    source_namespace: str
    batch_size: int = 1_000
    dry_run: bool = False
    resume: bool = True
    report_dir: Path = Path("migration/reports")

    def __post_init__(self) -> None:
        if not self.source_namespace.strip():
            raise ValueError("source_namespace must be a stable, non-empty identifier")
        if not 1 <= self.batch_size <= 50_000:
            raise ValueError("batch_size must be between 1 and 50000")


@dataclass(frozen=True)
class TableInventory:
    name: str
    columns: tuple[str, ...]
    row_count: int
    canonical_hash: str
    min_timestamp: str | None = None
    max_timestamp: str | None = None


@dataclass(frozen=True)
class SourceInventory:
    source_path: str
    source_size_bytes: int
    source_sha256: str
    schema_version: int
    quick_check: str
    foreign_key_violations: int
    captured_at: str
    tables: tuple[TableInventory, ...]
    totals: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_size_bytes": self.source_size_bytes,
            "source_sha256": self.source_sha256,
            "schema_version": self.schema_version,
            "quick_check": self.quick_check,
            "foreign_key_violations": self.foreign_key_violations,
            "captured_at": self.captured_at,
            "tables": [
                {
                    "name": table.name,
                    "columns": list(table.columns),
                    "row_count": table.row_count,
                    "canonical_hash": table.canonical_hash,
                    "min_timestamp": table.min_timestamp,
                    "max_timestamp": table.max_timestamp,
                }
                for table in self.tables
            ],
            "totals": dict(self.totals),
        }


@dataclass
class BridgeStats:
    batch_id: UUID
    source_sha256: str
    schema_version: int
    dry_run: bool
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    rows_read: int = 0
    rows_written: int = 0
    rows_by_stream: dict[str, int] = field(default_factory=dict)
    projection_rebuild: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = utc_now()

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": str(self.batch_id),
            "source_sha256": self.source_sha256,
            "schema_version": self.schema_version,
            "dry_run": self.dry_run,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "rows_read": self.rows_read,
            "rows_written": self.rows_written,
            "rows_by_stream": dict(sorted(self.rows_by_stream.items())),
            "projection_rebuild": self.projection_rebuild,
            "warnings": self.warnings,
        }
