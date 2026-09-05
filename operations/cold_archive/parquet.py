from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .model import ArchiveVerification


DATASET_TYPE = "publication_metric_snapshot"
SCHEMA_VERSION = 2
COMPRESSION = "zstd"

# This whitelist is deliberately independent of cursor metadata. Raw payloads,
# error text, tokens and migration evidence cannot enter the product archive.
ARCHIVE_SCHEMA = pa.schema(
    [
        pa.field("published_month", pa.date32(), nullable=False),
        pa.field("snapshot_id", pa.int64(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("collection_run_id", pa.string(), nullable=False),
        pa.field("primary_account_id", pa.string(), nullable=False),
        pa.field("platform", pa.string(), nullable=False),
        pa.field("published_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("collected_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("age_seconds", pa.int64(), nullable=False),
        pa.field("sampling_bucket", pa.int64(), nullable=False),
        pa.field("views_count", pa.int64()),
        pa.field("reactions_count", pa.int64()),
        pa.field("comments_count", pa.int64()),
        pa.field("shares_count", pa.int64()),
        pa.field("quality", pa.string(), nullable=False),
        pa.field("interval_uncertain", pa.bool_(), nullable=False),
        pa.field("synthetic", pa.bool_(), nullable=False),
        pa.field("metric_semantics_version", pa.int32(), nullable=False),
        pa.field("capability_version", pa.int32(), nullable=False),
        pa.field("source_fingerprint", pa.string(), nullable=False),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("reaction_breakdown_json", pa.string(), nullable=False),
    ],
    metadata={
        b"mranked.dataset_type": DATASET_TYPE.encode(),
        b"mranked.schema_version": str(SCHEMA_VERSION).encode(),
        b"mranked.timezone": b"UTC",
        b"mranked.interval": b"[partition_start,partition_end)",
    },
)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    expected = set(ARCHIVE_SCHEMA.names)
    missing = expected.difference(row)
    unexpected = set(row).difference(expected)
    if missing or unexpected:
        raise ValueError(
            f"archive row schema mismatch; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    result = dict(row)
    for name in ("publication_id", "collection_run_id", "primary_account_id"):
        result[name] = str(result[name])
    result["platform"] = str(result["platform"])
    result["quality"] = str(result["quality"])
    for name in ("published_at", "observed_at", "collected_at", "created_at"):
        result[name] = _as_utc(result[name], name)
    breakdown = result["reaction_breakdown_json"]
    if isinstance(breakdown, str):
        decoded = json.loads(breakdown)
    else:
        decoded = breakdown or {}
    if not isinstance(decoded, dict):
        raise ValueError("reaction breakdown must be a JSON object")
    result["reaction_breakdown_json"] = json.dumps(
        decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return result


def _as_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


class ParquetArchiveWriter:
    """A bounded writer: each call materializes at most one cursor batch."""

    def __init__(self, path: Path):
        self.path = path
        self._writer = pq.ParquetWriter(
            path,
            ARCHIVE_SCHEMA,
            compression=COMPRESSION,
            write_statistics=True,
            use_dictionary=True,
        )
        self.row_count = 0
        self.min_observed_at: datetime | None = None
        self.max_observed_at: datetime | None = None
        self._closed = False

    def append(self, rows: Iterable[Mapping[str, Any]]) -> int:
        normalized = [normalize_row(row) for row in rows]
        if not normalized:
            return 0
        table = pa.Table.from_pylist(normalized, schema=ARCHIVE_SCHEMA)
        self._writer.write_table(table, row_group_size=len(normalized))
        observed = [row["observed_at"] for row in normalized]
        batch_min = min(observed)
        batch_max = max(observed)
        self.min_observed_at = (
            batch_min
            if self.min_observed_at is None
            else min(self.min_observed_at, batch_min)
        )
        self.max_observed_at = (
            batch_max
            if self.max_observed_at is None
            else max(self.max_observed_at, batch_max)
        )
        self.row_count += len(normalized)
        return len(normalized)

    def close(self) -> None:
        if self._closed:
            return
        # An explicit empty table gives a valid, typed archive for empty ranges.
        if self.row_count == 0:
            self._writer.write_table(pa.Table.from_pylist([], schema=ARCHIVE_SCHEMA))
        self._writer.close()
        self._closed = True

    def __enter__(self) -> "ParquetArchiveWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def verify_archive(
    path: Path,
    *,
    expected_row_count: int | None = None,
    expected_sha256: str | None = None,
    sample_size: int = 16,
) -> ArchiveVerification:
    if sample_size < 1 or sample_size > 10_000:
        raise ValueError("sample_size must be between 1 and 10000")
    digest = sha256_file(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("archive SHA-256 mismatch")

    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    if schema != ARCHIVE_SCHEMA:
        raise ValueError(
            f"archive Arrow schema or metadata does not match version {SCHEMA_VERSION}"
        )
    row_count = parquet.metadata.num_rows
    if expected_row_count is not None and row_count != expected_row_count:
        raise ValueError(
            f"archive row count mismatch: expected {expected_row_count}, got {row_count}"
        )

    compressions = {
        parquet.metadata.row_group(group).column(column).compression.lower()
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if compressions and compressions != {COMPRESSION}:
        raise ValueError(f"archive compression mismatch: {sorted(compressions)}")

    min_observed_at: datetime | None = None
    max_observed_at: datetime | None = None
    sample_rows_read = 0
    sample_validated = False
    for batch in parquet.iter_batches(
        batch_size=max(1, sample_size),
        columns=["observed_at", "reaction_breakdown_json"],
    ):
        observed_column = batch.column(0)
        for value in observed_column.to_pylist():
            value = _as_utc(value, "observed_at")
            min_observed_at = value if min_observed_at is None else min(min_observed_at, value)
            max_observed_at = value if max_observed_at is None else max(max_observed_at, value)
        if not sample_validated:
            sample = batch.slice(0, sample_size).to_pylist()
            for row in sample:
                decoded = json.loads(row["reaction_breakdown_json"])
                if not isinstance(decoded, dict):
                    raise ValueError("archive sample contains a non-object reaction breakdown")
            sample_rows_read = len(sample)
            sample_validated = True

    return ArchiveVerification(
        sha256=digest,
        row_count=row_count,
        min_observed_at=min_observed_at,
        max_observed_at=max_observed_at,
        sample_rows_read=sample_rows_read,
        row_groups=parquet.metadata.num_row_groups,
        compression=COMPRESSION,
    )
