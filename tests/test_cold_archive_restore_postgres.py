"""Месяц уходит в холодный архив и возвращается без потерь (0063).

Та же одноразовая база, что у теста конвейера архива:

    MRANKED_TEST_ARCHIVE_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked
    MRANKED_TEST_ARCHIVE_MAINTENANCE_DSN=postgresql://maintenance:…@127.0.0.1:…/mranked
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pyarrow")
from test_cold_archive_pipeline_postgres import (  # noqa: E402,F401 — фикстура месяца
    ADMIN, MAINTENANCE, connect, copy_to_second_server, posts,
)
from operations.cold_archive.pipeline import Pipeline, Settings  # noqa: E402
from operations.cold_archive.restore import restore_month  # noqa: E402

pytestmark = pytest.mark.skipif(not (ADMIN and MAINTENANCE), reason="disposable archive PostgreSQL DSNs are required")
POINTS = "SELECT * FROM ingest.publication_metric_point WHERE published_month = %s ORDER BY id"
TECHNICAL = ("ingested_xid", "packed")
HOT_ONLY = ("source_fingerprint", "semantic_fingerprint", "ingested_xid", "packed")


def rows_without(rows, keys):
    return [{key: value for key, value in row.items() if key not in keys} for row in rows]


def assert_same(actual, expected, keys):
    """Строки равны без перечисленных полей; иначе — первая разница по полям."""
    actual, expected = rows_without(actual, keys), rows_without(expected, keys)
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        differing = {key: (got.get(key), want.get(key)) for key in set(got) | set(want) if got.get(key) != want.get(key)}
        assert not differing, f"snapshot {want.get('id')}: {differing}"


def test_archived_month_comes_back_exactly_and_packs(posts, tmp_path):
    month, _ = posts
    root, remote = tmp_path / "main", tmp_path / "server-1"
    with connect(ADMIN) as connection:
        before = connection.execute(POINTS, (month,)).fetchall()
    result = Pipeline(MAINTENANCE, Settings(root=root, cold_after_days=30, fence_deadline=timedelta(minutes=5),
                                            pace=0.0), sleep=copy_to_second_server(root, remote)).run(month)
    assert result["status"] == "cold"
    with connect(ADMIN) as connection:
        assert connection.execute(POINTS, (month,)).fetchall() == []

    with connect(MAINTENANCE) as connection:
        restored = restore_month(connection, root, month)
    assert restored.rows == len(before) == restored.restored and restored.files == 1

    with connect(ADMIN) as connection:
        after = connection.execute(POINTS, (month,)).fetchall()
        assert_same(after, before, TECHNICAL)
        # Повтор возврата ничего не дублирует.
    with connect(MAINTENANCE) as connection:
        assert restore_month(connection, root, month).restored == 0
    with connect(ADMIN) as connection:
        for publication_id in {row["publication_id"] for row in before}:
            connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                               (publication_id, datetime.now(timezone.utc)))
        packed = connection.execute(POINTS, (month,)).fetchall()
    assert all(row["packed"] for row in packed)
    assert_same(packed, before, HOT_ONLY)
