"""Конвейер холодного архива целиком на одноразовой базе (ADR-016).

Нужна пустая локальная база со схемой (infra/postgres/init) и pyarrow:

    MRANKED_TEST_ARCHIVE_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked
    MRANKED_TEST_ARCHIVE_MAINTENANCE_DSN=postgresql://maintenance:…@127.0.0.1:…/mranked

Без них тест пропускается. Копию на другом сервере подтверждает тот же код,
что на проде (сверщик main_agent.apply_plan и учёт приёмника NodeHub), — без
сети: «агент» второго сервера здесь только кладёт файл и сообщает SHA-256.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
from uuid import UUID, uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pyarrow")
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from anomaly_analysis.v2 import archive_job  # noqa: E402
from anomaly_analysis.v2.schedule import ScheduleConfig  # noqa: E402
from anomaly_analysis.v2.series import CollectionCadence  # noqa: E402
from anomaly_analysis.v2.store import PostgresAnomalyStore, SeriesTarget  # noqa: E402
from anomaly_analysis.v2.worker import Worker  # noqa: E402
from anomaly_analysis.v2.domain import Metric  # noqa: E402
from api.cold_archive import ColdArchiveReader  # noqa: E402
from operations.cold_archive.pipeline import Pipeline, Settings  # noqa: E402
from operations.storage import main_agent, store  # noqa: E402
from operations.storage.hub import NodeHub  # noqa: E402

ADMIN = os.environ.get("MRANKED_TEST_ARCHIVE_ADMIN_DSN", "")
MAINTENANCE = os.environ.get("MRANKED_TEST_ARCHIVE_MAINTENANCE_DSN", "")
WORKER = os.environ.get("MRANKED_TEST_ARCHIVE_WORKER_DSN", "")
INSTITUTION, ACCOUNT, RUN = uuid4(), uuid4(), uuid4()
EMBEDDED_EVIDENCE = {"reaction_breakdown": {"❤️": 4, "🔥": 6}, "views": "exact"}
TABLE_BREAKDOWN = {"👍": 11, "custom:5472256095697246943": 1}

pytestmark = pytest.mark.skipif(not (ADMIN and MAINTENANCE), reason="disposable archive PostgreSQL DSNs are required")


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


@pytest.fixture(scope="module")
def posts():
    if not any(host in ADMIN for host in ("127.0.0.1", "localhost")):
        raise AssertionError("the archive pipeline test drops partitions: local disposable database only")
    with connect(ADMIN) as connection:
        connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES ('ingestion',gen_random_uuid())")
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Archive fixture')", (INSTITUTION,))
        connection.execute("""INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                              VALUES (%s,%s,'max',%s,'public_web')""", (ACCOUNT, INSTITUTION, f"archive-{ACCOUNT}"))
        connection.execute("""INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
                              VALUES (%s,'max','archive','integration','2026-07-01','succeeded',gen_random_uuid())""", (RUN,))
        # Повторный прогон на той же базе берёт следующий нетронутый месяц.
        used = {row["month"] for row in connection.execute(
            "SELECT DISTINCT date_trunc('month', published_at AT TIME ZONE 'UTC')::date AS month FROM ingest.publication")}
        month = next(candidate for candidate in (date(year, number, 1) for year in (2026, 2025, 2024)
                                                 for number in range(12, 0, -1))
                     if candidate <= date(2026, 7, 1) and candidate not in used)
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        created = []
        for index in range(3):
            publication = uuid4()
            published = datetime(month.year, month.month, 10 + index, 9, tzinfo=timezone.utc)
            connection.execute("""INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                                  VALUES (%s,%s,%s,%s,'post','complete')""", (publication, ACCOUNT, published, published))
            for point in range(40):
                observed = published + timedelta(minutes=15 * (point + 1))
                # Сентябрьский сборщик r4 клал разбивку реакций внутрь
                # metric_evidence, без строк в reaction_breakdown.
                evidence = EMBEDDED_EVIDENCE if index == 0 and point < 5 else {}
                breakdown = TABLE_BREAKDOWN if index == 1 and point == 5 else {}
                # Строки разбивки вставляются в одной транзакции со своим замером.
                with connection.transaction():
                    snapshot = connection.execute("""
                        INSERT INTO ingest.publication_metric_snapshot(
                          published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                          views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at,
                          metric_evidence)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,NULL,'exact',%s,%s,%s) RETURNING id""",
                        (month, publication, RUN, observed, 900 * (point + 1), point, 100 * (point + 1), 3 * point,
                         uuid4().hex, observed, Jsonb(evidence))).fetchone()["id"]
                    for key, count in breakdown.items():
                        connection.execute("""INSERT INTO ingest.reaction_breakdown(
                                                snapshot_published_month,snapshot_id,reaction_key,reaction_count)
                                              VALUES (%s,%s,%s,%s)""", (month, snapshot, key, count))
            created.append((publication, published))
    return month, created


def copy_to_second_server(root: Path, remote: Path):
    """Сон конвейера: сверщик заказывает копию, «агент» Сервера 1 её сверяет."""
    hub = NodeHub(lambda: connect(MAINTENANCE), root)

    def sleep(_seconds: float) -> None:
        with connect(MAINTENANCE) as connection:
            main_agent.apply_plan(connection, "server-2", root, store.host_metrics(root))
            tasks = hub._tasks(connection, "server-1")
        results = []
        for task in tasks:
            if task["type"] != "fetch":
                continue
            target = store.object_path(remote, task["kind"], task["name"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.object_path(root, task["kind"], task["name"]), target)
            results.append({"objectId": task["objectId"], "state": "verified", "sha256": store.sha256_file(target),
                            "bytes": target.stat().st_size})
        hub.report(("server-1/max",), json.dumps({"agentVersion": "test", "results": results}).encode())

    return sleep


def history_before(publication: UUID) -> list[dict]:
    with connect(ADMIN) as connection:
        return connection.execute("""SELECT observed_at, views_count FROM ingest.publication_metric_snapshot
                                     WHERE publication_id = %s ORDER BY observed_at DESC""", (publication,)).fetchall()


def test_month_goes_cold_reads_back_and_late_rows_form_the_next_generation(posts, tmp_path):
    root, remote = tmp_path / "main", tmp_path / "server-1"
    settings = Settings(root=root, cold_after_days=30, fence_deadline=timedelta(minutes=5), pace=0.0)
    MONTH, created = posts
    first, published = created[0]
    before = history_before(first)

    result = Pipeline(MAINTENANCE, settings, sleep=copy_to_second_server(root, remote)).run(MONTH)
    assert result["status"] == "cold" and result["publications"] == 3 and result["rows"] == 120
    assert result["copy"] == "server-1"
    # Разбивка из metric_evidence и из таблицы доезжает до файла, а сама
    # metric_evidence — без неё, как в канонической записи.
    full = pq.read_table(store.object_path(root, "archive_full", f"snapshots-{MONTH:%Y-%m}-g1.parquet")).to_pylist()
    breakdowns = [json.loads(row["reaction_breakdown_json"]) for row in full]
    assert breakdowns.count(EMBEDDED_EVIDENCE["reaction_breakdown"]) == 5 and breakdowns.count(TABLE_BREAKDOWN) == 1
    assert {"views": "exact"} in [json.loads(row["metric_evidence_json"]) for row in full]

    with connect(ADMIN) as connection:
        assert connection.execute("SELECT count(*) AS n FROM ingest.publication_metric_snapshot "
                                  "WHERE published_month = %s", (MONTH,)).fetchone()["n"] == 0
        fence = connection.execute("SELECT state FROM ops_and_admin.publication_partition_fence "
                                   "WHERE published_month = %s", (MONTH,)).fetchone()["state"]
        generation = connection.execute("SELECT state, row_count FROM ops_and_admin.cold_archive_generation "
                                        "WHERE published_month = %s", (MONTH,)).fetchone()
        replicas = connection.execute("""SELECT object.kind, replica.node_id, replica.state
                                         FROM ops_and_admin.storage_replica replica
                                         JOIN ops_and_admin.storage_object object ON object.id = replica.object_id""").fetchall()
    # Месяц снова открыт для записи; поколение в архиве; полный файл на двух серверах.
    assert fence == "active" and generation == {"state": "cold", "row_count": 120}
    assert {("archive_full", "server-1", "verified"), ("archive_full", "server-2", "verified"),
            ("archive_browse", "server-2", "verified")} <= {tuple(row.values()) for row in replicas}

    class Db:
        async def fetch_all(self, sql, params):
            with connect(MAINTENANCE) as connection:
                return connection.execute(sql, params).fetchall()

    archived = asyncio.run(ColdArchiveReader(root).history(Db(), MONTH, str(first)))
    assert [datetime.fromisoformat(item["observedAt"]) for item in archived.items] == [
        row["observed_at"] for row in before]
    assert [item["views"]["value"] for item in archived.items] == [row["views_count"] for row in before]
    assert archived.items[0]["deltaViews"] == 100

    # Поздний контрольный замер после архивации ложится в новую партицию.
    late = published + timedelta(days=40)
    with connect(ADMIN) as connection:
        connection.execute("""
            INSERT INTO ingest.publication_metric_snapshot(
              published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
              views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at)
            VALUES (%s,%s,%s,%s,%s,999,9000,200,0,NULL,'exact',%s,%s)""",
            (MONTH, first, RUN, late, int((late - published).total_seconds()), uuid4().hex, late))
    second = Pipeline(MAINTENANCE, settings, sleep=copy_to_second_server(root, remote)).run(MONTH)
    assert second["status"] == "cold" and second["generation"] == 2 and second["rows"] == 1

    reader = ColdArchiveReader(root)
    merged = asyncio.run(reader.history(Db(), MONTH, str(first)))
    assert merged.generations == 2 and len(merged.items) == 41
    # Прирост на стыке поколений досчитан при слиянии.
    assert merged.items[0]["views"]["value"] == 9000 and merged.items[0]["deltaViews"] == 9000 - 4000

    # Работник анализа видит полный ряд архивного месяца.
    analysis = PostgresAnomalyStore(MAINTENANCE)
    analysis._archive.root = root
    series = analysis.read_series([SeriesTarget(first, published)])[first]
    assert len(series.observed_at) == 41 and series.values[Metric.VIEWS][-1] == 9000

    if not WORKER:
        return
    # Анализ заново по архиву: задание снимает заморозку, настоящий работник
    # (роль analytics_worker) анализирует посты по файлам архива и замораживает.
    with connect(ADMIN) as connection:
        connection.execute("UPDATE analytics.post_anomaly_state SET frozen = true")
        connection.execute("INSERT INTO ops_and_admin.admin_job (kind, params, requested_by) VALUES "
                           "('archive_analysis', %s::jsonb, 'test')", (json.dumps({"month": MONTH.isoformat()[:7]}),))
    worker_store = PostgresAnomalyStore(WORKER)
    worker_store._archive.root = root
    worker = Worker(worker_store, ScheduleConfig(), CollectionCadence())
    with connect(WORKER) as connection:
        while (outcome := archive_job.run(connection, sleep=lambda _: worker.run_once())) is not None:
            if outcome["queued"] == 3:
                break
    assert outcome == {"id": outcome["id"], "state": "done", "queued": 3, "seeded": 3}
    with connect(ADMIN) as connection:
        states = connection.execute("""SELECT frozen, analyzed_points, error_code FROM analytics.post_anomaly_state
                                       WHERE publication_id = ANY(%s)""", ([item[0] for item in created],)).fetchall()
    assert all(row["frozen"] and row["error_code"] is None for row in states)
    assert sorted(row["analyzed_points"] for row in states) == [40, 40, 41]


def test_main_agent_registers_dumps_places_copies_and_starts_panel_jobs(tmp_path):
    root, dumps = tmp_path / "store", tmp_path / "dumps"
    store.ensure_layout(root)
    dumps.mkdir()
    name = f"mranked-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}Z.dump"
    (dumps / name).write_bytes(b"pg_dump custom format" * 1000)
    with connect(MAINTENANCE) as connection:
        metrics = main_agent.record_heartbeat(connection, "server-2", root, [])
        assert main_agent.register_backups(connection, "server-2", root, dumps, tmp_path / "sha.json", None) == 1
        assert main_agent.register_backups(connection, "server-2", root, dumps, tmp_path / "sha.json", None) == 0
        # Без второй копии — жёсткая ссылка на тот же файл.
        assert (root / "backups" / name).stat().st_ino == (dumps / name).stat().st_ino
        plan = main_agent.apply_plan(connection, "server-2", root, metrics)
        object_id = connection.execute("SELECT id::text FROM ops_and_admin.storage_object WHERE name = %s",
                                       (name,)).fetchone()["id"]
        assert (object_id, "server-1") in plan.want
        replica = connection.execute("SELECT state FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                     "AND node_id = 'server-1'", (object_id,)).fetchone()
        assert replica["state"] == "wanted"
        # Копия основного сервера пропала с диска — она снова нужна.
        (root / "backups" / name).unlink()
        assert main_agent.check_local_copies(connection, "server-2", root) >= 1
        lost = connection.execute("SELECT state, error FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                  "AND node_id = 'server-2'", (object_id,)).fetchone()
        assert lost == {"state": "wanted", "error": "lost_local_copy"}
        connection.execute("UPDATE ops_and_admin.storage_replica SET state = 'failed', attempts = 1, "
                           "updated_at = now() - interval '1 hour' WHERE node_id = 'server-1'")
        main_agent.retry_failed(connection)
        assert connection.execute("SELECT state FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                  "AND node_id = 'server-1'", (object_id,)).fetchone()["state"] == "wanted"
    with connect(ADMIN) as connection:
        connection.execute("UPDATE ops_and_admin.admin_job SET state = 'cancelled' WHERE state = 'queued'")
        connection.execute("INSERT INTO ops_and_admin.admin_job (kind, requested_by) VALUES ('archive_now', 'test')")
    started = []
    with connect(MAINTENANCE) as connection:
        assert main_agent.start_jobs(connection, started.append) == ["m-ranked-target-cold-archive.service"]
    assert started == ["m-ranked-target-cold-archive.service"]
