"""Ночной пересчёт норм на одноразовой базе стенда; без стенда пропускается."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from anomaly_analysis.norms_job import NormJob
from anomaly_analysis.v2.norms import NormStatus
from anomaly_analysis.v2.series import CollectionCadence
from anomaly_analysis.v2.store import PostgresAnomalyStore

psycopg = pytest.importorskip("psycopg")


@pytest.fixture(scope="module")
def databases():
    values = {"admin": os.environ.get("MRANKED_ANOMALY_TEST_ADMIN_DSN", ""),
              "worker": os.environ.get("MRANKED_ANOMALY_TEST_WORKER_DSN", "")}
    if not all(values.values()):
        pytest.skip("disposable anomaly PostgreSQL role DSNs are required")
    if "anomaly_it" not in values["admin"] or not any(host in values["admin"] for host in ("127.0.0.1", "localhost")):
        raise AssertionError("anomaly integration test requires the dedicated disposable local anomaly_it database")
    yield values


def _organic_account(admin_dsn, posts: int):
    institution, account, run = uuid4(), uuid4(), uuid4()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Norms fixture')",
                           (institution,))
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
            VALUES (%s,%s,'max',%s,'public_web')""", (account, institution, f"norms-{account}"))
        connection.execute("""
            INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
            VALUES (%s,'max','norms','integration',now()-interval '20 days','succeeded',gen_random_uuid())""", (run,))
        for index in range(posts):
            publication = uuid4()
            published = datetime.now(timezone.utc) - timedelta(days=3 + index)
            month = published.date().replace(day=1)
            connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
            connection.execute("""
                INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                VALUES (%s,%s,%s,%s,'post','complete')""", (publication, account, published, published))
            for step in range(120):
                age = timedelta(minutes=15 * (step + 1))
                views = int(2000 * (1 - (1 + age.total_seconds() / 4000) ** -0.4))
                connection.execute("""
                    INSERT INTO ingest.publication_metric_snapshot(
                      published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                      views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,NULL,'exact',%s,%s)""",
                    (month, publication, run, published + age, int(age.total_seconds()), step, views,
                     views // 60, uuid4().hex, published + age))
    return account


def test_job_writes_a_version_that_the_worker_can_read(databases):
    account = _organic_account(databases["admin"], 22)
    store = PostgresAnomalyStore(databases["worker"])
    version, status = NormJob(store, CollectionCadence(), []).run()
    assert status in {NormStatus.ACCEPTED, NormStatus.DRIFT_REVIEW}
    norms = store.read_norms(version, "max")
    assert norms is not None and norms.for_account(account).posts == 22
    if status is NormStatus.ACCEPTED:
        assert store.latest_accepted_norm_version() == version
