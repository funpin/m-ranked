from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq
import pytest

from operations.cold_archive.model import MonthRange
from operations.cold_archive.parquet import (
    ARCHIVE_SCHEMA,
    ParquetArchiveWriter,
    normalize_row,
    verify_archive,
)
from operations.cold_archive.service import ColdArchiveService


UTC = timezone.utc


def archive_row(**changes):
    row = {
        "published_month": date(2026, 1, 1),
        "snapshot_id": 7,
        "publication_id": uuid4(),
        "collection_run_id": uuid4(),
        "primary_account_id": uuid4(),
        "platform": "telegram",
        "published_at": datetime(2026, 1, 2, 10, tzinfo=UTC),
        "observed_at": datetime(2026, 1, 2, 11, tzinfo=UTC),
        "collected_at": datetime(2026, 1, 2, 11, 0, 1, tzinfo=UTC),
        "age_seconds": 3600,
        "sampling_bucket": 1,
        "views_count": 0,
        "reactions_count": None,
        "comments_count": 0,
        "shares_count": None,
        "quality": "exact",
        "interval_uncertain": False,
        "synthetic": False,
        "metric_semantics_version": 1,
        "capability_version": 1,
        "source_fingerprint": "sha256:fixture",
        "created_at": datetime(2026, 1, 2, 11, 0, 1, tzinfo=UTC),
        "reaction_breakdown_json": {"custom:1": 0, "👍": 2},
    }
    row.update(changes)
    return row


def test_month_range_is_strict_and_half_open():
    month = MonthRange.parse("2026-12")
    assert month.start == date(2026, 12, 1)
    assert month.end == date(2027, 1, 1)
    assert month.start_utc.isoformat() == "2026-12-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="YYYY-MM"):
        MonthRange.parse("2026-1")
    with pytest.raises(ValueError, match="first calendar day"):
        MonthRange(date(2026, 1, 2))


def test_archive_schema_is_explicit_and_excludes_secrets_and_raw_payloads():
    names = set(ARCHIVE_SCHEMA.names)
    assert {
        "observed_at",
        "collected_at",
        "views_count",
        "reaction_breakdown_json",
    } <= names
    assert not names.intersection(
        {"raw_payload", "raw_json", "token", "access_token", "cookie", "error"}
    )
    with pytest.raises(ValueError, match="unexpected"):
        normalize_row({**archive_row(), "access_token": "must-not-archive"})


def test_parquet_zstd_roundtrip_preserves_null_zero_utc_and_breakdown(tmp_path: Path):
    path = tmp_path / "archive.parquet"
    rows = [
        archive_row(),
        archive_row(
            snapshot_id=8,
            observed_at=datetime(2026, 1, 3, 12, tzinfo=UTC),
            collected_at=datetime(2026, 1, 3, 12, 0, 1, tzinfo=UTC),
            views_count=None,
            reactions_count=0,
            reaction_breakdown_json='{"❤":0}',
        ),
    ]
    with ParquetArchiveWriter(path) as writer:
        writer.append(rows[:1])
        writer.append(rows[1:])
        writer.close()

    verified = verify_archive(path, expected_row_count=2, sample_size=2)

    assert verified.row_count == 2
    assert verified.compression == "zstd"
    assert verified.sample_rows_read == 2
    assert verified.min_observed_at == rows[0]["observed_at"]
    assert verified.max_observed_at == rows[1]["observed_at"]
    table = pq.read_table(path)
    decoded = table.to_pylist()
    assert decoded[0]["views_count"] == 0
    assert decoded[0]["reactions_count"] is None
    assert decoded[1]["views_count"] is None
    assert decoded[1]["reactions_count"] == 0
    assert decoded[0]["collected_at"] == rows[0]["collected_at"]
    assert json.loads(decoded[0]["reaction_breakdown_json"]) == {
        "custom:1": 0,
        "👍": 2,
    }


def test_archive_verification_detects_checksum_corruption(tmp_path: Path):
    path = tmp_path / "archive.parquet"
    with ParquetArchiveWriter(path) as writer:
        writer.append([archive_row()])
        writer.close()
    verified = verify_archive(path)
    with path.open("ab") as stream:
        stream.write(b"corruption")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_archive(path, expected_sha256=verified.sha256)


def test_drop_requires_exact_confirmation(tmp_path: Path):
    service = ColdArchiveService(
        "postgresql://redacted.invalid/db", tmp_path, min_free_bytes=0
    )
    with pytest.raises(ValueError, match="DROP_HOT_PARTITION"):
        service.archive(MonthRange.parse("2026-01"), drop_hot_partition=True)
