"""Рейтинг активности."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, params as normalize
from ..cached import serve
from ..db import Database
from ..sql import rating as sql

router = APIRouter(tags=["Query"])

RATING_TAGS = frozenset({"publications", "catalog", "rating"})


@router.get("/api/v1/rating")
async def rating(
    request: Request,
    platform: str = Query("telegram"),
    period: str | None = Query(None),
    channel_sort: str = Query("engagement"),
    channel_direction: str = Query("desc"),
    post_sort: str = Query("view_share"),
    post_direction: str = Query("desc"),
    entityLimit: int = Query(200),
    entityCursor: str | None = Query(None),
) -> Response:
    query = normalize.rating_query(platform, period, channel_sort, channel_direction,
                                   post_sort, post_direction)
    page_size = normalize.limit(entityLimit)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        dimensions = "rating:" + query.dimensions
        after_id = normalize.scoped_cursor(entityCursor, revision, dimensions)
        values = {
            "as_of": committed_at, "period": query.period, "platform": query.platform,
            "channel_sort": query.channel_sort, "channel_direction": query.channel_direction,
            "post_sort": query.post_sort, "post_direction": query.post_direction,
            "after_entity_id": after_id, "fetch_limit": page_size + 1,
        }
        entity_rows = await db.fetch_all(sql.ENTITIES, values)
        publication_rows = await db.fetch_all(sql.PUBLICATIONS, values)
        truncated = len(entity_rows) > page_size
        visible = entity_rows[:page_size]
        next_cursor = normalize.encode_scoped_cursor(
            str(visible[-1]["entity_id"]) if truncated and visible else None,
            revision, dimensions)
        return {
            "platform": query.platform, "period": query.period,
            "entityType": "channels" if query.platform == "telegram" else "institutions",
            "publicationLegacyType": "posts" if query.platform == "telegram" else "platform_posts",
            "channelSort": query.channel_sort, "channelDirection": query.channel_direction,
            "postSort": query.post_sort, "postDirection": query.post_direction,
            "entities": [dto.rating_entity(row) for row in visible],
            "publications": [dto.rating_publication(row) for row in publication_rows],
            "entityLimit": page_size, "entitiesTruncated": truncated,
            "nextEntityCursor": next_cursor,
            "entityOffset": int(visible[0]["page_position"] - 1) if visible else 0,
            "datasetRevision": revision, "asOf": committed_at.isoformat(),
        }

    return await serve(request, "rating", {
        "platform": query.platform, "period": query.period,
        "channelSort": query.channel_sort, "channelDirection": query.channel_direction,
        "postSort": query.post_sort, "postDirection": query.post_direction,
        "entityLimit": page_size, "entityCursor": entityCursor or "",
    }, RATING_TAGS, build)
