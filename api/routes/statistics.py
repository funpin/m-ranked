"""Detailed cumulative statistics for publications selected by publish date."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, params as normalize
from ..cached import serve
from ..db import Database
from ..errors import BadRequest
from ..sql import statistics as sql
from ..statistics_capabilities import INTERACTION_COMPONENTS, PLATFORM_METRIC_CAPABILITIES

router = APIRouter(tags=["Query"])

STATISTICS_TAGS = frozenset({"publications", "catalog", "statistics"})
PLATFORM_ORDER = ("telegram", "vk", "max", "rutube")


def _like_pattern(value: str) -> str:
    escaped = value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _capabilities(platform: str) -> dict[str, bool]:
    supported = PLATFORM_METRIC_CAPABILITIES[platform]
    return {metric: metric in supported for metric in INTERACTION_COMPONENTS}


def _page(rows: list[dict[str, Any]], after_id: str | None, limit: int,
          id_column: str) -> tuple[list[dict[str, Any]], int, bool]:
    offset = 0
    if after_id is not None:
        try:
            offset = next(index + 1 for index, row in enumerate(rows)
                          if str(row[id_column]) == after_id)
        except StopIteration as error:
            raise BadRequest("курсор больше не указывает на строку результата") from error
    visible = rows[offset:offset + limit]
    return visible, offset, offset + len(visible) < len(rows)


@router.get("/api/v1/statistics", operation_id="getStatistics")
async def statistics(
    request: Request,
    view: str = Query("publications"),
    platform: str = Query("all"),
    period: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    publication_sort: str = Query("erv"),
    publication_direction: str = Query("desc"),
    entity_sort: str = Query("erv"),
    entity_direction: str = Query("desc"),
    limit: int = Query(50),
    cursor: str | None = Query(None),
) -> Response:
    query = normalize.statistics_query(
        view, platform, period, q, publication_sort, publication_direction,
        entity_sort, entity_direction,
    )
    page_size = normalize.limit(limit, default=50, maximum=50)
    if query.platform == "all" and cursor:
        raise BadRequest("общий режим использует независимые списки и не принимает общий курсор")

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        dimensions = f"statistics:{query.dimensions}:{page_size}"
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        username_search = query.search[1:] if query.search.startswith("@") else query.search
        values = {
            "as_of": committed_at,
            "view": query.view,
            "platform": query.platform,
            "period": query.period,
            "q": query.search,
            "search_pattern": _like_pattern(query.search),
            "username_pattern": _like_pattern(username_search),
            "publication_sort": query.publication_sort,
            "publication_direction": query.publication_direction,
            "entity_sort": query.entity_sort,
            "entity_direction": query.entity_direction,
        }
        publication_rows: list[dict[str, Any]] = []
        entity_rows: list[dict[str, Any]] = []
        if query.view == "publications":
            publication_rows = await db.fetch_all(sql.PUBLICATIONS, values)
        else:
            entity_rows = await db.fetch_all(sql.ENTITIES, values)

        sections: list[dict[str, Any]] = []
        next_cursor = None
        offset = 0
        has_more = False
        if query.view == "publications":
            platforms = PLATFORM_ORDER if query.platform == "all" else (query.platform,)
            for section_platform in platforms:
                rows = [row for row in publication_rows if row["platform"] == section_platform]
                if query.platform == "all":
                    visible = rows
                    section_offset = 0
                    section_more = False
                    section_cursor = None
                else:
                    visible, section_offset, section_more = _page(
                        rows, after_id, page_size, "publication_id")
                    section_cursor = normalize.encode_scoped_cursor(
                        str(visible[-1]["publication_id"]) if section_more and visible else None,
                        revision, dimensions,
                    )
                    offset, has_more, next_cursor = section_offset, section_more, section_cursor
                sections.append({
                    "platform": section_platform,
                    "capabilities": _capabilities(section_platform),
                    "items": [dto.statistics_publication(row) for row in visible],
                    "total": len(rows),
                    "offset": section_offset,
                    "hasMore": section_more,
                    "nextCursor": section_cursor,
                })
        else:
            visible, offset, has_more = _page(entity_rows, after_id, page_size, "institution_id")
            next_cursor = normalize.encode_scoped_cursor(
                str(visible[-1]["institution_id"]) if has_more and visible else None,
                revision, dimensions,
            )
            entity_rows = visible

        return {
            "view": query.view,
            "platform": query.platform,
            "period": query.period,
            "q": query.search,
            "publicationSort": query.publication_sort,
            "publicationDirection": query.publication_direction,
            "entitySort": query.entity_sort,
            "entityDirection": query.entity_direction,
            "sections": sections,
            "entities": [dto.statistics_entity(row) for row in entity_rows],
            "limit": page_size,
            "offset": offset,
            "hasMore": has_more,
            "nextCursor": next_cursor,
            "datasetRevision": revision,
            "asOf": committed_at.isoformat(),
        }

    # Продолжение списка собирается по ревизии своего курсора: курсор входит в
    # ключ и сам её несёт. Первая страница собирается по опубликованной
    # ревизии — прежде её читали из базы на каждый запрос, даже на попадание.
    return await serve(request, "statistics", {
        "view": query.view,
        "platform": query.platform,
        "period": query.period,
        "q": query.search,
        "publicationSort": query.publication_sort,
        "publicationDirection": query.publication_direction,
        "entitySort": query.entity_sort,
        "entityDirection": query.entity_direction,
        "limit": page_size,
        "cursor": cursor or "",
    }, STATISTICS_TAGS, build, pinned_revision=normalize.cursor_revision(cursor))
