"""Месяц из холодного архива возвращается в базу без потерь (0063).

Архив месяца — Parquet с canonical_record каждой строки, как его писала
выгрузка (до вывода архива из оборота). Тест пишет такой файл сам,
убирает горячие строки, возвращает месяц инструментом и сверяет точки.
Нужна одноразовая база со схемой:

    MRANKED_TEST_PACKED_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked
    MRANKED_TEST_STORAGE_MAINTENANCE_DSN=postgresql://maintenance:…@127.0.0.1:…/mranked
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import os
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from operations.cold_archive.restore import RestoreMismatch, restore_month  # noqa: E402
from operations.storage import store  # noqa: E402

ADMIN = os.environ.get("MRANKED_TEST_PACKED_ADMIN_DSN", "")
MAINTENANCE = os.environ.get("MRANKED_TEST_STORAGE_MAINTENANCE_DSN", "")
pytestmark = pytest.mark.skipif(not (ADMIN and MAINTENANCE), reason="disposable PostgreSQL DSNs are required")
POINTS = "SELECT * FROM ingest.publication_metric_point WHERE publication_id = ANY(%s) ORDER BY id"
TECHNICAL = ("ingested_xid", "packed")
HOT_ONLY = ("source_fingerprint", "semantic_fingerprint", "ingested_xid", "packed")


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def assert_same(actual, expected, keys):
    """Строки равны без перечисленных полей; иначе — первая разница по полям."""
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        differing = {key: (got.get(key), want.get(key)) for key in set(got) | set(want)
                     if key not in keys and got.get(key) != want.get(key)}
        assert not differing, f"snapshot {want.get('id')}: {differing}"


def unused_month(connection) -> date:
    used = {row["month"] for row in connection.execute(
        "SELECT DISTINCT date_trunc('month', published_at AT TIME ZONE 'UTC')::date AS month FROM ingest.publication")}
    return next(candidate for candidate in (date(year, number, 1) for year in (2025, 2024, 2023)
                                            for number in range(12, 0, -1)) if candidate not in used)


def archived_month(connection, root):
    """Месяц с обычной разбивкой, встроенной разбивкой r4 и исправлением — в архиве."""
    month = unused_month(connection)
    institution, account, run = uuid4(), uuid4(), uuid4()
    published = datetime(month.year, month.month, 10, 9, tzinfo=timezone.utc)
    connection.execute("INSERT INTO analytics.dataset_revision(cause, correlation_id) VALUES ('ingestion', gen_random_uuid())")
    connection.execute("INSERT INTO catalog.institution(id, canonical_name) VALUES (%s, 'Restore')", (institution,))
    connection.execute("""INSERT INTO catalog.platform_account(id, institution_id, platform, canonical_external_id,
                          access_mode) VALUES (%s, %s, 'telegram', %s, 'public_web')""", (account, institution, f"r-{account}"))
    connection.execute("""INSERT INTO ingest.collection_run(id, platform, partition_key, collector_version, started_at,
                          status, correlation_id) VALUES (%s, 'telegram', 'r', 'test', %s, 'succeeded', gen_random_uuid())""",
                       (run, published))
    connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
    posts = []
    for index in range(2):
        publication = uuid4()
        connection.execute("""INSERT INTO ingest.publication(id, primary_account_id, published_at, discovered_at,
                              publication_type, history_completeness) VALUES (%s, %s, %s, %s, 'post', 'complete')""",
                           (publication, account, published + timedelta(hours=index), published))
        posts.append(publication)
        for point in range(30):
            observed = published + timedelta(hours=index, minutes=15 * (point + 1))
            evidence = {"reaction_breakdown": {"❤️": point}, "views": "exact"} if index == 0 and point < 4 else {"views": "x"}
            with connection.transaction():
                snapshot = connection.execute("""
                    INSERT INTO ingest.publication_metric_snapshot(published_month, publication_id, collection_run_id,
                      observed_at, age_seconds, sampling_bucket, views_count, reactions_count, comments_count,
                      shares_count, quality, source_fingerprint, collected_at, metric_evidence, semantic_fingerprint)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, NULL, 'exact', %s, %s, %s, %s) RETURNING id""",
                    (month, publication, run, observed, 900 * (point + 1), point, 10 * point, point, uuid4().hex,
                     observed, Jsonb(evidence), hashlib.sha256(str(point).encode()).digest())).fetchone()["id"]
                if index == 1 and point % 5 == 0:
                    connection.execute("""INSERT INTO ingest.reaction_breakdown(snapshot_published_month, snapshot_id,
                                          reaction_key, reaction_count) VALUES (%s, %s, '👍', %s)""", (month, snapshot, point))
        # Исправление того же бакета.
        with connection.transaction():
            connection.execute("""
                INSERT INTO ingest.publication_metric_snapshot(published_month, publication_id, collection_run_id,
                  observed_at, age_seconds, sampling_bucket, views_count, reactions_count, comments_count, shares_count,
                  quality, source_fingerprint, collected_at, metric_evidence)
                VALUES (%s, %s, %s, %s, 1900, 1, 999, 1, 0, NULL, 'exact', %s, %s, '{}')""",
                (month, publication, run, published + timedelta(hours=index, minutes=31), uuid4().hex,
                 published + timedelta(hours=index, minutes=31)))
    before = connection.execute(POINTS, (posts,)).fetchall()
    # Файл архива — canonical_record каждой строки, как писала выгрузка.
    texts = [row["canonical_record"] for row in connection.execute(
        "SELECT canonical_record FROM ops_and_admin.publication_archive_canonical WHERE published_month = %s "
        "ORDER BY id", (month,)).fetchall()]
    name = f"snapshots-{month:%Y-%m}-g1.parquet"
    path = store.object_path(root, "archive_full", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"canonical_record": texts}), path, compression="zstd")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    object_id = connection.execute("""
        INSERT INTO ops_and_admin.storage_object (kind, name, size_bytes, sha256, published_month, generation, origin_node)
        VALUES ('archive_full', %s, %s, %s, %s, 1, (SELECT id FROM ops_and_admin.server_node WHERE role = 'main' LIMIT 1))
        RETURNING id""", (name, path.stat().st_size, digest, month)).fetchone()["id"]
    connection.execute("""INSERT INTO ops_and_admin.cold_archive_generation (published_month, generation, state, hot_bytes,
                          full_object_id, row_count) VALUES (%s, 1, 'cold', 0, %s, %s)""", (month, object_id, len(texts)))
    # Партиция ушла в архив: горячих строк месяца нет.
    with connection.transaction():
        connection.execute("SET LOCAL ingest.compaction = 'on'")
        connection.execute("DELETE FROM ingest.reaction_breakdown WHERE snapshot_published_month = %s", (month,))
        connection.execute("DELETE FROM ingest.publication_metric_snapshot WHERE published_month = %s", (month,))
    return month, posts, before, path


def test_archived_month_comes_back_exactly_and_packs(tmp_path):
    root = tmp_path / "store"
    with connect(ADMIN) as connection:
        connection.execute("INSERT INTO ops_and_admin.server_node (id, display_name, role, state) VALUES "
                           "('server-2', 'Main', 'main', 'active') ON CONFLICT DO NOTHING")
        month, posts, before, _ = archived_month(connection, root)
        assert connection.execute(POINTS, (posts,)).fetchall() == []
    # Встроенная разбивка r4 видна как разбивка — каноническая форма.
    assert {"❤️": 2} in [row["reaction_breakdown"] for row in before]

    with connect(MAINTENANCE) as connection:
        restored = restore_month(connection, root, month)
        assert restore_month(connection, root, month).restored == 0  # повтор ничего не дублирует
    assert restored.rows == len(before) == restored.restored and restored.files == 1

    with connect(ADMIN) as connection:
        assert_same(connection.execute(POINTS, (posts,)).fetchall(), before, TECHNICAL)
        for publication_id in posts:
            connection.execute("SELECT ingest.compact_publication_history(%s, now())", (publication_id,))
        packed = connection.execute(POINTS, (posts,)).fetchall()
    assert all(row["packed"] for row in packed)
    assert_same(packed, before, HOT_ONLY)


def test_a_damaged_archive_file_stops_the_restore(tmp_path):
    root = tmp_path / "store"
    with connect(ADMIN) as connection:
        connection.execute("INSERT INTO ops_and_admin.server_node (id, display_name, role, state) VALUES "
                           "('server-2', 'Main', 'main', 'active') ON CONFLICT DO NOTHING")
        month, posts, _, path = archived_month(connection, root)
    path.write_bytes(path.read_bytes() + b"x")
    with connect(MAINTENANCE) as connection, pytest.raises(RestoreMismatch, match="SHA-256"):
        restore_month(connection, root, month)
