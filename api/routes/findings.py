"""«Находки»: посты выше нормы своего аккаунта."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, params as normalize
from ..cached import serve
from ..db import Database
from ..errors import NotFound
from ..findings import (
    COMMENT_NORM_FLOOR, FINDING_MIN_COMMENTS, FINDING_MIN_INDEX, FINDING_MIN_INTERACTIONS,
    FINDING_MIN_SHARES, FINDINGS_PERIOD_DAYS, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE,
    NORM_WINDOW_DAYS, PAGE_CAP, SHARE_NORM_FLOOR, TOP_REACTIONS, VIEW_NORM_FLOOR,
)
from ..sql import findings as sql
from .statistics import _like_pattern, _page

router = APIRouter(tags=["Query"])

# Уровни аномалий меняют выдачу, поэтому ответ сбрасывается и по анализу.
FINDINGS_TAGS = frozenset({"publications", "catalog", "analysis"})


def findings_body(query: normalize.FindingsQuery, rows: list[dict[str, Any]],
                  institutions: list[dict[str, Any]], page_size: int, after_id: str | None,
                  revision: int, committed_at: Any, dimensions: str) -> dict[str, Any]:
    if query.institution is not None and not any(
            row["legacy_id"] == query.institution for row in institutions):
        raise NotFound("вуз не найден")
    hidden = rows[0]["hidden_anomalous"] if rows else 0
    posts = [row for row in rows if row["publication_id"] is not None]
    items: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    offset, has_more, next_cursor = 0, False, None
    if query.group == "institution":
        by_institution: dict[Any, dict[str, Any]] = {}
        for row in sorted(posts, key=lambda value: value["rank"]):
            group = by_institution.setdefault(row["institution_id"], {
                "institutionLegacyId": row["institution_legacy_id"],
                "institutionShortName": row["institution_short_name"],
                "institutionCanonicalName": row["institution_canonical_name"],
                "findingCount": row["institution_finding_count"], "items": [],
            })
            group["items"].append(dto.finding(row))
        groups = list(by_institution.values())
    else:
        visible, offset, has_more = _page(posts, after_id, page_size, "publication_id")
        items = [dto.finding(row) for row in visible]
        next_cursor = normalize.encode_scoped_cursor(
            str(visible[-1]["publication_id"]) if has_more and visible else None,
            revision, dimensions)
    return {
        "mode": query.mode, "institution": query.institution, "platform": query.platform,
        "period": query.period, "types": list(query.types), "sort": query.sort,
        "direction": query.direction, "group": query.group, "q": query.search,
        "anomalies": query.anomalies, "items": items, "groups": groups,
        "total": posts[0]["total"] if posts else 0, "hiddenAnomalous": hidden,
        "institutions": [dto.finding_institution(row) for row in institutions],
        "limit": page_size, "offset": offset, "hasMore": has_more, "nextCursor": next_cursor,
        "datasetRevision": revision, "asOf": committed_at.isoformat(),
    }


@router.get("/api/v1/findings", operation_id="getFindings")
async def findings(
    request: Request,
    mode: str | None = Query(None),
    institution: str | None = Query(None),
    platform: str | None = Query(None),
    period: str | None = Query(None),
    types: list[str] | None = Query(None),
    sort: str | None = Query(None),
    direction: str | None = Query(None),
    group: str | None = Query(None),
    q: str | None = Query(None),
    anomalies: str | None = Query(None),
    limit: int = Query(50),
    cursor: str | None = Query(None),
) -> Response:
    query = normalize.findings_query(mode, institution, platform, period, types, sort,
                                     direction, group, q, anomalies)
    page_size = normalize.limit(limit, default=50, maximum=50)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        dimensions = f"findings:{query.dimensions}:{page_size}"
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        username_search = query.search[1:] if query.search.startswith("@") else query.search
        rows = await db.fetch_all(sql.FINDINGS, {
            "as_of": committed_at, "period_days": FINDINGS_PERIOD_DAYS[query.period],
            "norm_days": NORM_WINDOW_DAYS, "platform": query.platform,
            "institution_legacy_id": query.institution, "types": list(query.types),
            "q": query.search, "search_pattern": _like_pattern(query.search),
            "username_pattern": _like_pattern(username_search),
            "min_sample": MIN_NORM_SAMPLE, "interaction_floor": INTERACTION_NORM_FLOOR,
            "view_floor": VIEW_NORM_FLOOR, "mode": query.mode,
            "min_index": FINDING_MIN_INDEX, "min_interactions": FINDING_MIN_INTERACTIONS,
            "sort": query.sort, "direction": query.direction,
            "exclude_anomalies": query.anomalies == "exclude", "group": query.group,
            "cap": PAGE_CAP, "comment_floor": COMMENT_NORM_FLOOR, "share_floor": SHARE_NORM_FLOOR,
            "min_comments": FINDING_MIN_COMMENTS, "min_shares": FINDING_MIN_SHARES,
            "top_reactions": TOP_REACTIONS,
        })
        institutions = await db.fetch_all(sql.INSTITUTIONS, {})
        institutions.sort(key=lambda row: (row["short_name"] or row["canonical_name"]).lower())
        return findings_body(query, rows, institutions, page_size, after_id, revision,
                             committed_at, dimensions)

    return await serve(request, "findings", {
        "dimensions": query.dimensions, "limit": page_size, "cursor": cursor or "",
    }, FINDINGS_TAGS, build, pinned_revision=normalize.cursor_revision(cursor))
