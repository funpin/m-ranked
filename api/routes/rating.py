"""Вкладка «Рейтинг»: снимки прогноза М-Рейтинга, М-Рейтинг без накрутки и «Наш рейтинг»."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, own_rating as own, rating_clean as rc, rating_forecast as rf
from ..cached import serve
from ..db import Database
from ..errors import BadRequest, NotFound
from ..sql import own_rating as own_sql, rating as sql

router = APIRouter(tags=["Query"])

# Снимок пишет ночное задание (событие outbox с этим тегом); каталог даёт
# названия и legacy id; официальный импорт — факт опубликованного месяца.
RATING_TAGS = frozenset({"rating-forecast", "rating", "catalog"})
MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


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


def _clean_platform(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    smart = item.get("smart")
    return {"views": item["views"], "interactions": item["interactions"],
            "removedViews": item["removedViews"], "removedReactions": item["removedReactions"],
            "smartReactions": item["smartReactions"], "rawScore": item["rawScore"], "cleanScore": item["cleanScore"],
            "smart": None if smart is None else {key: smart[key] for key in ("evenness", "medianReactions",
                                                                               "tailRatio", "tailP90")}}


def clean_body(run: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    parameters = run["parameters"]
    items = []
    for row in rows:
        explanation = row["explanation"]
        items.append({
            "institutionId": row["institution_id"], "legacyId": row["legacy_id"], "name": row["name"],
            "shortName": row["short_name"],
            "categories": {category: {key: cell[key] for key in ("score", "rank", "baseScore", "baseRank")}
                           for category, cell in explanation["categories"].items()},
            "platforms": {platform: _clean_platform(explanation["platforms"].get(platform)) for platform in ("max", "vk")},
            "rutubeBatch": explanation.get("rutubeBatch"),
        })
    window = run["window_start"].astimezone(rf.MOSCOW)
    return {"month": f"{window.year:04d}-{window.month:02d}", "status": parameters["status"],
            "period": parameters["period"], "basis": parameters["basis"], "basisPeriod": parameters["basisPeriod"],
            "asOf": dto.iso(run["as_of"]), "formulaVersion": run["version"],
            "baseFormulaVersion": parameters["baseFormulaVersion"], "rows": items}


@router.get("/api/v1/rating/clean/months")
async def clean_months(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        return months_body(await db.fetch_all(sql.CLEAN_MONTHS, {"formula_key": rc.CLEAN_KEY}))

    return await serve(request, "rating-clean-months", {}, RATING_TAGS, build)


@router.get("/api/v1/rating/clean")
async def clean(request: Request, month: str | None = Query(None)) -> Response:
    selected = parse_month(month) if month is not None else None

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        target = selected
        if target is None:
            months = await db.fetch_all(sql.CLEAN_MONTHS, {"formula_key": rc.CLEAN_KEY})
            if not months:
                raise NotFound("снимков без накрутки ещё нет")
            target = parse_month(months[0]["month"])
        run = await db.fetch_one(sql.CLEAN_RUN, {"formula_key": rc.CLEAN_KEY,
                                                 "window_start": rf.month_window(target)[0]})
        if run is None:
            raise NotFound("за этот месяц снимка без накрутки нет")
        rows = await db.fetch_all(sql.FORECAST_ROWS, {"run_id": run["id"], "period": rf.period_label(target)})
        return clean_body(run, rows)

    return await serve(request, "rating-clean", {"month": month}, RATING_TAGS, build)


# ---- «Наш рейтинг» (api.own_rating) ----

FORMULA_FIELDS = ("weights", "activeDays", "reachPerStudent", "erv", "minPosts")


def _own_platform(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item.get("metrics") or {}
    shown = item["source"] in ("formula", "partial", "no_posts") and "posts" in metrics
    return {"source": item["source"], "score": item["score"], "rawScore": item["rawScore"],
            "subscores": item["subscores"] or None,
            "metrics": {key: metrics.get(key) for key in ("posts", "activeDays", "coveredDays", "avgViews", "students",
                                                           "reach", "erv", "removedViews", "removedInteractions",
                                                           "evenCapped")} if shown else None}


def own_body(run: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    parameters, definition = run["parameters"], run["definition"]
    items = []
    for row in rows:
        explanation = row["explanation"]
        items.append({
            "institutionId": row["institution_id"], "legacyId": row["legacy_id"], "name": row["name"],
            "shortName": row["short_name"], "rank": row["rank"], "score": float(row["score"]),
            "rawRank": explanation["rawRank"], "rawScore": explanation["rawScore"], "partial": explanation["partial"],
            "platforms": {platform: _own_platform(explanation["platforms"][platform]) for platform in own.PLATFORMS},
        })
    window = run["window_start"].astimezone(rf.MOSCOW)
    return {"month": f"{window.year:04d}-{window.month:02d}", "status": parameters["status"],
            "period": parameters["period"], "asOf": dto.iso(run["as_of"]),
            "institutions": parameters["institutions"], "ranked": parameters["ranked"],
            "formula": {"version": run["version"], **{key: definition[key] for key in FORMULA_FIELDS}},
            "rows": items}


@router.get("/api/v1/rating/own/months")
async def own_months(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        return months_body(await db.fetch_all(own_sql.OWN_MONTHS, {"formula_key": own.FORMULA_KEY}))

    return await serve(request, "rating-own-months", {}, RATING_TAGS, build)


@router.get("/api/v1/rating/own")
async def own_rating(request: Request, month: str | None = Query(None)) -> Response:
    selected = parse_month(month) if month is not None else None

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        target = selected
        if target is None:
            months = await db.fetch_all(own_sql.OWN_MONTHS, {"formula_key": own.FORMULA_KEY})
            if not months:
                raise NotFound("снимков нашего рейтинга ещё нет")
            target = parse_month(months[0]["month"])
        run = await db.fetch_one(own_sql.OWN_RUN, {"formula_key": own.FORMULA_KEY,
                                                   "window_start": rf.month_window(target)[0]})
        if run is None:
            raise NotFound("за этот месяц снимка нашего рейтинга нет")
        return own_body(run, await db.fetch_all(own_sql.OWN_ROWS, {"run_id": run["id"]}))

    return await serve(request, "rating-own", {"month": month}, RATING_TAGS, build)
