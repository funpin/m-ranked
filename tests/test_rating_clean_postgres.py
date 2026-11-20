"""«М-Рейтинг без накрутки» в базе: строка формулы и выбор снимка месяца.

Применить 0084, 0093 и 0094 к одноразовой базе «Находок»; без неё пропускается.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from api import rating_clean as rc
from api.sql import rating as sql
from test_findings_postgres import World, _connect, dsn  # noqa: F401 — фикстура dsn
from test_rating_forecast_postgres import END, SEPT, START, clean, coded, latest, payload, record  # noqa: F401 — фикстура clean


def test_clean_formula_matches_the_python_definition(dsn):
    with _connect(dsn) as connection:
        row = connection.execute("SELECT definition, status, source_hash FROM rating.formula_definition "
                                 "WHERE formula_key=%s AND version=1", (rc.CLEAN_KEY,)).fetchone()
    assert row["status"] == "published" and row["definition"] == rc.FORMULA_CLEAN_V1
    canonical = json.dumps(rc.FORMULA_CLEAN_V1, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row["source_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def clean_payload(institution, as_of, status):
    body = payload(institution, as_of, status)
    body.update(formulaKey=rc.CLEAN_KEY, version=1)
    body["parameters"].update(period="Октябрь 2026", basis="fact" if status == "retrospective" else "forecast",
                              basisPeriod="Октябрь 2026", formulaVersion=1, baseFormulaVersion=2)
    return body


def test_published_month_shows_the_fact_based_snapshot_and_forecast_page_ignores_it(dsn):
    institution = World(dsn, "vk").institution
    running = record(dsn, clean_payload(institution, END - timedelta(days=1), "running"))
    retro = record(dsn, clean_payload(institution, END + timedelta(days=20), "retrospective"))
    later = record(dsn, clean_payload(institution, END + timedelta(days=25), "running"))
    with _connect(dsn) as connection:
        run = connection.execute(sql.CLEAN_RUN, {"formula_key": rc.CLEAN_KEY, "window_start": START}).fetchone()
        forecast = connection.execute(sql.FORECAST_RUN, {"formula_key": "m-rating-social-forecast",
                                                         "window_start": START}).fetchone()
    assert running["runId"] != retro["runId"] != later["runId"]
    assert str(run["id"]) == str(retro["runId"])
    assert forecast is None


def test_packs_and_smart_signs_are_read_as_api_read(dsn):
    world = World(dsn, "vk")
    code = f"c{world.legacy_id}"
    coded(dsn, world, code)
    pack = {"title": "Пакет реакций с остановкой", "metric": "reactions", "strength": 0.99,
            "render": {"kind": "regime", "episodeReactions": 118, "episodeGrowth": 120}}
    lead = {"title": "Реакции раньше просмотров", "metric": "reactions", "strength": 1.0,
            "render": {"kind": "lead", "reactionsDelta": 56, "expected": 1}}
    gap = {"title": "Прирост за пробел в замерах", "metric": "views", "strength": 1.0,
           "render": {"kind": "gap", "episodeGrowth": 5000}}
    weak = {"title": "Рывок", "metric": "views", "strength": 0.6, "render": {"kind": "plateau", "episodeGrowth": 900}}
    day = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    packed = world.post(day, {}, level=3, signals=[pack, lead, gap, weak])
    plain = world.post(day.replace(hour=12), {}, level=2, signals=[pack])   # уровень 2 не вычитается
    latest(dsn, packed, 2000, 200, 10, 5)
    latest(dsn, plain, 1500, 150)
    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_read'").fetchone():
            pytest.skip("роль api_read не создана")
        connection.execute("SET ROLE api_read")
        parameters = {"window_start": SEPT[0], "window_end": SEPT[1], "mature_before": SEPT[1]}
        [row] = [row for row in connection.execute(sql.PLATFORM_INFLATION, parameters).fetchall() if row["code"] == code]
        [smart] = [row for row in connection.execute(sql.ACCOUNT_SMART, parameters).fetchall() if row["code"] == code]
    # Крупнейший эпизод реакций — 120; пробел в замерах и слабый сигнал не считаются.
    assert (row["mature_reactions"], row["mature_views"], row["mature_posts"]) == (120, 0, 2)
    # Два поста одного дня: остаток считается, хвоста в профиле нет.
    assert smart["residuals"] == 2 and smart["tail_ratio"] is None
    assert smart["interactions"] == 365
