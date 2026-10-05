"""Упакованная история (0059) на одноразовой базе: упаковка без потерь.

Нужна пустая локальная база со схемой (infra/postgres/init):

    MRANKED_TEST_PACKED_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked

Без неё тест пропускается.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

ADMIN = os.environ.get("MRANKED_TEST_PACKED_ADMIN_DSN", "")
pytestmark = pytest.mark.skipif(not ADMIN, reason="disposable PostgreSQL DSN is required")

# Только в горячем слое: технические отпечатки и xid записи.
HOT_ONLY = ("source_fingerprint", "semantic_fingerprint", "ingested_xid")
RESOLVED = "SELECT * FROM ingest.publication_metric_snapshot_resolved WHERE publication_id = %s ORDER BY id"
ACTIVE = "SELECT id FROM ingest.publication_metric_snapshot_active WHERE publication_id = %s ORDER BY id"
REACTIONS = ("SELECT id, reaction_breakdown FROM ingest.publication_metric_point "
             "WHERE publication_id = %s ORDER BY id")


def connect():
    if not any(host in ADMIN for host in ("127.0.0.1", "localhost")):
        raise AssertionError("packed history tests write and delete observations: local disposable database only")
    return psycopg.connect(ADMIN, autocommit=True, row_factory=dict_row)


def insert(connection, row: dict, reactions: dict | None = None) -> int | None:
    """Через триггеры вставки, как сборщик; разбивка — в той же транзакции."""
    with connection.transaction():
        inserted = connection.execute("""
            INSERT INTO ingest.publication_metric_snapshot(
              published_month, publication_id, collection_run_id, observed_at, age_seconds, sampling_bucket,
              views_count, reactions_count, comments_count, shares_count, quality, views_quality,
              reactions_quality, comments_quality, shares_quality, interval_uncertain, synthetic,
              source_fingerprint, collected_at, metric_evidence, metric_evidence_id, semantic_fingerprint)
            VALUES (%(month)s, %(publication)s, %(run)s, %(observed)s, %(age)s, %(bucket)s, %(views)s,
                    %(reactions)s, %(comments)s, %(shares)s, %(quality)s, %(views_quality)s,
                    %(reactions_quality)s, %(comments_quality)s, %(shares_quality)s, %(uncertain)s,
                    %(synthetic)s, %(fingerprint)s, %(collected)s, %(evidence)s, %(evidence_id)s,
                    %(semantic)s)
            RETURNING id""", row).fetchone()
        if inserted is None:
            return None
        for key, count in (reactions or {}).items():
            connection.execute("""INSERT INTO ingest.reaction_breakdown(snapshot_published_month, snapshot_id,
                                  reaction_key, reaction_count) VALUES (%s, %s, %s, %s)""",
                               (row["month"], inserted["id"], key, count))
        return inserted["id"]


@pytest.fixture()
def publication():
    institution, account, publication = uuid4(), uuid4(), uuid4()
    runs = [uuid4(), uuid4()]
    published = (datetime.now(timezone.utc) - timedelta(days=3, hours=5)).replace(microsecond=123456)
    month = published.date().replace(day=1)
    with connect() as connection:
        connection.execute("INSERT INTO analytics.dataset_revision(cause, correlation_id) "
                           "VALUES ('ingestion', gen_random_uuid())")
        connection.execute("INSERT INTO catalog.institution(id, canonical_name) VALUES (%s, 'Packed fixture')",
                           (institution,))
        connection.execute("""INSERT INTO catalog.platform_account(id, institution_id, platform, canonical_external_id,
                              access_mode) VALUES (%s, %s, 'telegram', %s, 'public_web')""",
                           (account, institution, f"packed-{account}"))
        for run in runs:
            connection.execute("""INSERT INTO ingest.collection_run(id, platform, partition_key, collector_version,
                                  started_at, status, correlation_id)
                                  VALUES (%s, 'telegram', 'packed', 'test', %s, 'succeeded', gen_random_uuid())""",
                               (run, published))
        connection.execute("""INSERT INTO ingest.publication(id, primary_account_id, published_at, discovered_at,
                              publication_type, history_completeness)
                              VALUES (%s, %s, %s, %s, 'post', 'complete')""",
                           (publication, account, published, published))
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        # Словарь неизменяемый: запись добавляется один раз и дальше только читается.
        connection.execute("""
            INSERT INTO ingest.metric_evidence_dictionary(payload, payload_sha256)
            VALUES ('{"views": {"quality": "exact"}}', sha256(convert_to('{"views": {"quality": "exact"}}', 'UTF8')))
            ON CONFLICT (payload_sha256) DO NOTHING""")
        evidence_id = connection.execute("""
            SELECT id FROM ingest.metric_evidence_dictionary
             WHERE payload_sha256 = sha256(convert_to('{"views": {"quality": "exact"}}', 'UTF8'))""").fetchone()["id"]

        def row(point: int, **values) -> dict:
            observed = published + timedelta(minutes=37 * point, microseconds=point * 911)
            base = {
                "month": month, "publication": publication, "run": runs[point % 2], "observed": observed,
                "age": int((observed - published).total_seconds()) + point % 2,
                "bucket": int(observed.timestamp()) // 300 - point % 3,
                "views": 100 * point, "reactions": 3 * point, "comments": None if point % 4 else point,
                "shares": point // 5, "quality": "exact", "views_quality": "exact",
                "reactions_quality": "rounded" if point % 7 == 0 else "exact", "comments_quality": "unknown",
                "shares_quality": "estimated", "uncertain": point % 9 == 0, "synthetic": False,
                "fingerprint": uuid4().hex, "collected": observed + timedelta(seconds=point % 13, microseconds=17),
                "evidence": None if point % 3 == 0 else Jsonb({"views": {"source_field": "views", "n": point % 2}}),
                "evidence_id": evidence_id if point % 3 == 0 else None,
                "semantic": bytes(32),
            }
            base.update(values)
            return base

        ids = []
        for point in range(1, 120):
            reactions = {"👍": point, "❤️": point // 2} if point % 10 == 0 else None
            ids.append(insert(connection, row(point), reactions))
        # Исправление того же бакета: новые счётчики, новый отпечаток.
        corrected = row(30, views=99999, fingerprint=uuid4().hex)
        ids.append(insert(connection, corrected, {"🔥": 1}))
        # Синтетическая точка в момент публикации.
        insert(connection, row(0, observed=published, age=0, bucket=-1, synthetic=True,
                               collected=published + timedelta(seconds=1)))
    return publication, month, row


def snapshot_state(connection, publication):
    resolved = [{key: value for key, value in item.items() if key not in HOT_ONLY}
                for item in connection.execute(RESOLVED, (publication,)).fetchall()]
    active = [item["id"] for item in connection.execute(ACTIVE, (publication,)).fetchall()]
    reactions = connection.execute(REACTIONS, (publication,)).fetchall()
    return resolved, active, reactions


def test_compaction_keeps_every_point_version_and_breakdown(publication):
    publication_id, month, row = publication
    boundary = datetime.now(timezone.utc) - timedelta(days=1)
    with connect() as connection:
        before = snapshot_state(connection, publication_id)
        hot_before = connection.execute("SELECT count(*) AS n FROM ingest.publication_metric_snapshot "
                                        "WHERE publication_id = %s", (publication_id,)).fetchone()["n"]
        moved = connection.execute("SELECT ingest.compact_publication_history(%s, %s) AS n",
                                   (publication_id, boundary)).fetchone()["n"]
        after = snapshot_state(connection, publication_id)
        hot_after = connection.execute("SELECT count(*) AS n FROM ingest.publication_metric_snapshot "
                                       "WHERE publication_id = %s", (publication_id,)).fetchone()["n"]
        packed = connection.execute("SELECT point_count FROM ingest.publication_metric_history "
                                    "WHERE publication_id = %s", (publication_id,)).fetchone()

    assert moved > 0 and packed["point_count"] == moved and hot_after == hot_before - moved
    assert after == before


def test_second_pass_merges_new_rows_without_loss(publication):
    publication_id, month, row = publication
    now = datetime.now(timezone.utc)
    with connect() as connection:
        connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                           (publication_id, now - timedelta(days=2)))
        before = snapshot_state(connection, publication_id)
        connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                           (publication_id, now - timedelta(hours=12)))
        after = snapshot_state(connection, publication_id)
    assert after == before


def test_late_replay_is_dropped_and_late_correction_supersedes_packed_point(publication):
    publication_id, month, row = publication
    with connect() as connection:
        connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                           (publication_id, datetime.now(timezone.utc) - timedelta(hours=6)))
        before = snapshot_state(connection, publication_id)
        # Повтор доставки после долгого простоя: тот же замер, отпечатка в упаковке нет.
        assert insert(connection, row(20)) is None
        assert snapshot_state(connection, publication_id) == before

        late = insert(connection, row(20, views=777, fingerprint=uuid4().hex))
        assert late is not None
        state = connection.execute("""SELECT id, correction_sequence, supersedes_snapshot_id, visible, packed
                                        FROM ingest.publication_metric_point
                                       WHERE publication_id = %s AND sampling_bucket = %s
                                       ORDER BY correction_sequence""",
                                   (publication_id, row(20)["bucket"])).fetchall()
        assert [(item["packed"], item["visible"]) for item in state] == [(True, False), (False, True)]
        assert state[1]["correction_sequence"] == state[0]["correction_sequence"] + 1
        assert state[1]["supersedes_snapshot_id"] == state[0]["id"]

        merged_before = snapshot_state(connection, publication_id)
        connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                           (publication_id, datetime.now(timezone.utc) - timedelta(hours=6)))
        assert snapshot_state(connection, publication_id) == merged_before
        assert connection.execute("SELECT late_rows FROM ingest.publication_metric_history "
                                  "WHERE publication_id = %s", (publication_id,)).fetchone()["late_rows"] is False


def test_only_the_compactor_may_delete_observations(publication):
    # Флаг сеанса ставит кто угодно: роль с правом DELETE, но не владелец
    # таблицы, всё равно получает отказ триггера неизменяемости.
    publication_id, month, row = publication
    role = f"packed_deleter_{uuid4().hex[:8]}"
    with connect() as connection:
        connection.execute(f"CREATE ROLE {role}")
        connection.execute(f"GRANT USAGE ON SCHEMA ingest TO {role}")
        connection.execute(f"GRANT SELECT, DELETE ON ingest.publication_metric_snapshot TO {role}")
        try:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                with connection.transaction():
                    connection.execute(f"SET LOCAL ROLE {role}")
                    connection.execute("SET LOCAL ingest.compaction = 'on'")
                    connection.execute("DELETE FROM ingest.publication_metric_snapshot WHERE publication_id = %s",
                                       (publication_id,))
        finally:
            connection.execute(f"DROP OWNED BY {role}")
            connection.execute(f"DROP ROLE {role}")


WINDOW_VIEW = """SELECT * FROM ingest.publication_metric_point
                  WHERE publication_id = %s AND observed_at >= %s AND observed_at < %s ORDER BY id"""
WINDOW_FUNCTION = """SELECT * FROM ingest.publication_points_between(ARRAY[%s]::uuid[], %s, %s) ORDER BY id"""
AT_VIEW = """SELECT * FROM ingest.publication_metric_point WHERE publication_id = %s AND observed_at <= %s AND visible
              ORDER BY observed_at DESC, id DESC LIMIT 1"""
AT_FUNCTION = "SELECT * FROM ingest.publication_point_at(ARRAY[%s]::uuid[], %s)"


def window_answers(connection, publication_id, published):
    answers = []
    for start, end in ((0, 6), (5, 30), (40, 80), (0, 100)):
        bounds = (published + timedelta(hours=start), published + timedelta(hours=end))
        answers.append((connection.execute(WINDOW_VIEW, (publication_id, *bounds)).fetchall(),
                        connection.execute(WINDOW_FUNCTION, (publication_id, *bounds)).fetchall()))
    for hours in (0, 3, 12.4, 30, 70, 200):
        at = published + timedelta(hours=hours)
        answers.append((connection.execute(AT_VIEW, (publication_id, at)).fetchall(),
                        connection.execute(AT_FUNCTION, (publication_id, at)).fetchall()))
    return answers


def test_window_functions_match_the_view_in_both_layers(publication):
    publication_id, month, row = publication
    with connect() as connection:
        published = connection.execute("SELECT published_at FROM ingest.publication WHERE id = %s",
                                       (publication_id,)).fetchone()["published_at"]
        before = window_answers(connection, publication_id, published)
        connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                           (publication_id, datetime.now(timezone.utc) - timedelta(hours=30)))
        after = window_answers(connection, publication_id, published)
        insert(connection, row(20, views=777, fingerprint=uuid4().hex))  # поздняя версия: late_rows
        late = window_answers(connection, publication_id, published)
    for view, function in before + after + late:
        assert function == view
    def logical(rows):
        return [{key: value for key, value in item.items() if key not in (*HOT_ONLY, "packed")} for item in rows]
    assert [logical(view) for view, _ in before] == [logical(view) for view, _ in after]
