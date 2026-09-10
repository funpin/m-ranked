"""Современный и байтово замороженный CSV-экспорт."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ..cached import current_revision
from ..errors import ApiProblem, BadRequest
from ..exporting import ExportQuota, temporary_csv, write_csv, write_csv_async
from ..sql import exports as sql

router = APIRouter(tags=["Export"])

PUBLIC_HEADERS = (
    "platform", "institution", "publication_id", "published_at", "observed_at",
    "views", "reactions", "comments", "shares", "quality", "dataset_revision",
)
LEGACY_HEADERS = {
    ("snapshots", "telegram"): ("канал", "id_публикации", "опубликовано", "измерено",
        "возраст_часов", "реакций_всего", "изменение_реакций", "просмотры",
        "изменение_просмотров", "комментарии", "изменение_комментариев", "реакции_json"),
    ("snapshots", "generic"): ("площадка", "вуз", "аккаунт", "id_публикации",
        "опубликовано", "измерено", "возраст_часов", "просмотры", "реакции",
        "комментарии", "репосты", "сырой_json"),
    ("posts", "telegram"): ("канал", "id_публикации", "опубликовано", "полная_история",
        "последнее_число_реакций", "последнее_число_просмотров",
        "последнее_число_комментариев", "максимальный_скачок", "возраст_скачка_часов"),
    ("posts", "generic"): ("площадка", "вуз", "аккаунт", "id_публикации",
        "опубликовано", "тип", "ссылка", "последние_просмотры", "последние_реакции",
        "последние_комментарии", "последние_репосты"),
}

def _instant(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _legacy_platform(values: list[str] | None) -> str:
    value = values[-1] if values else "telegram"
    normalized = value.strip().casefold()
    normalized = {"tg": "telegram", "общий": "all"}.get(normalized, normalized)
    return normalized if normalized in ("all", "telegram", "vk", "max", "rutube") else "telegram"


def _legacy_cell(value: Any) -> str:
    return "" if value is None else str(value)


def _quota(request: Request, name: str, requests_per_minute: int) -> ExportQuota:
    attribute = f"{name}_export_quota"
    quota = getattr(request.app.state, attribute, None)
    if quota is None:
        quota = ExportQuota(requests_per_minute)
        setattr(request.app.state, attribute, quota)
    return quota


async def _cleanup(path: Path, quota: ExportQuota) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    quota.downloaded()


def _file(path: Path, filename: str, revision: int, quota: ExportQuota) -> FileResponse:
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=filename,
                        headers={"Cache-Control": "no-store", "X-Dataset-Revision": str(revision)},
                        background=BackgroundTask(_cleanup, path, quota))


@router.get("/api/v1/exports/publications.csv")
async def publications(request: Request, platform: str = Query("all")) -> Response:
    if platform not in ("all", "telegram", "vk", "max", "rutube"):
        raise BadRequest("неподдерживаемая платформа экспорта")
    quota = _quota(request, "public", 10)
    await quota.acquire()
    path = temporary_csv("mranked-public-export-")
    try:
        revision, committed_at = await current_revision(request.app.state.db)

        async def rows():
            async for row in request.app.state.db.stream(sql.PUBLICATIONS, {
                "platform": platform, "as_of": committed_at,
            }):
                yield (row["platform"], row["institution"], row["publication_id"],
                       _instant(row["published_at"]), _instant(row["observed_at"]),
                       row["views_count"], row["reactions_count"], row["comments_count"],
                       row["shares_count"], row["quality"], revision)

        await write_csv_async(path, PUBLIC_HEADERS, rows(), max_rows=100_000,
                              max_bytes=32*1024*1024, max_seconds=30)
        quota.generated()
        return _file(path, f"publications-{platform}.csv", revision, quota)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        quota.failed()
        raise


@router.get("/api/v1/legacy-exports/{kind}.csv")
async def legacy(request: Request, kind: str, platform: list[str] | None = Query(None)) -> Response:
    if kind not in ("posts", "snapshots"):
        raise ApiProblem(404, "Not Found", "Неизвестный вид legacy CSV")
    selected = _legacy_platform(platform)
    namespace = "telegram" if selected == "telegram" else "generic"
    quota = _quota(request, "legacy", 20)
    await quota.acquire()
    path = temporary_csv("mranked-legacy-export-")
    try:
        revision, _ = await current_revision(request.app.state.db)
        status = await request.app.state.db.fetch_one(sql.LEGACY_STATUS)
        if status and status["blocked_reason"]:
            raise ApiProblem(
                409, "Legacy export compatibility unavailable",
                "Exact legacy CSV cannot be produced from this published revision.",
                "urn:m-ranked:problem:legacy-export-unavailable",
                code=status["blocked_reason"],
            )
        write_csv(path, LEGACY_HEADERS[(kind, namespace)], (), max_rows=2_000_000,
                  max_bytes=512*1024*1024, max_seconds=300, transform=_legacy_cell)
        quota.generated()
        suffix = "" if selected == "telegram" else f"-{selected}"
        return _file(path, f"{kind}{suffix}.csv", revision, quota)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        quota.failed()
        raise
