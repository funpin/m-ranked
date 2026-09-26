"""Кандидаты и почасовые сравнения."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, params as normalize
from ..cached import serve
from ..db import Database
from ..errors import BadRequest
from ..sql import compare as sql

router = APIRouter(tags=["Query"])

COMPARE_TAGS = frozenset({"publications", "catalog", "comparison"})
PLATFORMS = ("telegram", "vk", "max", "rutube")
HORIZONS = (24, 48, 72, 168, 336)
METRICS = ("views", "reactions", "comments", "shares")


def _choice(value: Any, allowed: tuple[Any, ...], name: str) -> Any:
    if value not in allowed:
        raise BadRequest(f"{name} должен быть одним из {', '.join(map(str, allowed))}")
    return value


def _selection(values: list[str] | None, name: str) -> list[int]:
    if values is None:
        return []
    if len(values) > 2000:
        raise BadRequest(f"параметр {name} содержит больше 2000 значений")
    result: list[int] = []
    seen: set[int] = set()
    for raw in values:
        if not raw.isascii() or not raw.isdigit() or raw.startswith("0"):
            raise BadRequest(f"значения {name} должны быть положительными целыми")
        value = int(raw)
        if value > (1 << 63) - 1:
            raise BadRequest(f"значение {name} не помещается в int64")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


@router.get("/api/v1/compare/candidates")
async def candidates(request: Request, platform: str = Query("telegram"),
                     limit: int = Query(50), cursor: str | None = Query(None)) -> Response:
    resolved_platform = _choice(platform, PLATFORMS, "platform")
    page_size = normalize.limit(limit)
    dimensions = f"compare-candidates:{resolved_platform}"

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        rows = await request.app.state.db.fetch_all(sql.CANDIDATES, {
            "platform": resolved_platform, "as_of": committed_at,
            "after_id": after_id, "fetch_limit": page_size + 1,
        })
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        return {"items": [dto.comparison_candidate(row) for row in visible],
                "nextCursor": normalize.encode_scoped_cursor(
                    str(visible[-1]["entity_id"]) if has_more and visible else None,
                    revision, dimensions),
                "datasetRevision": revision, "asOf": committed_at.isoformat()}

    return await serve(request, "comparison-candidates", {
        "platform": resolved_platform, "limit": page_size, "cursor": cursor or "",
    }, COMPARE_TAGS, build,
        pinned_revision=normalize.cursor_revision(cursor))


@router.get("/api/v1/compare")
async def comparison(
    request: Request,
    platform: str = Query("telegram"), horizonHours: int = Query(72),
    includePartial: bool = Query(False), metric: str = Query("reactions"),
    aggregation: str = Query("median"), institutionLimit: int = Query(25),
    channels: list[str] | None = Query(None), institutions: list[str] | None = Query(None),
    selectionCursor: str | None = Query(None),
) -> Response:
    resolved_platform = _choice(platform, PLATFORMS, "platform")
    horizon = _choice(horizonHours, HORIZONS, "horizonHours")
    resolved_metric = _choice(metric, METRICS, "metric")
    resolved_aggregation = _choice(aggregation, ("sum", "median"), "aggregation")
    page_size = normalize.limit(institutionLimit, default=25, maximum=50)
    relevant_name = "channels" if resolved_platform == "telegram" else "institutions"
    explicit = _selection(channels if resolved_platform == "telegram" else institutions, relevant_name)
    dimensions = json.dumps({
        "platform": resolved_platform, "horizon": horizon, "partial": includePartial,
        "metric": resolved_metric, "aggregation": resolved_aggregation,
        "limit": page_size, "selection": explicit,
    }, sort_keys=True, separators=(",", ":"))

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        after = normalize.scoped_cursor(selectionCursor, revision, dimensions)
        next_cursor: str | None = None
        if explicit:
            offset = uuid.UUID(after).int if after else 0
            if offset < 0 or offset >= len(explicit):
                if after or offset:
                    raise BadRequest("курсор выбора повреждён")
            end = min(offset + page_size, len(explicit))
            selected_ids = explicit[offset:end]
            if end < len(explicit):
                next_cursor = normalize.encode_scoped_cursor(
                    str(uuid.UUID(int=end)), revision, dimensions)
        else:
            candidate_rows = await db.fetch_all(sql.CANDIDATES, {
                "platform": resolved_platform, "as_of": committed_at,
                "after_id": after, "fetch_limit": page_size + 1,
            })
            has_more = len(candidate_rows) > page_size
            visible_candidates = candidate_rows[:page_size]
            selected_ids = [int(row["legacy_id"]) for row in visible_candidates]
            if has_more and visible_candidates:
                next_cursor = normalize.encode_scoped_cursor(
                    str(visible_candidates[-1]["entity_id"]), revision, dimensions)

        values = {
            "as_of": committed_at, "revision": revision, "platform": resolved_platform,
            "horizon_hours": horizon, "include_partial": includePartial,
            "metric": resolved_metric, "aggregation": resolved_aggregation,
            "selection_ids": json.dumps(selected_ids),
            "hot_days": request.app.state.settings.retention_days,
        }
        rows = await db.fetch_all(sql.COMPARISON, values) if selected_ids else []
        grouped: dict[Any, dict[str, Any]] = {}
        first = rows[0] if rows else None
        for row in rows:
            selection_id = row["selection_id"]
            if selection_id is None:
                continue
            group = grouped.setdefault(selection_id, {"row": row, "points": [], "engagement": []})
            if row["hour_offset"] is not None:
                group["points"].append(dto.comparison_point(row))
                group["engagement"].append(dto.comparison_point(row, True))
        series = [dto.comparison_series(group["row"], group["points"], group["engagement"])
                  for group in grouped.values()]
        if first:
            cohort_id = str(first["cohort_id"])
            cohort_size = first["cohort_sample_size"]
        else:
            digest = hashlib.md5(
                f"live|{revision}|{resolved_platform}|{horizon}|{str(includePartial).lower()}".encode(),
                usedforsecurity=False).hexdigest()
            cohort_id = str(uuid.UUID(digest))
            cohort_size = 0
        return {"cohortId": cohort_id, "platform": resolved_platform,
                "horizonHours": horizon, "includePartial": includePartial,
                "metric": resolved_metric, "aggregation": resolved_aggregation,
                "selectionType": relevant_name, "cohortSampleSize": cohort_size,
                "series": series, "datasetRevision": revision,
                "asOf": committed_at.isoformat(), "nextSelectionCursor": next_cursor}

    return await serve(request, "comparison", {
        "dimensions": dimensions, "cursor": selectionCursor or "",
    }, COMPARE_TAGS, build,
        pinned_revision=normalize.cursor_revision(selectionCursor))


DASHBOARD_PERIODS = {"7d": 7, "30d": 30}
CHECKPOINT_HOURS = (1, 3, 6, 12, 24, 48, 72, 168)


def _number(value: Any, digits: int = 0) -> float | int | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if digits == 0 else rounded


def _json_rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


def dashboard_body(period: str, revision: int, committed_at: Any, dashboard: dict[str, Any],
                   curves: list[dict[str, Any]], institutions: list[dict[str, Any]]) -> dict[str, Any]:
    """Всё, что рисует страница сравнения, одним ответом без ограничения числа
    вузов. Медианы — значения на 24-м часу; суммы — по последнему замеру."""
    curve_rows: dict[tuple[Any, str], dict[str, list[Any]]] = {}
    for row in curves:
        key = (str(row["institution_id"]) if row["institution_id"] else None, row["platform"])
        curve = curve_rows.setdefault(key, {
            "samples": [0] * len(CHECKPOINT_HOURS),
            "views": [None] * len(CHECKPOINT_HOURS),
            "reactions": [None] * len(CHECKPOINT_HOURS),
        })
        index = CHECKPOINT_HOURS.index(int(row["hour_offset"]))
        curve["samples"][index] = int(row["samples"])
        curve["views"][index] = _number(row["views"])
        curve["reactions"][index] = _number(row["reactions"])
    return {
        "period": period, "hours": list(CHECKPOINT_HOURS),
        "datasetRevision": revision, "asOf": committed_at.isoformat(),
        "institutions": [{
            "institutionId": str(row["id"]), "legacyId": row["legacy_id"],
            "name": row["canonical_name"], "shortName": row["short_name"],
            "platforms": sorted(row["platforms"] or []),
            "subscribers": {platform: int(row[platform] or 0) for platform in PLATFORMS},
        } for row in institutions],
        "stats": [{
            "institutionId": row["institution_id"], "platform": row["platform"],
            "posts": row["posts"], "viewsTotal": row["views_total"],
            "reactionsTotal": row["reactions_total"], "commentsTotal": row["comments_total"],
            "sharesTotal": row["shares_total"], "sample24": row["sample24"],
            "views24": _number(row["views24"]), "reactions24": _number(row["reactions24"]),
            "comments24": _number(row["comments24"]), "shares24": _number(row["shares24"]),
            "engagement24": _number(row["engagement24"], 3),
            "analyzed": row["analyzed"],
            "levels": [row["level0"], row["level1"], row["level2"], row["level3"]],
        } for row in _json_rows(dashboard.get("stats"))],
        "curves": [{"institutionId": institution, "platform": platform, **curve}
                   for (institution, platform), curve in curve_rows.items()],
        "daily": [{
            "platform": row["platform"], "day": row["day"], "posts": row["posts"],
            "viewsTotal": row["views_total"], "reactionsTotal": row["reactions_total"],
            "analyzed": row["analyzed"], "anomalous": row["anomalous"],
        } for row in _json_rows(dashboard.get("daily"))],
        "timing": [{
            "platform": row["platform"], "weekday": row["weekday"], "hour": row["hour"],
            "posts": row["posts"], "views24": _number(row["views24"]),
        } for row in _json_rows(dashboard.get("timing"))],
        "types": [{
            "platform": row["platform"], "type": row["publication_type"], "posts": row["posts"],
            "views24": _number(row["views24"]), "engagement24": _number(row["engagement24"], 3),
        } for row in _json_rows(dashboard.get("types"))],
    }


@router.get("/api/v1/compare/dashboard")
async def dashboard(request: Request, period: str = Query("30d")) -> Response:
    resolved_period = _choice(period, tuple(DASHBOARD_PERIODS), "period")
    days = DASHBOARD_PERIODS[resolved_period]

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        values = {"as_of": committed_at, "days": days}
        dashboard_row = await db.fetch_one(sql.DASHBOARD, values)
        curves = await db.fetch_all(sql.DASHBOARD_CURVES, values)
        institutions = await db.fetch_all(sql.DASHBOARD_INSTITUTIONS, {})
        return dashboard_body(resolved_period, revision, committed_at,
                              dict(dashboard_row or {}), curves, institutions)

    return await serve(request, "comparison-dashboard", {"period": resolved_period},
                       COMPARE_TAGS, build)
