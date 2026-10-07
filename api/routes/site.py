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

# Сводные метрики обновляет обслуживание; покрытие читается из каталога.
# Изменения каталога сбрасывают ответ; поступление замеров не пересчитывает каталог.
SITE_TAGS = frozenset({"site-summary", "catalog", "rating"})


@router.get("/api/v1/site/summary")
async def site_summary(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        row = await db.fetch_one(sql.SUMMARY, {})
        coverage = await db.fetch_one(sql.COVERAGE, {})
        counts = {"trackedInstitutions": coverage["tracked_institutions"],
                  "ratingInstitutions": coverage["rating_institutions"]}
        if row is None:
            # Обслуживание ещё не посчитало сводку: главная покажет раздел без цифр.
            return {**counts, "available": False, "institutions": None, "accounts": None, "accountsByPlatform": {},
                    "publications": None, "snapshots": None, "computedAt": None}
        return {
            **counts,
            "available": True,
            "institutions": row["institutions"], "accounts": row["accounts"],
            "accountsByPlatform": dict(row["accounts_by_platform"] or {}),
            "publications": row["publications"], "snapshots": row["snapshots"],
            "computedAt": dto.iso(row["computed_at"]),
        }

    return await serve(request, "site-summary", {}, SITE_TAGS, build)
