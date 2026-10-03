from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from operations.cold_archive import browse


def record(index: int, points: int = 50) -> browse.BrowseRecord:
    items = [{"snapshotId": str(index * 1000 + point), "observedAt": f"2026-08-0{1 + point % 9}T00:00:00Z",
              "views": {"value": point * 10, "quality": "exact"}} for point in range(points)]
    return browse.BrowseRecord(f"00000000-0000-0000-0000-{index:012d}", "acc", datetime(2026, 8, 1, tzinfo=timezone.utc),
                               items, {"gaps": [], "successfulPolls": points}, points, index * 1000 + points)


def test_written_month_reads_back_one_post_and_is_compact(tmp_path):
    path = tmp_path / "browse-2026-08.sqlite"
    summary = browse.write(path, "2026-08", (record(index) for index in range(1, 201)))
    assert summary.publications == 200 and summary.snapshots == 200 * 50
    assert summary.sha256 == browse.sha256_file(path)
    reader = browse.BrowseReader()
    found = reader.read(path, record(17).publication_id)
    assert found is not None and found.items == record(17).items and found.coverage == {"gaps": [], "successfulPolls": 50}
    assert reader.read(path, "missing") is None
    raw = sum(len(str(record(index).items)) for index in range(1, 201))
    assert summary.size_bytes * 5 < raw


def test_existing_file_is_never_overwritten(tmp_path):
    path = tmp_path / "browse-2026-08.sqlite"
    browse.write(path, "2026-08", [record(1)])
    with pytest.raises(FileExistsError):
        browse.write(path, "2026-08", [record(2)])


def test_verify_rejects_a_tampered_or_mislabelled_file(tmp_path):
    path = tmp_path / "browse-2026-08.sqlite"
    browse.write(path, "2026-08", [record(1), record(2)])
    with pytest.raises(ValueError):
        browse.verify(path, "2026-09")
    connection = sqlite3.connect(path)
    connection.execute("UPDATE meta SET value='5' WHERE key='publications'")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError):
        browse.verify(path, "2026-08")
