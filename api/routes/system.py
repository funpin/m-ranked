"""Состояние системы для панели: снимки сервера за час, три часа, сутки или неделю
и живой буфер ресурсов машины с шагом в несколько секунд."""
from __future__ import annotations

import time
from datetime import datetime, timezone
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
                 period: Annotated[Literal["1h", "3h", "day", "week"], Query(alias="range")] = "day") -> Response:
    now = request.app.state.clock()
    cached = _CACHE.get(period)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return JSONResponse(cached[1], headers=NO_STORE)
    span, bucket = overview.RANGES[period]
    rows = await request.app.state.db.admin_fetch_all(SAMPLES, {"seconds": span + 900})
    latest = rows[-1] if rows else None
    previous = rows[-2]["sample"] if len(rows) > 1 else None
    settings = request.app.state.settings
    summary = overview.status_summary(rows, now, lambda platform: _threshold(settings, platform), span)
    # Период и один снимок перед ним — опора для первых разностей счётчиков.
    start = now - span
    period_rows = overview.period_rows(rows, now, span)
    body = {
        "range": period,
        "sampledAt": summary["sampledAt"],
        "checks": summary["checks"],
        "host": overview.host(latest["sample"], previous) if latest else None,
        "pipeline": overview.pipeline(latest["sample"]) if latest else None,
        "restarts": overview.restarts(period_rows),
        "collection": summary["collection"],
        "series": overview.series(period_rows, bucket, since=start),
        "backups": overview.backups(latest["sample"] if latest else None),
    }
    _CACHE[period] = (time.monotonic(), body)
    return JSONResponse(body, headers=NO_STORE)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


@router.get("/api/v1/admin/system/live", tags=["Admin"])
async def live(request: Request, _: Annotated[Principal, Depends(READ)],
               since: Annotated[datetime | None, Query()] = None) -> Response:
    """Точки живого буфера после since: панель дочитывает только новые."""
    monitor = request.app.state.host_monitor
    if monitor is None:
        return JSONResponse({"intervalSeconds": None, "cores": None, "memoryTotalBytes": None,
                             "diskTotalBytes": None, "diskFreeBytes": None, "points": []}, headers=NO_STORE)
    moment = None
    if since is not None:
        moment = (since if since.tzinfo else since.replace(tzinfo=timezone.utc)).timestamp()
    points = [{**point, "at": _iso(point["at"])} for point in monitor.since(moment)]
    return JSONResponse({
        "intervalSeconds": monitor.interval,
        "cores": monitor.cores,
        "memoryTotalBytes": monitor.memory_total,
        "diskTotalBytes": monitor.disk_total,
        "diskFreeBytes": monitor.disk_free,
        "points": points,
    }, headers=NO_STORE)
