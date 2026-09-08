"""Публичные запросы: ревизия, обзор, сущности, история."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from .. import params as normalize
from ..cached import serve
from ..db import Database
from ..dto import overview_account, overview_row
from ..params import encode_cursor
from ..providers import public_representation_version, status as provider_status, warning as provider_warning
from ..sql.overview import OVERVIEW

router = APIRouter(prefix="/api/v1", tags=["Query"])

NO_STORE = {"Cache-Control": "no-store"}
REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"

# Обзор и списки затрагиваются записью публикаций и справочника.
OVERVIEW_TAGS = frozenset({"publications", "overview"})


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


@router.get("/revision")
async def revision(request: Request) -> JSONResponse:
    """Читается из базы на каждый запрос и никогда не кэшируется."""
    db: Database = request.app.state.db
    row = await db.fetch_one(REVISION_SQL)
    return JSONResponse(
        {
            "datasetRevision": int(row["id"]) if row else 0,
            "asOf": _iso(row["committed_at"]) if row else None,
            "representationVersion": public_representation_version(),
        },
        headers=NO_STORE,
    )


@router.get("/overview")
async def overview(
    request: Request,
    platform: str = Query("all"),
    period: str = Query("1d"),
    q: str = Query(""),
    sort: str = Query("median_reactions"),
    direction: str | None = Query(None),
    limit: int = Query(50),
    cursor: str | None = Query(None),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
) -> Response:
    query = normalize.overview_query(platform, period, q, sort, direction)
    page_size = normalize.limit(limit)
    after_id = normalize.cursor(cursor)

    # Статус развёртывания — часть представления: он меняется без новой
    # ревизии базы, поэтому входит и в ключ кэша, и в валидатор.
    integration_status = provider_status(query.platform) if query.platform != "all" else "unknown"
    integration_warning = provider_warning(query.platform) if query.platform != "all" else None

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        rows = await db.fetch_all(OVERVIEW, {
            "as_of": committed_at,
            "period": query.period,
            "platform": query.platform,
            "sort": query.sort,
            "direction": query.direction,
            "search": query.search,
            "after_id": after_id,
            # На одну карточку больше, чтобы узнать, есть ли следующая страница.
            "fetch_limit": page_size + 1,
        })

        cards: list[dict[str, Any]] = []
        accounts: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            entity = row["entity_id"]
            if entity not in accounts:
                accounts[entity] = []
                cards.append(row)
            if row["account_id"] is not None:
                accounts[entity].append(overview_account(row))

        has_more = len(cards) > page_size
        visible = cards[:page_size]
        next_cursor = encode_cursor(str(visible[-1]["entity_id"])) if has_more and visible else None

        return {
            "items": [overview_row(card, accounts[card["entity_id"]], revision) for card in visible],
            "nextCursor": next_cursor,
            "datasetRevision": revision,
            "asOf": _iso(committed_at),
            "integrationStatus": integration_status,
            "integrationWarning": integration_warning,
        }

    return await serve(request, "overview", {
        "platform": query.platform, "period": query.period, "q": query.search,
        "sort": query.sort, "direction": query.direction, "limit": page_size,
        "cursor": after_id or "", "integrationStatus": integration_status,
        "integrationWarning": integration_warning or "",
    }, OVERVIEW_TAGS, build)
