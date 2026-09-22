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
