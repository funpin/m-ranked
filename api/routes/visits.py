"""Маячок посещений и сводка посетителей для панели (миграция 0053)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from ..security import Principal, require_roles
from ..security_events import source_address
from ..visits import ONLINE_WINDOW, moscow_day

router = APIRouter()
READ = require_roles("VIEWER", "EDITOR", "ADMIN")
NO_STORE = {"Cache-Control": "no-store"}
RANGES = {"week": 7, "month": 30}

ONLINE = """
SELECT count(*) AS online FROM ops_and_admin.site_visitor
WHERE last_seen > now() - make_interval(secs => %(seconds)s)
"""
# Закрытые сутки берутся из итога; сутки, итог которых ещё не подведён
# (сегодня и первые минуты после полуночи), — прямо из посетителей.
DAYS = """
SELECT day, visitors, views FROM ops_and_admin.site_visit_daily WHERE day >= %(start)s
UNION ALL
SELECT day, count(*)::integer, coalesce(sum(views), 0)::integer FROM ops_and_admin.site_visitor
WHERE day >= %(start)s GROUP BY day
"""


@router.post("/api/v1/visit", status_code=204, tags=["Operations"])
async def visit(request: Request) -> Response:
    """Сигнал страницы: просмотр или «вкладка ещё открыта». Ответ — всегда 204.

    sendBeacon отправляет text/plain, поэтому тело разбирается вручную.
    """
    counter = getattr(request.app.state, "visits", None)
    if counter is not None:
        try:
            try:
                body = json.loads((await request.body())[:256] or b"{}")
            except ValueError:
                body = None
            view = isinstance(body, dict) and body.get("view") is True
            await counter.record(source_address(request), request.headers.get("user-agent", ""), view)
        except Exception:  # noqa: BLE001 — счётчик не влияет на ответ странице
            pass
    return Response(status_code=204, headers=NO_STORE)


@router.get("/api/v1/admin/visitors", tags=["Admin"])
async def visitors(request: Request, _: Annotated[Principal, Depends(READ)],
                   period: Annotated[Literal["week", "month"], Query(alias="range")] = "week"
                   ) -> Response:
    db = request.app.state.db
    today = moscow_day(request.app.state.clock())
    start = today - timedelta(days=RANGES[period] - 1)
    online = await db.admin_fetch_one(ONLINE, {"seconds": ONLINE_WINDOW.total_seconds()})
    totals: dict[date, list[int]] = {start + timedelta(days=offset): [0, 0]
                                     for offset in range(RANGES[period])}
    for row in await db.admin_fetch_all(DAYS, {"start": start}):
        if row["day"] in totals:
            totals[row["day"]][0] += row["visitors"]
            totals[row["day"]][1] += row["views"]
    days = [{"day": day.isoformat(), "visitors": value[0], "views": value[1]}
            for day, value in sorted(totals.items())]
    return JSONResponse({
        "range": period,
        "online": online["online"] if online else 0,
        "onlineWindowSeconds": int(ONLINE_WINDOW.total_seconds()),
        "today": days[-1],
        "days": days,
    }, headers=NO_STORE)
