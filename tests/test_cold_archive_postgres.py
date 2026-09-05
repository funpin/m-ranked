from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from operations.cold_archive.model import MonthRange
from operations.cold_archive.service import ColdArchiveService


MAINTENANCE_DSN = os.environ.get("MRANKED_TEST_MAINTENANCE_DSN")


@pytest.mark.skipif(
    not MAINTENANCE_DSN,
    reason="set MRANKED_TEST_MAINTENANCE_DSN after loading the golden bridge fixture",
)
def test_real_postgres_partition_archive_is_verified_and_idempotent(tmp_path: Path):
    with psycopg.connect(str(MAINTENANCE_DSN)) as connection:
        month = connection.execute(
            "SELECT min(published_month) FROM ingest.publication_metric_snapshot"
        ).fetchone()[0]
    if month is None:
        pytest.skip("target database has no snapshot fixture")

    service = ColdArchiveService(
        str(MAINTENANCE_DSN), tmp_path, batch_size=2, min_free_bytes=0
    )
    first = service.archive(MonthRange(month))
    second = service.archive(MonthRange(month))

    assert first.verification.row_count > 0
    assert first.verification.sample_rows_read > 0
    assert first.verification.compression == "zstd"
    assert first.object_path.is_file()
    assert first.manifest_path.is_file()
    assert first.object_path.stat().st_mode & 0o777 == 0o600
    assert first.manifest_path.stat().st_mode & 0o777 == 0o600
    assert second.reused is True
    assert second.manifest_id == first.manifest_id
    assert second.verification.sha256 == first.verification.sha256
