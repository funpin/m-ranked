"""Маршруты «Рейтинга»: сборка ответа по контракту, 404, заглушка."""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from api.errors import NotFound
from api.routes import rating

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"


def validate(body, schema):
    registry = Registry().with_resource("urn:contract", Resource.from_contents(
        yaml.safe_load(CONTRACT.read_text(encoding="utf-8")), default_specification=DRAFT202012))
    errors = list(Draft202012Validator({"$ref": f"urn:contract#/components/schemas/{schema}"},
                                       registry=registry).iter_errors(json.loads(json.dumps(body, default=str))))
    assert not errors, [f"{list(error.path)}: {error.message}" for error in errors]


CELL = {"score": 65.9, "rank": 8, "rankBest": 5, "rankWorst": 14, "baseRank": 11, "source": "formula"}
RUN = {"id": "run", "as_of": datetime(2026, 10, 16, 22, tzinfo=timezone.utc),
       "window_start": datetime(2026, 8, 31, 21, tzinfo=timezone.utc), "version": 1,
       "parameters": {"status": "retrospective", "basePeriod": "Август 2026", "period": "Сентябрь 2026",
                      "errors": {"social": 7, "max": 10, "vk": 9, "rutube": 8}, "postsScale": 1.0, "early": False}}
ROW = {"institution_id": "aac11cf4-9cf6-5b88-b474-9691b38b8235", "legacy_id": 12, "name": "СКФУ",
       "short_name": None, "score": 65.9, "rank": 8,
       "explanation": {"code": "61", "baseConsolidatedRank": None,
                       "categories": {key: dict(CELL) for key in ("social", "max", "vk", "rutube")},
                       "platforms": {"vk": {"source": "formula", "subscores": {"posts": 100.0},
                                            "metrics": {"posts": 120, "postsExtrapolated": 120.0, "avgViews": 950.0,
                                                        "students": 20000, "erv": 0.021}},
                                     "max": {"source": "fallback", "subscores": {}, "metrics": {"posts": 3}},
                                     "rutube": {"source": "no_account", "subscores": {}, "metrics": {}}}},
       "actual": {"social": {"rank": 8, "score": 65.9}, "vk": {"rank": 38, "score": 70.2}}}


def test_forecast_body_matches_the_contract():
    body = rating.forecast_body(RUN, [ROW])
    validate(body, "RatingForecast")
    assert (body["month"], body["status"], body["basePeriod"]) == ("2026-09", "retrospective", "Август 2026")
    row = body["rows"][0]
    assert row["categories"]["social"]["actualRank"] == 8 and row["categories"]["max"]["actualRank"] is None
    assert row["categories"]["vk"]["metrics"]["avgViews"] == 950.0
    assert row["categories"]["max"]["metrics"] is None and "metrics" not in row["categories"]["social"]


def test_months_body_matches_the_contract():
    body = rating.months_body([{"month": "2026-10", "status": "running", "as_of": RUN["as_of"]}])
    validate(body, "RatingForecastMonths")


def own_run():
    from api import own_rating as own
    return {"id": "own", "as_of": datetime(2026, 11, 20, 22, tzinfo=timezone.utc),
            "window_start": datetime(2026, 10, 31, 21, tzinfo=timezone.utc), "version": 1,
            "definition": own.FORMULA_V1,
            "parameters": {"status": "running", "period": "Ноябрь 2026", "formulaVersion": 1, "elapsedDays": 20.9,
                           "institutions": 133, "ranked": 2}}


def own_rows():
    from api import own_rating as own
    accounts = [own.AccountMonth(platform=platform, covered_days=20.9, posts=60, active_days=18, viewed_posts=55,
                                 views=55_000, interactions=1100, pack_reactions=200 if platform == "vk" else 0)
                for platform in ("telegram", "vk", "max")]
    institutions = [own.InstitutionMonth("aac11cf4-9cf6-5b88-b474-9691b38b8235", "Вуз А", 8000, tuple(accounts)),
                    own.InstitutionMonth("bac11cf4-9cf6-5b88-b474-9691b38b8235", "Вуз Б", 3000,
                                         (*accounts, own.AccountMonth("rutube", 9.0, 2, 2, 2, 100, 1)))]
    rows = own.compute(institutions, elapsed_days=20.9, days_in_month=30)
    return [{"institution_id": row["institutionId"], "legacy_id": None, "name": row["institutionId"][:4],
             "short_name": None, "score": row["score"], "rank": row["rank"], "explanation": row["explanation"]}
            for row in rows]


def test_own_rating_body_matches_the_contract():
    body = rating.own_body(own_run(), own_rows())
    validate(body, "OwnRating")
    assert (body["month"], body["status"], body["ranked"]) == ("2026-11", "running", 2)
    assert body["formula"]["weights"] == {"telegram": 0.25, "vk": 0.25, "max": 0.25, "rutube": 0.25}
    first = body["rows"][0]
    assert first["platforms"]["vk"]["metrics"]["removedInteractions"] == 200
    # Rutube без аккаунта — 0 без метрик; собранный 9 дней из 21 — «нет данных».
    sources = {row["institutionId"][:4]: row["platforms"]["rutube"]["source"] for row in body["rows"]}
    assert sources == {"aac1": "no_account", "bac1": "no_data"}
    assert all(row["platforms"]["rutube"]["metrics"] is None for row in body["rows"])


def test_own_months_body_matches_the_contract():
    validate(rating.months_body([{"month": "2026-11", "status": "running", "as_of": own_run()["as_of"]}]),
             "RatingForecastMonths")


@pytest.mark.parametrize("value", ["2026-13", "26-10", "2026-1", "x"])
def test_month_parameter_is_validated(value):
    from api.errors import BadRequest
    with pytest.raises(BadRequest):
        rating.parse_month(value)


def test_missing_snapshot_is_404(monkeypatch):
    class Read:
        async def fetch_all(self, query, params=None): return []
        async def fetch_one(self, query, params=None): return None
    async def serve(_request, _namespace, _query, _tags, build):
        return await build(1, None)
    monkeypatch.setattr(rating, "serve", serve)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=Read())))
    with pytest.raises(NotFound):
        asyncio.run(rating.forecast(request, "2026-10"))


def test_source_zero_cell_matches_the_contract():
    row = json.loads(json.dumps(ROW))
    row["explanation"]["categories"]["max"]["source"] = "source_zero"
    row["explanation"]["platforms"]["max"] = {"source": "source_zero", "subscores": {"posts": 100.0},
                                              "metrics": {"posts": 104, "postsExtrapolated": 104.0, "avgViews": 300.0,
                                                          "students": 5000, "erv": 0.03}}
    body = rating.forecast_body(RUN, [row])
    validate(body, "RatingForecast")
    # Метрики канала видны: у нас он живой, ноль ставит источник.
    assert body["rows"][0]["categories"]["max"]["metrics"]["posts"] == 104
