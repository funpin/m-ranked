"""Хранилище v2 на живой одноразовой базе стенда; без стенда пропускается.

Схема стенда применяется целиком, 0001–0036 подряд, поэтому сама применимость
0036 поверх предыдущих проверяется наличием её объектов.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from anomaly_analysis.v2.domain import (
    DataQuality, Family, Interval, Level, Metric, PostVerdict, Sign,
)
from anomaly_analysis.v2.store import DueRow, PostgresAnomalyStore, SeriesTarget, StateWrite

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402 — только после importorskip

NEW_TABLES = ("anomaly_norm_version", "anomaly_norm", "post_anomaly_state", "post_anomaly_log")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
INSTITUTION, ACCOUNT, RUN = uuid4(), uuid4(), uuid4()


@pytest.fixture(scope="module")
def databases():
    names = {"admin": "MRANKED_ANOMALY_TEST_ADMIN_DSN", "worker": "MRANKED_ANOMALY_TEST_WORKER_DSN",
             "api": "MRANKED_ANOMALY_TEST_API_DSN"}
    values = {name: os.environ.get(key, "") for name, key in names.items()}
    if not all(values.values()):
        pytest.skip("disposable anomaly PostgreSQL role DSNs are required")
    if "anomaly_it" not in values["admin"] or not any(host in values["admin"] for host in ("127.0.0.1", "localhost")):
        raise AssertionError("anomaly integration test requires the dedicated disposable local anomaly_it database")
    with _admin(values["admin"]) as connection:
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Anomaly v2 fixture')",
                           (INSTITUTION,))
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
            VALUES (%s,%s,'vk',%s,'public_web')""", (ACCOUNT, INSTITUTION, f"anomaly-v2-{ACCOUNT}"))
        connection.execute("""
            INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
            VALUES (%s,'vk','anomaly-v2','integration',now()-interval '1 day','succeeded',gen_random_uuid())""", (RUN,))
    yield values


def _admin(dsn):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def _publication(admin_dsn, published_at: datetime, points: int):
    publication = uuid4()
    with _admin(admin_dsn) as connection:
        month = published_at.astimezone(timezone.utc).date().replace(day=1)
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        connection.execute("""
            INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
            VALUES (%s,%s,%s,%s,'post','complete')""", (publication, ACCOUNT, published_at, published_at))
        for index in range(points):
            observed = published_at + timedelta(minutes=5 * (index + 1))
            connection.execute("""
                INSERT INTO ingest.publication_metric_snapshot(
                  published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                  views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'exact',%s,%s)""",
                (month, publication, RUN, observed, 300 * (index + 1), index, 100 * (index + 1), 3 * index,
                 index // 4, index // 8, uuid4().hex, observed))
    return SeriesTarget(publication, published_at)


def test_migration_objects_exist_on_top_of_the_previous_schema(databases):
    with _admin(databases["admin"]) as connection:
        present = {row["table_name"] for row in connection.execute(
            """SELECT table_name FROM information_schema.tables
                WHERE table_schema='analytics' AND table_name = ANY(%s)""", (list(NEW_TABLES),))}
        assert present == set(NEW_TABLES)
        # Контракт схемы сборщиков и API прежний: новые таблицы им не видны.
        contract = connection.execute("SELECT contract_id FROM ops_and_admin.schema_contract").fetchone()
        assert contract["contract_id"] == "live-read-2026-09-13-text-fingerprint"


def test_roles_receive_exactly_the_listed_privileges(databases):
    expected = {
        ("analytics_worker", "anomaly_norm_version"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "anomaly_norm"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "post_anomaly_state"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "post_anomaly_log"): {"INSERT"},
        ("api_read", "post_anomaly_state"): {"SELECT"},
    }
    with _admin(databases["admin"]) as connection:
        roles = [row["rolname"] for row in connection.execute(
            "SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' AND NOT rolsuper").fetchall()]
        for role in roles:
            for table in NEW_TABLES:
                granted = {privilege for privilege in PRIVILEGES if connection.execute(
                    "SELECT has_table_privilege(%s, %s, %s) AS ok",
                    (role, f"analytics.{table}", privilege)).fetchone()["ok"]}
                owner = connection.execute(
                    "SELECT tableowner FROM pg_tables WHERE schemaname='analytics' AND tablename=%s",
                    (table,)).fetchone()["tableowner"]
                if role == owner:
                    continue
                assert granted == expected.get((role, table), set()), (role, table, granted)


def test_batched_series_equal_single_reads(databases):
    base = datetime.now(timezone.utc) - timedelta(hours=6)
    targets = [_publication(databases["admin"], base + timedelta(minutes=index), 12 + index) for index in range(3)]
    store = PostgresAnomalyStore(databases["worker"])
    batched = store.read_series(targets)
    single = {}
    for target in targets:
        single.update(store.read_series([target]))
    assert batched == single and set(batched) == {item.publication_id for item in targets}
    series = batched[targets[0].publication_id]
    assert series.platform == "vk" and len(series.observed_at) == 12
    assert series.values[Metric.VIEWS][:3] == (100, 200, 300)


def test_progress_matches_the_series_it_stands_in_for(databases):
    base = datetime.now(timezone.utc) - timedelta(hours=6)
    targets = [_publication(databases["admin"], base + timedelta(minutes=index), 8 + index) for index in range(2)]
    store = PostgresAnomalyStore(databases["worker"])
    series = store.read_series(targets)
    rows = []
    for target, back in zip(targets, (1, 4)):
        points = series[target.publication_id].observed_at
        rows.append(DueRow(target.publication_id, target.published_at, base, base, points[-back], None, 0, ()))
    progress = store.read_progress(rows)
    for row in rows:
        points = series[row.publication_id].observed_at
        new = [at for at in points if at > row.last_point_observed_at]
        item = progress[row.publication_id]
        assert (item.platform, item.new_points, item.first_new_at, item.last_observed_at) == (
            series[row.publication_id].platform, len(new), new[0] if new else None, points[-1])


def test_log_is_written_only_when_the_verdict_changes(databases):
    target = _publication(databases["admin"], datetime.now(timezone.utc) - timedelta(hours=3), 6)
    store = PostgresAnomalyStore(databases["worker"])
    moment = datetime.now(timezone.utc)
    sign = Sign(1, Family.VELOCITY, Metric.VIEWS, 0.9, Interval(moment - timedelta(hours=2), moment),
                timedelta(hours=1), "CV = 0.03")

    def write(level, signs):
        verdict = PostVerdict(target.publication_id, level, signs, DataQuality(1.0), {"linear_feed": "1"})
        return store.write_states([StateWrite(target.publication_id, target.published_at, moment,
                                              moment + timedelta(minutes=15), verdict=verdict)])

    assert write(Level.PRONOUNCED_ANOMALY, (sign,)) == 1
    assert write(Level.PRONOUNCED_ANOMALY, (sign,)) == 0
    assert write(Level.WEAK_SIGNAL, (sign,)) == 1
    store.write_states([StateWrite(target.publication_id, target.published_at, moment,
                                   moment + timedelta(minutes=30), error_code="series_unavailable")])
    with _admin(databases["admin"]) as connection:
        changes = [row["change"] for row in connection.execute(
            "SELECT change FROM analytics.post_anomaly_log WHERE publication_id=%s ORDER BY id",
            (target.publication_id,)).fetchall()]
        state = connection.execute(
            "SELECT level, attempts, error_code FROM analytics.post_anomaly_state WHERE publication_id=%s",
            (target.publication_id,)).fetchone()
    assert changes == ["appeared", "level_changed"]
    # Неудачный анализ не стирает прежний вывод.
    assert state == {"level": 1, "attempts": 1, "error_code": "series_unavailable"}
