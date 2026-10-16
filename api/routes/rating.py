"""Вкладка «Рейтинг»: снимки прогноза М-Рейтинга и каркас «Нашего рейтинга»."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, rating_forecast as rf
from ..cached import serve
from ..db import Database
from ..errors import BadRequest, NotFound
from ..sql import rating as sql

router = APIRouter(tags=["Query"])

# Снимок пишет ночное задание (событие outbox с этим тегом); каталог даёт
# названия и legacy id; официальный импорт — факт опубликованного месяца.
RATING_TAGS = frozenset({"rating-forecast", "rating", "catalog"})
MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

OWN_RATING = {
    "status": "no_methodology",
    "questions": [
        "Какие площадки входят и с какими весами.",
        "Какие метрики считаются и как нормируются.",
        "На что делим: подписчики, контингент или ничего.",
        "Как учитываются аномальные посты.",
        "За какой период и как часто пересчитывается.",
    ],
}


def parse_month(value: str) -> date:
    match = MONTH.fullmatch(value)
    if not match:
        raise BadRequest("month должен иметь вид ГГГГ-ММ")
    return date(int(match.group(1)), int(match.group(2)), 1)


def months_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"months": [{"month": row["month"], "status": row["status"], "asOf": dto.iso(row["as_of"])}
                       for row in rows]}


def _cell(category: str, cell: dict[str, Any], platform: dict[str, Any] | None,
          actual: dict[str, Any] | None) -> dict[str, Any]:
    body = {"score": cell["score"], "rank": cell["rank"], "rankBest": cell["rankBest"],
            "rankWorst": cell["rankWorst"], "baseRank": cell.get("baseRank"), "source": cell["source"],
            "actualRank": (actual or {}).get("rank"),
            "actualScore": float(actual["score"]) if actual and actual.get("score") is not None else None}
    if category != "social":
        metrics = (platform or {}).get("metrics") or {}
        body["metrics"] = ({key: metrics.get(key) for key in ("posts", "postsExtrapolated", "avgViews", "students", "erv")}
                           if (platform or {}).get("source") in ("formula", "source_zero") else None)
    return body


def forecast_body(run: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    parameters = run["parameters"]
    items = []
    for row in rows:
        explanation = row["explanation"]
        actual = row.get("actual") or {}
        items.append({
            "institutionId": row["institution_id"], "legacyId": row["legacy_id"], "name": row["name"],
            "shortName": row["short_name"], "baseConsolidatedRank": explanation.get("baseConsolidatedRank"),
            "categories": {category: _cell(category, explanation["categories"][category],
                                           explanation["platforms"].get(category), actual.get(category))
                           for category in rf.CATEGORIES},
        })
    window = run["window_start"].astimezone(rf.MOSCOW)
    return {"month": f"{window.year:04d}-{window.month:02d}", "status": parameters["status"],
            "period": parameters["period"], "basePeriod": parameters["basePeriod"],
            "asOf": dto.iso(run["as_of"]), "early": bool(parameters.get("early")),
            "formulaVersion": run["version"], "errors": parameters["errors"], "rows": items}


@router.get("/api/v1/rating/forecast/months")
async def forecast_months(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        return months_body(await db.fetch_all(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY}))

    return await serve(request, "rating-forecast-months", {}, RATING_TAGS, build)


@router.get("/api/v1/rating/forecast")
async def forecast(request: Request, month: str | None = Query(None)) -> Response:
    selected = parse_month(month) if month is not None else None

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        target = selected
        if target is None:
            months = await db.fetch_all(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY})
            if not months:
                raise NotFound("снимков прогноза ещё нет")
            target = parse_month(months[0]["month"])
        run = await db.fetch_one(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY,
                                                    "window_start": rf.month_window(target)[0]})
        if run is None:
            raise NotFound("за этот месяц снимка прогноза нет")
        rows = await db.fetch_all(sql.FORECAST_ROWS, {"run_id": run["id"], "period": rf.period_label(target)})
        return forecast_body(run, rows)

    return await serve(request, "rating-forecast", {"month": month}, RATING_TAGS, build)


@router.get("/api/v1/rating/own")
async def own_rating(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        return OWN_RATING

    return await serve(request, "rating-own", {}, frozenset({"rating-own"}), build)
