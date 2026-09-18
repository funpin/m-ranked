"""Публичные запросы: ревизия, обзор, сущности, история."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from .. import params as normalize
from ..cached import serve
from ..db import Database
from .. import dto
from ..dto import overview_account, overview_row
from ..errors import BadRequest, NotFound
from ..params import encode_cursor
from ..providers import public_representation_version, status as provider_status, warning as provider_warning
from ..sql.overview import OVERVIEW
from ..sql import details

router = APIRouter(prefix="/api/v1", tags=["Query"])

NO_STORE = {"Cache-Control": "no-store"}
REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"

# Обзор и списки затрагиваются записью публикаций и справочника.
OVERVIEW_TAGS = frozenset({"publications", "overview"})
DETAIL_TAGS = frozenset({"publications", "catalog"})


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _legacy_type(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise BadRequest(f"legacyType должен быть одним из {', '.join(allowed)}")
    return value


def _entity_params(value: str, legacy_type: str) -> dict[str, Any]:
    entity_uuid, legacy_id = normalize.entity_id(value)
    return {"entity_uuid": entity_uuid, "legacy_id": legacy_id, "legacy_type": legacy_type}


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


@router.get("/institutions/{legacyId}")
async def institution(
    legacyId: str,
    request: Request,
    platform: str = Query("all"),
    period: str = Query("1d"),
) -> Response:
    resolved_platform = normalize.platform(platform)
    resolved_period = normalize.period(period)
    entity_uuid, legacy_id = normalize.entity_id(legacyId)
    if entity_uuid is not None:
        raise BadRequest("для учреждения требуется положительный legacy id")

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        row = await request.app.state.db.fetch_one(details.INSTITUTION, {
            "legacy_id": legacy_id, "platform": resolved_platform,
            "period": resolved_period, "revision": revision, "as_of": committed_at,
        })
        if row is None:
            raise NotFound(f"учреждение {legacy_id} не найдено")
        return dto.institution(row, resolved_platform, resolved_period, revision)

    return await serve(request, "institution", {
        "legacyId": legacy_id, "platform": resolved_platform, "period": resolved_period,
    }, DETAIL_TAGS, build)


def _pinned_revision(value: int | None) -> int | None:
    """Клиент просит собрать страницу по одному снимку данных.

    Экран детали складывается из нескольких запросов, а ревизия на проде
    меняется каждые две секунды. Первый запрос сообщает свою ревизию,
    остальные её закрепляют — иначе страница собирается из разных снимков.
    """
    if value is None:
        return None
    if value < 1:
        raise BadRequest("ревизия набора данных должна быть положительной")
    return value


@router.get("/accounts/{legacyId}")
async def account(
    legacyId: str,
    request: Request,
    legacyType: str = Query("platform_accounts"),
    revision: int | None = Query(None),
) -> Response:
    resolved_type = _legacy_type(legacyType, ("channels", "platform_accounts"))
    identity = _entity_params(legacyId, resolved_type)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        row = await db.fetch_one(details.ACCOUNT, {**identity, "as_of": committed_at})
        if row is None:
            raise NotFound(f"аккаунт {legacyId} не найден")
        stats_row = await db.fetch_one(details.ACCOUNT_STATS, {
            "account_id": row["account_id"], "institution_id": row["institution_id"],
            "platform": row["platform"], "days": request.app.state.settings.retention_days,
            "as_of": committed_at,
        })
        daily = await db.fetch_all(details.ACCOUNT_DAILY, {
            "account_id": row["account_id"], "as_of": committed_at,
        }) if stats_row else []
        stats = dto.account_stats(stats_row, revision, committed_at,
                                  dto.account_daily(list(daily))) if stats_row else None
        return dto.account(row, revision, stats)

    return await serve(request, "account", {
        "id": legacyId.lower(), "legacyType": resolved_type,
    }, DETAIL_TAGS, build, _pinned_revision(revision))


@router.get("/publications/{legacyId}")
async def publication(
    legacyId: str,
    request: Request,
    legacyType: str = Query("posts"),
    revision: int | None = Query(None),
) -> Response:
    resolved_type = _legacy_type(legacyType, ("posts", "platform_posts"))
    identity = _entity_params(legacyId, resolved_type)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        row = await request.app.state.db.fetch_one(
            details.PUBLICATION, {**identity, "as_of": committed_at})
        if row is None:
            raise NotFound(f"публикация {legacyId} не найдена")
        return dto.publication(row, revision)

    return await serve(request, "publication", {
        "id": legacyId.lower(), "legacyType": resolved_type,
    }, DETAIL_TAGS, build, _pinned_revision(revision))


@router.get("/institutions/{legacyId}/accounts")
async def institution_accounts(
    legacyId: str,
    request: Request,
    platform: str = Query("all"),
    limit: int = Query(50),
    cursor: str | None = Query(None),
    revision: int | None = Query(None),
) -> Response:
    resolved_platform = normalize.platform(platform)
    page_size = normalize.limit(limit)
    entity_uuid, legacy_id = normalize.entity_id(legacyId)
    if entity_uuid is not None:
        raise BadRequest("для учреждения требуется положительный legacy id")
    dimensions = f"institution-accounts:{legacy_id}:{resolved_platform}"

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        exists = await db.fetch_one(details.INSTITUTION, {
            "legacy_id": legacy_id, "platform": resolved_platform, "period": "1d",
            "revision": revision, "as_of": committed_at,
        })
        if exists is None:
            raise NotFound(f"учреждение {legacy_id} не найдено")
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        sql_params = {
            "legacy_id": legacy_id, "platform": resolved_platform,
            "after_id": after_id, "fetch_limit": page_size + 1, "as_of": committed_at,
        }
        rows = await db.fetch_all(details.INSTITUTION_ACCOUNTS, sql_params)
        total = await db.fetch_value(details.INSTITUTION_ACCOUNT_COUNT, sql_params)
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        next_cursor = normalize.encode_scoped_cursor(
            str(visible[-1]["id"]) if has_more and visible else None, revision, dimensions)
        return {
            "items": [dto.account(row, revision) for row in visible],
            "nextCursor": next_cursor, "legacyTotalAccountCount": total or 0,
            "datasetRevision": revision, "asOf": _iso(committed_at),
        }

    return await serve(request, "institution-accounts", {
        "legacyId": legacy_id, "platform": resolved_platform,
        "limit": page_size, "cursor": cursor or "",
    }, DETAIL_TAGS, build, _pinned_revision(revision))


@router.get("/accounts/{legacyId}/publications")
async def account_publications(
    legacyId: str,
    request: Request,
    legacyType: str = Query("platform_accounts"),
    limit: int = Query(50),
    cursor: str | None = Query(None),
    revision: int | None = Query(None),
    day: date | None = Query(None),
) -> Response:
    resolved_type = _legacy_type(legacyType, ("channels", "platform_accounts"))
    page_size = normalize.limit(limit)
    identity = _entity_params(legacyId, resolved_type)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        account_row = await db.fetch_one(details.ACCOUNT, {**identity, "as_of": committed_at})
        if account_row is None:
            raise NotFound(f"аккаунт {legacyId} не найден")
        today = committed_at.astimezone(ZoneInfo("Europe/Moscow")).date()
        if day is not None and not today - timedelta(days=6) <= day <= today:
            raise BadRequest("day должен входить в последние 7 московских суток")
        dimensions = f"account-publications:{account_row['account_id']}:{day.isoformat() if day else '-'}"
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        publication_type = "posts" if account_row["platform"] == "telegram" else "platform_posts"
        rows = await db.fetch_all(details.ACCOUNT_PUBLICATIONS, {
            "account_id": account_row["account_id"], "publication_legacy_type": publication_type,
            "after_id": after_id, "fetch_limit": page_size + 1,
            "days": request.app.state.settings.retention_days, "as_of": committed_at,
            "growth_day": day,
        })
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        next_cursor = normalize.encode_scoped_cursor(
            str(visible[-1]["publication_id"]) if has_more and visible else None,
            revision, dimensions)
        return {"items": [dto.publication_list_item(row) for row in visible],
                "nextCursor": next_cursor, "datasetRevision": revision,
                "asOf": _iso(committed_at)}

    return await serve(request, "account-publications", {
        "id": legacyId.lower(), "legacyType": resolved_type,
        "limit": page_size, "cursor": cursor or "", "day": day.isoformat() if day else "",
    }, DETAIL_TAGS, build, _pinned_revision(revision))


@router.get("/publications/{legacyId}/history")
async def publication_history(
    legacyId: str,
    request: Request,
    legacyType: str = Query("posts"),
    limit: int = Query(200),
    cursor: str | None = Query(None),
) -> Response:
    resolved_type = _legacy_type(legacyType, ("posts", "platform_posts"))
    requested_size = normalize.limit(limit, default=200, maximum=3000)
    # Схема ответа ограничивает items двумя тысячами, хотя параметр исторически
    # допускает 3000. Больший запрос остаётся валидным и получает продолжение.
    page_size = min(requested_size, 2000)
    identity = _entity_params(legacyId, resolved_type)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        publication_row = await db.fetch_one(
            details.PUBLICATION, {**identity, "as_of": committed_at})
        if publication_row is None:
            raise NotFound(f"публикация {legacyId} не найдена")
        publication_id = publication_row["publication_id"]
        canonical_type = publication_row["entity_type"]
        dimensions = f"publication-history:{publication_id}"
        cursor_id = normalize.scoped_cursor(cursor, revision, dimensions)
        after_snapshot_id = None
        if cursor_id is not None:
            parsed = uuid.UUID(cursor_id)
            if parsed.int <= 0 or parsed.int > (1 << 63) - 1:
                raise BadRequest("курсор истории повреждён")
            after_snapshot_id = parsed.int
        published_month = publication_row["published_at"].date().replace(day=1)
        rows = await db.fetch_all(details.HISTORY, {
            "publication_id": publication_id, "published_month": published_month,
            "as_of": committed_at, "after_snapshot_id": after_snapshot_id,
            "fetch_limit": page_size + 1,
        })
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        cursor_uuid = str(uuid.UUID(int=int(visible[-1]["snapshot_id"]))) if has_more and visible else None
        neighbours = await db.fetch_one(details.NEIGHBOURS, {
            "publication_id": publication_id, "legacy_type": canonical_type,
        })
        return {
            "publication": dto.publication(publication_row, revision),
            "items": [dto.history_snapshot(row) for row in visible],
            "previousLegacyId": neighbours["previous"] if neighbours else None,
            "nextLegacyId": neighbours["next"] if neighbours else None,
            "archivedText": None,
            "nextCursor": normalize.encode_scoped_cursor(cursor_uuid, revision, dimensions),
            "datasetRevision": revision, "asOf": _iso(committed_at),
        }

    return await serve(request, "publication-history", {
        "id": legacyId.lower(), "legacyType": resolved_type,
        "limit": requested_size, "cursor": cursor or "",
    }, DETAIL_TAGS, build)
