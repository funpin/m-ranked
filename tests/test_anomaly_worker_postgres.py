"""Работник v2 на одноразовой базе стенда; без стенда пропускается."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from anomaly_analysis.v2.schedule import ScheduleConfig
from anomaly_analysis.v2.series import CollectionCadence
from anomaly_analysis.v2.store import PostgresAnomalyStore
from anomaly_analysis.v2.worker import Worker

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402 — только после importorskip

INSTITUTION, ACCOUNT, RUN = uuid4(), uuid4(), uuid4()


@pytest.fixture(scope="module")
def databases():
    values = {"admin": os.environ.get("MRANKED_ANOMALY_TEST_ADMIN_DSN", ""),
              "worker": os.environ.get("MRANKED_ANOMALY_TEST_WORKER_DSN", "")}
    if not all(values.values()):
        pytest.skip("disposable anomaly PostgreSQL role DSNs are required")
    if "anomaly_it" not in values["admin"] or not any(host in values["admin"] for host in ("127.0.0.1", "localhost")):
        raise AssertionError("anomaly integration test requires the dedicated disposable local anomaly_it database")
    with psycopg.connect(values["admin"], autocommit=True) as connection:
        # Состояния прежних прогонов не должны попадать в очередь этого модуля.
        connection.execute("UPDATE analytics.post_anomaly_state SET frozen = true")
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Worker v2 fixture')",
                           (INSTITUTION,))
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
            VALUES (%s,%s,'telegram',%s,'public_web')""", (ACCOUNT, INSTITUTION, f"worker-v2-{ACCOUNT}"))
        connection.execute("""
            INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
            VALUES (%s,'telegram','worker-v2','integration',now()-interval '2 days','succeeded',gen_random_uuid())""",
                           (RUN,))
    yield values


def _post(admin_dsn, published_at: datetime, views_per_step, points: int):
    publication = uuid4()
    month = published_at.astimezone(timezone.utc).date().replace(day=1)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        connection.execute("""
            INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
            VALUES (%s,%s,%s,%s,'post','complete')""", (publication, ACCOUNT, published_at, published_at))
        views = 0
        for index in range(points):
            views += views_per_step(index)
            observed = published_at + timedelta(minutes=15 * (index + 1))
            connection.execute("""
                INSERT INTO ingest.publication_metric_snapshot(
                  published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                  views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,NULL,'exact',%s,%s)""",
                (month, publication, RUN, observed, 900 * (index + 1), index, views, views // 50,
                 uuid4().hex, observed))
    return publication


def _worker(databases, now):
    return Worker(PostgresAnomalyStore(databases["worker"]), ScheduleConfig(), CollectionCadence(),
                  clock=lambda: now)


def test_batch_is_analyzed_logged_on_change_and_caught_up_once(databases):
    published = datetime.now(timezone.utc) - timedelta(hours=40)
    organic = _post(databases["admin"], published, lambda index: max(1, int(400 / (1 + index) ** 1.3)), 150)
    # После затухания ровная подача: сутки по +300 за 15 минут.
    linear = _post(databases["admin"], published, lambda index: 300 if index >= 60 else
                   max(1, int(400 / (1 + index) ** 1.3)), 150)
    now = datetime.now(timezone.utc)
    worker = _worker(databases, now)
    assert worker.run_once() >= 2
    with psycopg.connect(databases["admin"], row_factory=dict_row) as connection:
        states = {row["publication_id"]: row for row in connection.execute(
            "SELECT publication_id, level, next_due_at, analyzed_at FROM analytics.post_anomaly_state "
            "WHERE publication_id = ANY(%s)", ([organic, linear],)).fetchall()}
        logs = connection.execute("SELECT publication_id, change FROM analytics.post_anomaly_log "
                                  "WHERE publication_id = ANY(%s)", ([organic, linear],)).fetchall()
    assert states[linear]["level"] >= 2 and states[organic]["level"] <= 1
    assert [row["change"] for row in logs if row["publication_id"] == linear] == ["appeared"]
    # «Простой»: срок прошёл двое суток назад, с прошлого анализа пришли новые
    # замеры. Два прогона подряд — ровно один анализ «на сейчас», без повторов.
    with psycopg.connect(databases["admin"], autocommit=True) as connection:
        connection.execute("""
            UPDATE analytics.post_anomaly_state
               SET next_due_at = %s - interval '2 days',
                   last_point_observed_at = last_point_observed_at - interval '3 hours'
             WHERE publication_id = %s""", (now, linear))
    later = now + timedelta(minutes=1)
    repeat = _worker(databases, later)
    repeat.run_once()
    repeat.run_once()
    with psycopg.connect(databases["admin"], row_factory=dict_row) as connection:
        count = connection.execute("SELECT count(*) AS n FROM analytics.post_anomaly_log WHERE publication_id=%s",
                                   (linear,)).fetchone()["n"]
        state = connection.execute(
            "SELECT analyzed_at, next_due_at FROM analytics.post_anomaly_state WHERE publication_id=%s",
            (linear,)).fetchone()
    assert state["analyzed_at"] == later and state["next_due_at"] > later
    # Вывод не изменился — журнал не пополнился.
    assert count == 1
