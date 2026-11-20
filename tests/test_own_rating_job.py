"""«Наш рейтинг» в ночном задании прогноза: месяцы, закрытие, сбой не мешает прогнозу."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

from api import own_rating as own
from api.tools import own_rating as job

INSTITUTION = "00000000-0000-0000-0000-000000000037"


def row(platform, **values):
    base = {"institution_id": INSTITUTION, "account_id": f"acc-{platform}", "platform": platform,
            "covered_days": 19.9, "posts": 60, "active_days": 18, "mature_posts": 50, "mature_views": 50_000,
            "mature_interactions": 1000, "mature_pack_views": 0, "mature_pack_reactions": 300,
            "viewed_posts": 60, "views": 60_000, "interactions": 1200, "pack_views": 0, "pack_reactions": 300,
            "median_reactions": 40.0, "residuals": 30, "evenness": 0.5, "profiles": 19, "confident": 12,
            "late_share": 0.4}
    return {**base, **values}


class FakeDatabase:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows if rows is not None else [row(p) for p in own.PLATFORMS], fail
        self.recorded, self.finalized, self.params = [], [], []

    async def fetch_all(self, query, params=None):
        if self.fail:
            raise RuntimeError("boom")
        if "WITH account" in query:
            self.params.append(params)
            return self.rows
        if "visible_institution institution" in query:
            return [{"institution_id": INSTITUTION, "name": "Вуз 37"}]
        raise AssertionError(query)

    async def admin_fetch_one(self, query, params=None):
        if "record_rating_forecast" in query:
            self.recorded.append(json.loads(params["payload"]))
            return {"result": {"runId": "r", "replaced": 0}}
        if "finalize_rating_forecast" in query:
            self.finalized.append((params["formula_key"], params["window_start"]))
            return {"result": {"runId": "r", "removed": 1}}
        raise AssertionError(query)


def test_months_start_from_november_2026():
    assert job.months_to_rate(datetime(2026, 10, 20, 22, tzinfo=timezone.utc)) == ([], None)
    assert job.months_to_rate(datetime(2026, 11, 20, 22, tzinfo=timezone.utc)) == ([(date(2026, 11, 1), "running")], None)


def test_previous_month_is_refined_until_the_7th_then_closed():
    # 7 декабря 01:47 МСК — ноябрь ещё уточняется; 8-го — закрывается.
    assert job.months_to_rate(datetime(2026, 12, 6, 22, 47, tzinfo=timezone.utc)) == (
        [(date(2026, 11, 1), "final"), (date(2026, 12, 1), "running")], None)
    assert job.months_to_rate(datetime(2026, 12, 7, 22, 47, tzinfo=timezone.utc)) == (
        [(date(2026, 12, 1), "running")], date(2026, 11, 1))


def test_late_excess_needs_confident_tail_most_of_the_month():
    assert job.account_month(row("max")).late_share == 0.4
    assert job.account_month(row("max", confident=9)).late_share is None      # меньше половины профилей
    assert job.account_month(row("max", profiles=8, confident=8)).late_share is None  # мало профилей
    # Нет зрелых постов (первые дни месяца) — берутся все.
    early = job.account_month(row("vk", mature_posts=0))
    assert (early.viewed_posts, early.views, early.pack_reactions) == (60, 60_000, 300)


def test_run_records_the_running_month():
    database = FakeDatabase()
    as_of = datetime(2026, 11, 20, 22, 47, tzinfo=timezone.utc)
    asyncio.run(job.run(database, as_of))
    [body] = database.recorded
    assert (body["formulaKey"], body["version"]) == (own.FORMULA_KEY, 1)
    assert body["parameters"]["status"] == "running" and body["parameters"]["ranked"] == 1
    assert body["windowStart"] == "2026-10-31T21:00:00+00:00" and body["windowEnd"] == "2026-11-20T22:47:00+00:00"
    [params] = database.params
    assert (as_of - params["mature_before"]).days == 3
    [result] = body["results"]
    assert result["institutionId"] == INSTITUTION and result["rank"] == 1
    # Вычитается большее из пакетов (300) и хвоста (0.4 · 1000 = 400).
    assert result["explanation"]["platforms"]["max"]["metrics"]["removedInteractions"] == 400


def test_run_closes_the_previous_month_after_the_7th():
    database = FakeDatabase()
    asyncio.run(job.run(database, datetime(2026, 12, 9, 22, 47, tzinfo=timezone.utc)))
    assert [body["parameters"]["status"] for body in database.recorded] == ["running"]
    assert database.finalized == [(own.FORMULA_KEY, datetime(2026, 10, 31, 21, tzinfo=timezone.utc))]


def test_retrospective_skips_months_before_the_first():
    database = FakeDatabase()
    asyncio.run(job.run(database, datetime(2026, 12, 9, 22, tzinfo=timezone.utc),
                        retrospective=[date(2026, 10, 1), date(2026, 11, 1)]))
    assert [body["parameters"]["status"] for body in database.recorded] == ["retrospective"]
    assert database.finalized == []


def test_failure_is_logged_not_raised():
    database = FakeDatabase(fail=True)
    assert asyncio.run(job.run(database, datetime(2026, 11, 20, 22, tzinfo=timezone.utc))) == []
    assert database.recorded == []
