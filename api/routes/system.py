"""Состояние системы для панели: снимки сервера за сутки или неделю."""
from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from .. import system_overview as overview
from ..security import Principal, require_roles
from .health import _threshold

router = APIRouter()
READ = require_roles("VIEWER", "EDITOR", "ADMIN")
NO_STORE = {"Cache-Control": "no-store"}
# Панель опрашивает сводку каждые 15 секунд, а снимок появляется раз в минуту:
# дольше держать ответ нельзя, чаще пересчитывать незачем.
CACHE_SECONDS = 15.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Опорный снимок перед началом периода нужен для разности счётчиков процессора.
SAMPLES = """
SELECT observed_at, sample - 'sizes' AS sample FROM ops_and_admin.host_sample
WHERE observed_at >= now() - make_interval(secs => %(seconds)s)
ORDER BY observed_at
"""


@router.get("/api/v1/admin/system", tags=["Admin"])
async def system(request: Request, _: Annotated[Principal, Depends(READ)],
                 period: Annotated[Literal["day", "week"], Query(alias="range")] = "day") -> Response:
    now = request.app.state.clock()
    cached = _CACHE.get(period)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return JSONResponse(cached[1], headers=NO_STORE)
    span, bucket = overview.RANGES[period]
    rows = await request.app.state.db.admin_fetch_all(SAMPLES, {"seconds": span + 900})
    latest = rows[-1] if rows else None
    previous = rows[-2]["sample"] if len(rows) > 1 else None
    sampled_at = latest["observed_at"].timestamp() if latest else None
    settings = request.app.state.settings
    window = [row for row in rows if row["observed_at"].timestamp() >= now - 3 * 3600]
    freshness: dict[str, tuple[float | None, int]] = {}
    for platform in overview.PLATFORMS:
        moments = [row["sample"].get("collection", {}).get(platform, {}).get("lastOk") for row in window]
        known = [moment for moment in moments if isinstance(moment, (int, float))]
        freshness[platform] = (max(known) if known else None, _threshold(settings, platform))
    recent = [row for row in rows if row["observed_at"].timestamp() >= now - 3600]
    # Период и один снимок перед ним — опора для первых разностей счётчиков.
    start = now - span
    inside = [row for row in rows if row["observed_at"].timestamp() >= start]
    period_rows = [row for row in rows if row["observed_at"].timestamp() < start][-1:] + inside
    body = {
        "range": period,
        "sampledAt": latest["observed_at"].isoformat() if latest else None,
        "checks": overview.checks(now, sampled_at, latest["sample"] if latest else None, recent, freshness),
        "host": overview.host(latest["sample"], previous) if latest else None,
        "pipeline": overview.pipeline(latest["sample"]) if latest else None,
        "restarts": overview.restarts(period_rows),
        "collection": overview.collection(period_rows),
        "series": overview.series(period_rows, bucket, since=start),
        "backups": overview.backups(latest["sample"] if latest else None),
    }
    _CACHE[period] = (time.monotonic(), body)
    return JSONResponse(body, headers=NO_STORE)
