"""Состояние системы для панели: снимки сервера за час, три часа, сутки или неделю
и живой буфер ресурсов машины с шагом в несколько секунд; серверы по одному
(ресурсы, пропуски замеров) и процессы серверов-сборщиков."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from .. import server_monitor as monitor_view
from .. import system_overview as overview
from ..security import Principal, require_roles
from .health import _threshold

router = APIRouter()
READ = require_roles("VIEWER", "EDITOR", "ADMIN")
NO_STORE = {"Cache-Control": "no-store"}
# Панель опрашивает сводку каждые 15 секунд, а снимок появляется раз в минуту:
# дольше держать ответ нельзя, чаще пересчитывать незачем.
CACHE_SECONDS = 15.0
_CACHE: dict[Any, tuple[float, dict[str, Any]]] = {}
# Минутные точки сборщиков приходят раз в минуту: чаще пересчитывать незачем.
NODE_LIVE_CACHE_SECONDS = 10.0
NODE_LIVE_HORIZON_SECONDS = 3 * 3600
NODE_STEP_SECONDS = 60
MAIN_NODE_SQL = "SELECT id, display_name, role, state, platforms, last_seen_at, report - 'files' AS report " \
                "FROM ops_and_admin.server_node WHERE role = 'main'"
Period = Annotated[Literal["1h", "3h", "day", "week"], Query(alias="range")]


def _cached(key: Any, seconds: float) -> dict[str, Any] | None:
    cached = _CACHE.get(key)
    return cached[1] if cached is not None and time.monotonic() - cached[0] < seconds else None


def _remember(key: Any, body: dict[str, Any]) -> dict[str, Any]:
    _CACHE[key] = (time.monotonic(), body)
    return body

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
    # Период и один снимок перед ним — опора для первых разностей счётчиков.
    start = now - span
    period_rows = overview.period_rows(rows, now, span)
    summary = overview.status_summary(rows, now, lambda platform: _threshold(settings, platform), span,
                                      period=period_rows)
    main = await request.app.state.db.admin_fetch_one(MAIN_NODE_SQL)
    last = rows[-1]["observed_at"].timestamp() if rows else None
    body = {
        "range": period,
        "server": monitor_view.status(main, now, last) if main else None,
        "tasks": monitor_view.tasks_view(main),
        "gaps": monitor_view.gaps([(row["observed_at"].timestamp(), row["sample"].get("rel")) for row in period_rows],
                                  now, start, step=60),
        "sampledAt": summary["sampledAt"],
        "checks": summary["checks"],
        "alerts": summary["alerts"],
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


async def _servers(request: Request) -> list[dict[str, Any]]:
    """Подключённые серверы и основной; кэш на тот же срок, что сводка."""
    body = _cached("servers", CACHE_SECONDS)
    if body is None:
        body = _remember("servers", {"rows": await request.app.state.db.admin_fetch_all(monitor_view.LIST_SQL)})
    return body["rows"]


def _pick(rows: list[dict[str, Any]], server: str | None, role: str | None = None) -> dict[str, Any] | None:
    """Выбранный сервер из списка; чужое имя из адреса — первый подходящий."""
    candidates = [row for row in rows if role is None or row["role"] == role]
    return next((row for row in candidates if row["id"] == server), candidates[0] if candidates else None)


@router.get("/api/v1/admin/servers", tags=["Admin"])
async def servers(request: Request, _: Annotated[Principal, Depends(READ)], period: Period = "day",
                  server: Annotated[str | None, Query(max_length=40)] = None) -> Response:
    """Список серверов для переключателя и панель выбранного: состояние,
    ресурсы сейчас и за период, пропуски замеров, службы и задания."""
    now = request.app.state.clock()
    rows = await _servers(request)
    selected = _pick(rows, server)
    key = ("server", period, selected["id"] if selected else None)
    if (body := _cached(key, CACHE_SECONDS)) is not None:
        return JSONResponse(body, headers=NO_STORE)
    span, bucket = overview.RANGES[period]
    start = now - span
    db = request.app.state.db
    last_main = None
    panel = None
    if selected is not None and selected["role"] == "main":
        samples = await db.admin_fetch_all(monitor_view.MAIN_SAMPLES_SQL, {"seconds": span + 900})
        period_rows = overview.period_rows(samples, now, span)
        points = monitor_view.main_points(period_rows)
        last_main = samples[-1]["observed_at"].timestamp() if samples else None
        panel = {
            "host": overview.host(samples[-1]["sample"], samples[-2]["sample"] if len(samples) > 1 else None)
            if samples else None,
            "liveSeconds": request.app.state.host_monitor.interval if request.app.state.host_monitor else None,
            "series": monitor_view.series(points, bucket),
            "gaps": monitor_view.gaps([(row["observed_at"].timestamp(), row["sample"].get("rel")) for row in period_rows],
                                      now, start, step=60),
        }
    elif selected is not None:
        samples = await db.admin_fetch_all(monitor_view.NODE_SAMPLES_SQL,
                                           {"node": selected["id"], "seconds": span + 900})
        inside = [monitor_view.node_point(row) for row in samples if row["observed_at"].timestamp() >= start]
        panel = {
            "host": monitor_view.host_view(selected, inside[-1] if inside else None),
            "liveSeconds": NODE_STEP_SECONDS,
            "series": monitor_view.series(inside, bucket),
            "gaps": monitor_view.gaps([(row["observed_at"].timestamp(), row.get("release")) for row in samples],
                                      now, start),
        }
    if last_main is None and any(row["role"] == "main" for row in rows):
        latest = await db.admin_fetch_one("SELECT max(observed_at) AS at FROM ops_and_admin.host_sample")
        last_main = latest["at"].timestamp() if latest and latest["at"] else None
    body = {
        "range": period,
        "servers": [monitor_view.server_item(row, now, last_main if row["role"] == "main" else None) for row in rows],
        "selected": None if selected is None else {
            **monitor_view.server_item(selected, now, last_main if selected["role"] == "main" else None),
            **panel, "tasks": monitor_view.tasks_view(selected)},
    }
    return JSONResponse(_remember(key, body), headers=NO_STORE)


@router.get("/api/v1/admin/servers/{server}/live", tags=["Admin"])
async def server_live(request: Request, _: Annotated[Principal, Depends(READ)], server: str,
                      since: Annotated[datetime | None, Query()] = None) -> Response:
    """Живые точки сервера после since. Основной — буфер API (шаг в секунды),
    сборщик — минутные точки агента за три часа."""
    rows = await _servers(request)
    selected = _pick(rows, server)
    if selected is None or selected["id"] != server:
        return JSONResponse({"detail": "server not found"}, status_code=404, headers=NO_STORE)
    if selected["role"] == "main":
        return await live(request, _, since)
    now = request.app.state.clock()
    moment = (since if since is None or since.tzinfo else since.replace(tzinfo=timezone.utc))
    seconds = NODE_LIVE_HORIZON_SECONDS if moment is None else max(1.0, min(NODE_LIVE_HORIZON_SECONDS, now - moment.timestamp()))
    # Опрос панелей с разным since попадает в одну минутную корзину кэша.
    key = ("node-live", server, round(seconds / NODE_STEP_SECONDS))
    body = _cached(key, NODE_LIVE_CACHE_SECONDS)
    if body is None:
        samples = await request.app.state.db.admin_fetch_all(monitor_view.NODE_SAMPLES_SQL,
                                                             {"node": server, "seconds": seconds})
        host = monitor_view.host_view(selected, None)
        body = _remember(key, {
            "intervalSeconds": NODE_STEP_SECONDS, "cores": host["cores"], "memoryTotalBytes": host["memoryTotalBytes"],
            "diskTotalBytes": host["diskTotalBytes"], "diskFreeBytes": host["diskFreeBytes"],
            "points": [monitor_view.node_point(row) for row in samples]})
    if moment is not None:
        edge = moment.timestamp()
        body = {**body, "points": [point for point in body["points"]
                                   if datetime.fromisoformat(point["at"]).timestamp() > edge]}
    return JSONResponse(body, headers=NO_STORE)


@router.get("/api/v1/admin/collectors", tags=["Admin"])
async def collectors(request: Request, _: Annotated[Principal, Depends(READ)], period: Period = "day",
                     server: Annotated[str | None, Query(max_length=40)] = None) -> Response:
    """Процессы сервера-сборщика: циклы площадок по журналу циклов, пропуски
    сбора, отправитель переноса и очередь пачек, службы и задания узла."""
    now = request.app.state.clock()
    rows = await _servers(request)
    selected = _pick(rows, server, "collector")
    key = ("collector", period, selected["id"] if selected else None)
    if (body := _cached(key, CACHE_SECONDS)) is not None:
        return JSONResponse(body, headers=NO_STORE)
    span = overview.RANGES[period][0]
    view = None
    if selected is not None:
        db = request.app.state.db
        platforms = monitor_view.collector_platforms(selected)
        runs = await db.admin_fetch_all(monitor_view.RUNS_SQL, {"platforms": platforms, "seconds": span})
        margin = max(overview.PROFILE_B_FRESHNESS.values())
        starts = await db.admin_fetch_all(monitor_view.RUN_STARTS_SQL, {"platforms": platforms, "seconds": span + margin})
        latest = await db.admin_fetch_one(
            "SELECT sample->'pipeline' AS pipeline FROM ops_and_admin.host_sample ORDER BY observed_at DESC LIMIT 1")
        view = monitor_view.collector_view(selected, runs, starts, (latest or {}).get("pipeline"), now, span)
    body = {"range": period,
            "collectors": [monitor_view.server_item(row, now) for row in rows if row["role"] == "collector"],
            "selected": view}
    return JSONResponse(_remember(key, body), headers=NO_STORE)
