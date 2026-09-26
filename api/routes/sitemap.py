"""Карта сайта: сводка (аккаунты, вузы, число файлов постов) и файлы постов."""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from .. import dto
from ..cached import serve
from ..db import Database
from ..sql import sitemap as sql

router = APIRouter(tags=["Query"])

SITEMAP_TAGS = frozenset({"publications", "catalog"})


@router.get("/api/v1/sitemap")
async def sitemap_summary(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        summary = await db.fetch_one(sql.SUMMARY, {})
        accounts = await db.fetch_all(sql.ACCOUNTS, {})
        institutions = await db.fetch_all(sql.INSTITUTIONS, {})
        total = int(summary["publications"]) if summary else 0
        return {
            "publicationPages": math.ceil(total / sql.PUBLICATIONS_PER_PAGE),
            "publications": total,
            "accounts": [{"accountId": str(row["account_id"]), "lastModified": dto.iso(row["last_modified"])}
                         for row in accounts],
            "institutions": [{"legacyId": int(row["legacy_id"])} for row in institutions],
            "datasetRevision": revision, "asOf": dto.iso(committed_at),
        }

    return await serve(request, "sitemap-summary", {}, SITEMAP_TAGS, build)


@router.get("/api/v1/sitemap/publications/{page}")
async def sitemap_publications(request: Request, page: int = Path(ge=0, le=1000)) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        rows = await db.fetch_all(sql.PUBLICATIONS, {
            "offset": page * sql.PUBLICATIONS_PER_PAGE, "limit": sql.PUBLICATIONS_PER_PAGE})
        return {
            "page": page,
            "items": [{"publicationId": str(row["publication_id"]), "lastModified": dto.iso(row["last_modified"])}
                      for row in rows],
            "datasetRevision": revision, "asOf": dto.iso(committed_at),
        }

    return await serve(request, "sitemap-publications", {"page": page}, SITEMAP_TAGS, build)
