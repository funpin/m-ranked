"""Ночное задание прогноза: выбор месяцев, пропуск без базы, финализация."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from api.tools import rating_forecast as job


class FakeDatabase:
    def __init__(self, periods, scores=None, months=None):
        self.periods, self.scores, self.months = periods, scores or {}, months or []
        self.recorded, self.finalized = [], []

    async def admin_fetch_all(self, query, params=None):
        if "official_periods" in query:
            return [{"period": period} for period in self.periods]
        if "official_period_scores" in query:
            return self.scores.get(params["period"], [])
        raise AssertionError(query)

    async def admin_fetch_one(self, query, params=None):
        if "record_rating_forecast" in query:
            body = json.loads(params["payload"])
            self.recorded.append(body)
            return {"result": {"runId": "r", "replaced": 0}}
        if "finalize_rating_forecast" in query:
            self.finalized.append(params["window_start"])
            return {"result": {"runId": None, "removed": 0}}
        raise AssertionError(query)

    async def fetch_all(self, query, params=None):
        if "WITH coded" in query:
            return self.months
        return []


SCORES = [{"code": "37", "name": "Вуз 37", "social_score": 46.9, "max_score": 60.4, "vk_score": 56.7,
           "rutube_score": 19.2, "consolidated_score": None}]
MONTH_ROWS = [{"institution_id": "00000000-0000-0000-0000-000000000037", "code": "37", "name": "Вуз 37",
               "platform": "vk", "posts": 80, "mature_posts": 70, "mature_views": 70000, "mature_interactions": 1400,
               "viewed_posts": 80, "views": 80000, "interactions": 1600, "covered": True}]


def test_parse_retrospective():
    assert job.parse_retrospective("2026-08..2026-09") == [date(2026, 8, 1), date(2026, 9, 1)]
    with pytest.raises(ValueError):
        job.parse_retrospective("2026-09..2026-08")


def test_job_records_current_month_with_extrapolation_and_finalizes_published():
    database = FakeDatabase(["Август 2026", "Сентябрь 2026"], {"Сентябрь 2026": SCORES}, MONTH_ROWS)
    asyncio.run(job.run(database, datetime(2026, 10, 15, 22, 10, tzinfo=timezone.utc)))
    [body] = database.recorded
    assert body["parameters"]["status"] == "running" and body["parameters"]["basePeriod"] == "Сентябрь 2026"
    assert body["parameters"]["early"] is False and body["parameters"]["postsScale"] == pytest.approx(31 / 16)
    assert body["windowEnd"] == "2026-10-15T22:10:00+00:00"
    vk = body["results"][0]["explanation"]["platforms"]["vk"]
    # Просмотры — по зрелым постам: 70 000 / 70.
    assert vk["metrics"]["avgViews"] == 1000.0 and vk["metrics"]["postsExtrapolated"] == pytest.approx(155.0)
    assert len(database.finalized) == 2


def test_job_skips_a_month_without_a_published_base(caplog):
    database = FakeDatabase([], {}, MONTH_ROWS)
    assert asyncio.run(job.run(database, datetime(2026, 1, 10, tzinfo=timezone.utc))) == []
    assert database.recorded == []
    assert "нет опубликованного базового месяца" in caplog.text


def test_job_retrospective_uses_the_previous_published_month():
    database = FakeDatabase(["Июль 2026", "Август 2026", "Сентябрь 2026"],
                            {"Июль 2026": SCORES, "Август 2026": SCORES}, MONTH_ROWS)
    asyncio.run(job.run(database, datetime(2026, 10, 16, 22, tzinfo=timezone.utc),
                        retrospective=[date(2026, 8, 1), date(2026, 9, 1)]))
    assert [(body["parameters"]["status"], body["parameters"]["basePeriod"]) for body in database.recorded] == \
        [("retrospective", "Июль 2026"), ("retrospective", "Август 2026")]
    assert all(body["parameters"]["postsScale"] == 1.0 for body in database.recorded)


def test_definer_functions_read_the_revision_without_foreign_functions():
    """На проде функции 0084 принадлежат migration_owner, а у него нет EXECUTE на
    analytics.latest_dataset_revision() (владелец — mranked_bootstrap): запись
    снимка падала с InsufficientPrivilege. Ревизию читаем из таблицы напрямую."""
    from pathlib import Path
    migration = (Path(__file__).parents[1] / "db/migrations/0084_rating_forecast.sql").read_text(encoding="utf-8")
    body = migration.split("CREATE FUNCTION ops_and_admin.record_rating_forecast", 1)[1]
    assert "latest_dataset_revision" not in body
    assert body.count("SELECT max(id) INTO revision FROM analytics.dataset_revision") == 2
