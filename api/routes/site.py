"""Главная страница: сводные цифры проекта."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import dto
from ..cached import serve
from ..db import Database
from ..sql import site as sql

router = APIRouter(tags=["Query"])

# Строку пересчитывает обслуживание раз в сутки; приход новых данных её не
# меняет, поэтому тег не совпадает ни с одним событием сброса кэша, и ответ
# живёт до срока кэша, а не до следующего пакета замеров.
SITE_TAGS = frozenset({"site-summary"})


@router.get("/api/v1/site/summary")
async def site_summary(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        row = await db.fetch_one(sql.SUMMARY, {})
        if row is None:
            # Обслуживание ещё не посчитало сводку: главная покажет раздел без цифр.
            return {"available": False, "institutions": None, "accounts": None, "accountsByPlatform": {},
                    "publications": None, "snapshots": None, "computedAt": None}
        return {
            "available": True,
            "institutions": row["institutions"], "accounts": row["accounts"],
            "accountsByPlatform": dict(row["accounts_by_platform"] or {}),
            "publications": row["publications"], "snapshots": row["snapshots"],
            "computedAt": dto.iso(row["computed_at"]),
        }

    return await serve(request, "site-summary", {}, SITE_TAGS, build)
