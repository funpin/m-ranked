"""«Наш рейтинг» в базе: строка формулы, агрегат аккаунтов, выбор снимка месяца.

Применить 0084, 0093, 0094 и 0095 к одноразовой базе «Находок»; без неё пропускается.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from api import own_rating as own
from api.sql import own_rating as sql
from test_findings_postgres import World, _connect, dsn  # noqa: F401 — фикстура dsn
from test_rating_forecast_postgres import clean, latest, payload, record  # noqa: F401 — фикстура clean

NOV = (datetime(2026, 10, 31, 21, tzinfo=timezone.utc), datetime(2026, 11, 30, 21, tzinfo=timezone.utc))


def test_own_formula_matches_the_python_definition(dsn):
    with _connect(dsn) as connection:
        row = connection.execute("SELECT definition, status, source_hash FROM rating.formula_definition "
                                 "WHERE formula_key=%s AND version=1", (own.FORMULA_KEY,)).fetchone()
    assert row["status"] == "published" and row["definition"] == own.FORMULA_V1
    canonical = json.dumps(own.FORMULA_V1, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row["source_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def accounts(dsn, window_end=NOV[1], mature_before=NOV[1], role="api_read"):
    with _connect(dsn) as connection:
        if role:
            if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                pytest.skip(f"роль {role} не создана")
            connection.execute(f"SET ROLE {role}")
        return connection.execute(sql.OWN_ACCOUNTS, {"window_start": NOV[0], "window_end": window_end,
                                                     "mature_before": mature_before}).fetchall()


def mine(rows, world):
    return [row for row in rows if row["account_id"] == str(world.account)]


def test_accounts_count_days_packs_and_coverage_as_api_read(dsn):
    world = World(dsn, "telegram")
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-10-01' WHERE id=%s", (world.account,))
    pack = {"title": "Пакет реакций с остановкой", "metric": "reactions", "strength": 0.99,
            "render": {"kind": "regime", "episodeReactions": 118, "episodeGrowth": 120}}
    gap = {"title": "Прирост за пробел", "metric": "views", "strength": 1.0, "render": {"kind": "gap", "episodeGrowth": 5000}}
    no_size = {"title": "Реакций больше, чем просмотров", "metric": "reactions", "strength": 0.9, "render": {"kind": "exceed"}}
    day = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
    packed = world.post(day, {}, level=3, signals=[pack, gap])
    unsized = world.post(day + timedelta(hours=2), {}, level=3, signals=[no_size])   # NULL-размер — не весь пост
    other_day = world.post(day + timedelta(days=2), {}, level=2, signals=[pack])     # уровень 2 не вычитается
    world.post(datetime(2026, 10, 31, 20, 59, tzinfo=timezone.utc), {})              # 31 октября МСК
    latest(dsn, packed, 2000, 200)
    latest(dsn, unsized, 1000, 50)
    latest(dsn, other_day, 1500, 150)
    [row] = mine(accounts(dsn), world)
    assert (row["platform"], row["posts"], row["active_days"]) == ("telegram", 3, 2)
    assert row["covered_days"] == pytest.approx(30.0)
    assert (row["mature_posts"], row["mature_views"], row["mature_interactions"]) == (3, 4500, 400)
    assert (row["mature_pack_reactions"], row["mature_pack_views"]) == (120, 0)


def test_accounts_added_mid_month_are_covered_from_the_date_added(dsn):
    world = World(dsn, "max")
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-11-16T09:00:00+03:00' WHERE id=%s",
                           (world.account,))
    [row] = mine(accounts(dsn, role=None), world)
    assert row["covered_days"] == pytest.approx(14.625) and row["posts"] == 0
    # История, догруженная до начала месяца, делает месяц покрытым.
    world.post(datetime(2026, 9, 1, 9, tzinfo=timezone.utc), {})
    [row] = mine(accounts(dsn, role=None), world)
    assert row["covered_days"] == pytest.approx(30.0)


def test_rutube_counts_videos_by_upload_date(dsn):
    world = World(dsn, "rutube")
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-10-01' WHERE id=%s", (world.account,))
    october = world.post(datetime(2026, 11, 2, 9, tzinfo=timezone.utc), {})     # загружено в октябре
    december = world.post(datetime(2026, 12, 3, 9, tzinfo=timezone.utc), {})    # загружено в ноябре
    world.post(datetime(2026, 11, 10, 9, tzinfo=timezone.utc), {})              # без даты загрузки
    with _connect(dsn) as connection:
        connection.execute("UPDATE ingest.publication SET uploaded_at='2026-10-28T09:00:00Z' WHERE id=%s", (october,))
        connection.execute("UPDATE ingest.publication SET uploaded_at='2026-11-20T09:00:00Z' WHERE id=%s", (december,))
    [row] = mine(accounts(dsn, role=None), world)
    assert (row["posts"], row["active_days"]) == (2, 2)


def test_month_snapshot_prefers_real_runs_and_rows_join_names(dsn):
    world = World(dsn, "vk")
    as_of = NOV[0] + timedelta(days=5)
    body = payload(world.institution, as_of, "running", window_start=NOV[0], window_end=as_of)
    body.update(formulaKey=own.FORMULA_KEY, version=1)
    body["parameters"].update(period="Ноябрь 2026", institutions=1, ranked=1)
    record(dsn, body)
    later = (NOV[0] + timedelta(days=9)).isoformat()
    retro = {**body, "asOf": later, "startedAt": later, "windowEnd": later,
             "parameters": {**body["parameters"], "status": "retrospective"}}
    record(dsn, retro)
    with _connect(dsn) as connection:
        months = connection.execute(sql.OWN_MONTHS, {"formula_key": own.FORMULA_KEY}).fetchall()
        run = connection.execute(sql.OWN_RUN, {"formula_key": own.FORMULA_KEY, "window_start": NOV[0]}).fetchone()
        connection.execute("SET ROLE api_read")
        rows = connection.execute(sql.OWN_ROWS, {"run_id": run["id"]}).fetchall()
    assert [(item["month"], item["status"]) for item in months] == [("2026-11", "running")]
    assert run["definition"] == own.FORMULA_V1
    assert (rows[0]["legacy_id"], rows[0]["rank"]) == (world.legacy_id, 8)
