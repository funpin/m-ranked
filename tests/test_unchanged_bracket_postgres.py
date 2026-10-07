"""Скобка роста: последнее чтение без изменений сохраняется, когда пришло изменение.

Чтения без изменений не пишутся (кроме контрольного раз в сутки). Без скобки
рост, случившийся за последний час сбора, на графике растягивался на все
часы с прошлой сохранённой точки: RuTube читается раз в час, и между
точками выходило 18 часов вместо одного.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform, RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository


def _dsn(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _persist(repository, account, published, observed, metrics):
    context = CollectionContext.create(Platform.RUTUBE, f"bracket-{uuid4()}", "bracket-test-v1", observed, observed)
    raw = RawCollectionBatch(account, None, (RawPublication(
        "video-1", published, published, observed, observed, "video", metrics, {"kind": "public"},
        history_completeness=HistoryCompleteness.COMPLETE, sampling_interval_seconds=3600,
    ),), "bracket-integration", "1")
    repository.start_run(context)
    assert repository.begin_account(context, account, observed)
    repository.persist_account_batch(CanonicalNormalizer().normalize(raw, context))


def test_growth_after_unchanged_reads_keeps_the_last_unchanged_read() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    repository = PostgresCollectorRepository(_dsn("MRANKED_TEST_POSTGRES_DSN"))
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"), autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    account = AccountRef(account_id, institution_id, Platform.RUTUBE, f"bracket_{account_id.hex}", "public_web")
    admin.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
                  (institution_id, f"bracket {institution_id}"))
    admin.execute("""INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                     VALUES (%s,%s,'rutube',%s,'public_web')""", (account_id, institution_id, account.canonical_external_id))
    published = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=20)
    base = {"views": 100, "reactions": 3, "comments": 0, "shares": None}
    _persist(repository, account, published, published + timedelta(minutes=15), base)
    # Восемнадцать часовых чтений без изменений: ни одно не пишется.
    for hour in range(1, 19):
        _persist(repository, account, published, published + timedelta(minutes=15, hours=hour), base)
    grown = {"views": 1849, "reactions": 100, "comments": 0, "shares": None}
    _persist(repository, account, published, published + timedelta(minutes=15, hours=19), grown)

    rows = admin.execute(
        """SELECT snapshot.observed_at, snapshot.views_count, snapshot.reactions_count
             FROM ingest.publication_metric_snapshot snapshot
             JOIN ingest.publication_identity identity ON identity.publication_id = snapshot.publication_id
            WHERE identity.platform_account_id = %s AND NOT snapshot.synthetic
            ORDER BY snapshot.observed_at""", (account_id,)).fetchall()
    ages = [round((row["observed_at"] - published).total_seconds() / 3600, 2) for row in rows]
    # Первое чтение, последнее чтение без изменений (скобка) и рост.
    assert ages == [0.25, 18.25, 19.25]
    assert [row["views_count"] for row in rows] == [100, 100, 1849]


def test_heartbeat_or_growth_without_unchanged_reads_adds_nothing() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    repository = PostgresCollectorRepository(_dsn("MRANKED_TEST_POSTGRES_DSN"))
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"), autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    account = AccountRef(account_id, institution_id, Platform.RUTUBE, f"bracket_{account_id.hex}", "public_web")
    admin.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
                  (institution_id, f"bracket {institution_id}"))
    admin.execute("""INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                     VALUES (%s,%s,'rutube',%s,'public_web')""", (account_id, institution_id, account.canonical_external_id))
    published = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=5)
    for hour, views in ((0, 10), (1, 20), (2, 30)):
        _persist(repository, account, published, published + timedelta(minutes=10, hours=hour),
                 {"views": views, "reactions": 1, "comments": 0, "shares": None})
    count = admin.execute(
        """SELECT count(*) AS n FROM ingest.publication_metric_snapshot snapshot
             JOIN ingest.publication_identity identity ON identity.publication_id = snapshot.publication_id
            WHERE identity.platform_account_id = %s AND NOT snapshot.synthetic""", (account_id,)).fetchone()["n"]
    assert count == 3


def test_history_places_growth_after_the_last_cycle_for_data_without_a_bracket() -> None:
    # Данные до скобки: каждое чтение — новым процессом, память о чтениях без
    # изменений теряется. История поста по журналу циклов называет последнее
    # чтение без изменений — график ставит туда точку.
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row
    from api.sql import details

    dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"), autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    account = AccountRef(account_id, institution_id, Platform.RUTUBE, f"bracket_{account_id.hex}", "public_web")
    admin.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
                  (institution_id, f"bracket {institution_id}"))
    admin.execute("""INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                     VALUES (%s,%s,'rutube',%s,'public_web')""", (account_id, institution_id, account.canonical_external_id))
    published = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=20)
    base = {"views": 1, "reactions": 0, "comments": 0, "shares": None}
    for hour in range(0, 18):
        _persist(PostgresCollectorRepository(dsn), account, published, published + timedelta(minutes=15, hours=hour), base)
    _persist(PostgresCollectorRepository(dsn), account, published, published + timedelta(minutes=15, hours=18),
             {"views": 1749, "reactions": 97, "comments": 0, "shares": None})

    publication_id = admin.execute(
        "SELECT publication_id FROM ingest.publication_identity WHERE platform_account_id=%s", (account_id,)
    ).fetchone()["publication_id"]
    rows = admin.execute(details.HISTORY, {
        "publication_id": publication_id, "published_month": published.date().replace(day=1),
        "as_of": datetime.now(timezone.utc), "after_snapshot_id": None, "fetch_limit": 100}).fetchall()
    growth = next(row for row in rows if row["views_count"] == 1749)
    interval = growth["collector_interval"]
    # Семнадцать циклов без изменений и цикл самого роста.
    assert interval["successfulPolls"] == 18
    assert datetime.fromisoformat(interval["unchangedAt"]) == published + timedelta(minutes=15, hours=17)
