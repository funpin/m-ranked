"""Проверки живости, готовности и свежести сбора."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..config import Settings
from ..db import Database

router = APIRouter(prefix="/api/v1/health", tags=["Operations"])
logger = logging.getLogger(__name__)

PLATFORMS = ("telegram", "vk", "max", "rutube")
EXPECTED_CONTRACT = "live-read-2026-09-13-text-fingerprint"

NO_STORE = {"Cache-Control": "no-store"}

CONTRACT_SQL = "SELECT contract_id FROM ops_and_admin.schema_contract"
SOURCE_SCHEMA_SQL = """
SELECT to_regclass('catalog.visible_platform_account') IS NOT NULL
   AND to_regclass('ingest.visible_publication') IS NOT NULL
   AND to_regclass('analytics.usable_publication_snapshot') IS NOT NULL
   -- Миграция 0025: без этих таблиц админка не сможет ни открыть сессию,
   -- ни удержать одноразовость кода, поэтому узел не готов принимать нагрузку.
   AND to_regclass('ops_and_admin.admin_session') IS NOT NULL
   AND to_regclass('ops_and_admin.admin_totp_use') IS NOT NULL
   AND to_regclass('ops_and_admin.admin_login_failure') IS NOT NULL AS ready
"""
REVISION_SQL = "SELECT id, committed_at FROM analytics.latest_dataset_revision()"
SNAPSHOT_SQL = "SELECT ops_and_admin.public_health_snapshot() AS snapshot"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@router.get("/live")
async def liveness() -> Response:
    return JSONResponse({"status": "UP"}, headers=NO_STORE)


@router.get("/ready")
async def readiness(request: Request) -> Response:
    db: Database = request.app.state.db
    try:
        if await db.fetch_value("SELECT 1") != 1:
            return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)
        if await db.fetch_value(CONTRACT_SQL) != EXPECTED_CONTRACT:
            return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)
        if not await db.fetch_value(SOURCE_SCHEMA_SQL):
            return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)
        revision = await db.fetch_one(REVISION_SQL)
    except Exception:
        logger.warning("проба готовности не прошла", exc_info=True)
        return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)
    if revision is None or int(revision["id"]) <= 0:
        return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)
    return JSONResponse({"status": "UP", "datasetRevision": int(revision["id"])}, headers=NO_STORE)


@router.get("/legacy")
async def legacy(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    try:
        snapshot = await _snapshot(request.app.state.db)
    except Exception:
        logger.warning("операционный снимок недоступен", exc_info=True)
        return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)

    checkpoints = _mapping(snapshot.get("checkpoints"))
    cycles = _cycles(snapshot, checkpoints)
    configured = _configured(settings)
    fresh = _fresh(snapshot, cycles["telegram"], "telegram", settings.freshness_seconds)

    telegram_connected = (
        settings.health_mode == "telegram_web"
        and fresh
        and checkpoints.get("telegram_web_last_success_at") is not None
        and checkpoints.get("telegram_web_last_error") is None
    )
    body = {
        "status": "ok",
        "data_source": settings.health_mode,
        "source_connected": fresh,
        "collector_fresh": fresh,
        "telegram_connected": telegram_connected,
        "channels": snapshot.get("channels"),
        "last_poll": checkpoints.get("last_poll"),
        "next_poll": checkpoints.get("next_poll"),
        "poll_cycle": cycles["telegram"],
        "integrations": {
            "telegram": {
                "configured": configured["telegram"],
                "mode": settings.health_mode,
                "comments_last_success_at": checkpoints.get("telegram_web_last_success_at"),
                "comments_last_error": checkpoints.get("telegram_web_last_error"),
            },
            "vk": {"configured": configured["vk"], "poll_cycle": cycles["vk"]},
            "max": {
                "configured": configured["max"],
                "mode": "user_session",
                "phone_configured": _flag(request, "HEALTH_MAX_PHONE_CONFIGURED"),
                "session_exists": _flag(request, "HEALTH_MAX_SESSION_EXISTS"),
                "poll_cycle": cycles["max"],
            },
            "rutube": {
                "configured": configured["rutube"],
                "mode": "official_public_api",
                "poll_cycle": cycles["rutube"],
            },
        },
    }
    return JSONResponse(body, headers=NO_STORE)


@router.get("/freshness")
async def freshness(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    try:
        snapshot = await _snapshot(request.app.state.db)
    except Exception:
        logger.warning("операционный снимок недоступен", exc_info=True)
        return JSONResponse({"status": "DOWN"}, status_code=503, headers=NO_STORE)

    checkpoints = _mapping(snapshot.get("checkpoints"))
    cycles = _cycles(snapshot, checkpoints)
    configured = _configured(settings)

    healthy = True
    platforms: dict[str, Any] = {}
    for platform in PLATFORMS:
        is_fresh = _fresh(snapshot, cycles[platform], platform, settings.freshness_seconds)
        if configured[platform] and not is_fresh:
            healthy = False
        platforms[platform] = {
            "configured": configured[platform],
            "fresh": is_fresh,
            "completedAt": cycles[platform].get("completed_at"),
        }

    raw = int(snapshot.get("rawRevision") or 0)
    published = int(snapshot.get("publishedRevision") or 0)
    healthy = healthy and published > 0
    body = {
        "status": "UP" if healthy else "DOWN",
        "asOf": snapshot.get("asOf"),
        "datasetRevision": published,
        "rawRevision": raw,
        "publishedRevision": published,
        # Публиковать больше нечего: данные видны сразу после фиксации ревизии,
        # поэтому отставание структурно равно нулю.
        "revisionLag": max(0, raw - published),
        "publishedGenerationAgeSeconds": snapshot.get("publishedGenerationAgeSeconds"),
        "freshnessThresholdSeconds": settings.freshness_seconds,
        "platforms": platforms,
        "outbox": snapshot.get("outbox"),
        "storage": snapshot.get("storage"),
    }
    return JSONResponse(body, status_code=200 if healthy else 503, headers=NO_STORE)


async def _snapshot(db: Database) -> dict[str, Any]:
    return _mapping(await db.fetch_value(SNAPSHOT_SQL))


def _flag(request: Request, name: str) -> bool:
    import os
    return os.environ.get(name, "false").lower() in ("1", "true", "yes")


def _configured(settings: Settings) -> dict[str, bool]:
    import os
    def integration(name: str) -> bool:
        return os.environ.get(f"INTEGRATION_{name.upper()}", "unknown") == "configured"
    return {
        "telegram": settings.health_mode in ("public_web", "telegram_web") or integration("telegram"),
        "vk": integration("vk"),
        "max": integration("max"),
        "rutube": integration("rutube"),
    }


def _cycles(snapshot: dict[str, Any], checkpoints: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Цикл опроса берётся из последнего прогона целевого коллектора.

    Если целевых прогонов ещё нет, значения читаются из импортированных
    контрольных точек прежней системы — у telegram они лежат под другим
    префиксом, чем у остальных платформ.
    """
    runs = _mapping(snapshot.get("runs"))
    result: dict[str, dict[str, Any]] = {}
    for platform in PLATFORMS:
        run = _mapping(runs.get(platform))
        target = run.get("started_at") is not None
        prefix = "poll_last_" if platform == "telegram" else f"{platform}_poll_last_"

        def pick(field: str, checkpoint: str | None = None) -> Any:
            return run.get(field) if target else checkpoints.get(prefix + (checkpoint or field))

        cycle: dict[str, Any] = {
            "completed_at": pick("completed_at"),
            "duration_seconds": pick("duration_seconds"),
            "error_count": pick("error_count"),
        }
        if platform == "telegram":
            cycle["started_at"] = pick("started_at")
            cycle["channel_count"] = pick("account_count", "channel_count")
        else:
            cycle["account_count"] = pick("account_count")
        result[platform] = cycle
    return result


def _fresh(snapshot: dict[str, Any], cycle: dict[str, Any], platform: str, threshold: int) -> bool:
    run = _mapping(_mapping(snapshot.get("runs")).get(platform))
    if run.get("started_at") is not None and run.get("status") != "succeeded":
        return False
    try:
        now = _instant(snapshot["asOf"])
        completed = _instant(cycle["completed_at"])
    except (KeyError, TypeError, ValueError):
        return False
    age = (now - completed).total_seconds()
    return 0 <= age <= threshold


def _instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
