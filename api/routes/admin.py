"""Приватный каталог и операционные административные маршруты."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg import errors as pg_errors

from ..errors import ApiProblem, BadRequest, NotFound
from .. import dto
from ..identity_receipts import persist_admin_envelope
from ..security import Principal, issue_csrf, require_csrf, require_roles
from ..sql import admin as sql

router = APIRouter(tags=["Admin"])
READ = require_roles("VIEWER", "EDITOR", "ADMIN")
WRITE = require_roles("EDITOR", "ADMIN")
ADMIN = require_roles("ADMIN")
PLATFORMS = frozenset({"telegram", "vk", "max", "rutube"})


class InstitutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=1000)
    shortName: str | None = Field(None, max_length=1000)


class InstitutionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=1000)
    shortName: str = Field(min_length=1, max_length=1000)
    expectedRowVersion: int = Field(ge=0)


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    institutionId: uuid.UUID
    expectedRowVersion: int | None = Field(None, ge=0)
    platform: Literal["telegram", "vk", "max", "rutube"]
    reference: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(None, max_length=1000)
    url: str | None = Field(None, max_length=2048)


class AccountCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRowVersion: int = Field(ge=0)
    nativeId: str | None = Field(None, max_length=200)


class LegacyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=200, pattern=r"^/manage/")
    fields: dict[str, str]

    @field_validator("fields")
    @classmethod
    def fields_are_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20 or any(len(key) > 100 or len(item) > 131072
                                  for key, item in value.items()):
            raise ValueError("invalid legacy fields")
        return value


def _json(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)


def _text(value: str | None, maximum: int, message: str) -> str:
    if value is None or not value.strip():
        raise BadRequest(message)
    result = value.strip()
    if len(result) > maximum or any(ord(character) < 32 for character in result):
        raise BadRequest("Недопустимое текстовое поле")
    return result


def _nullable(value: str | None, maximum: int) -> str | None:
    if value is None or not value.strip():
        return None
    return _text(value, maximum, "Поле не заполнено")


def _web_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username:
        raise BadRequest("Аккаунт должен использовать HTTP(S)-ссылку без учётных данных")


def _account_body(platform: str, reference: str, title: str | None,
                  supplied_url: str | None, institution: uuid.UUID | None) -> dict[str, Any]:
    original = _text(reference, 2048, "Укажите аккаунт или ссылку")
    key = original
    url = _nullable(supplied_url, 2048)
    if platform == "telegram":
        key = re.sub(r"/+$", "", original)
        key = re.sub(r"^(?:https?://)?t\.me/", "", key, flags=re.IGNORECASE)
        key = re.sub(r"^@+", "", key)
        parts = [part for part in key.split("/") if part]
        index = 1 if parts and parts[0].lower() == "s" else 0
        key = parts[index] if len(parts) > index else ""
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", key):
            raise BadRequest("Некорректное имя Telegram-канала")
        url = "https://t.me/" + key
    elif platform == "vk":
        key = re.sub(r"/+$", "", original)
        key = re.sub(r"^https?://(?:m\.)?vk\.(?:com|ru)/", "", key, flags=re.IGNORECASE)
        key = key.split("?", 1)[0].split("/", 1)[0].lstrip("@")
        if not re.fullmatch(r"(?:club|public)?[A-Za-zА-Яа-яЁё0-9_.-]{2,64}", key):
            raise BadRequest("Не удалось определить сообщество ВКонтакте")
        url = url or "https://vk.com/" + key
    else:
        parsed = urlsplit(original if "://" in original else "https://placeholder/" + original)
        if "://" in original:
            _web_url(original)
            url = url or original
        path = parsed.path.rstrip("/")
        key = path.rsplit("/", 1)[-1].lstrip("@")
        if not key or len(key) > 200:
            raise BadRequest("Не удалось определить аккаунт")
    if url:
        _web_url(url)
    return {
        "institutionId": str(institution) if institution else None,
        "platform": platform, "externalKey": key.lower() if platform == "telegram" else key,
        "username": key, "title": _nullable(title, 1000), "url": url,
        "accessMode": {"telegram": "public_web", "vk": "official_api",
                       "max": "user_session", "rutube": "public_api"}[platform],
    }


def _command_problem(outcome: str) -> ApiProblem:
    if outcome == "not_found":
        return NotFound("Ресурс каталога не найден")
    if outcome in ("version_conflict", "idempotency_conflict"):
        return ApiProblem(409, "Conflict", "Версия или ключ команды конфликтует",
                          "urn:m-ranked:problem:optimistic-lock")
    return ApiProblem(500, "Internal Server Error", "Неожиданный результат команды каталога")


async def _catalog_command(request: Request, action: str, target: uuid.UUID | None,
                           expected: int | None, body: dict[str, Any], actor: str,
                           correlation: uuid.UUID, connection: Any | None = None) -> dict[str, Any]:
    values = {"action": action, "target": target, "expected": expected,
              "body": _json(body), "actor": actor[:200], "correlation": correlation}

    async def execute(active: Any) -> dict[str, Any]:
        original = (await (await active.execute(sql.CATALOG_ENVELOPE, values)).fetchone())["original"]
        try:
            persist_admin_envelope(original)
        except (OSError, ValueError) as error:
            raise ApiProblem(503, "Service Unavailable",
                             "Не удалось надёжно сохранить исходную команду") from error
        row = await (await active.execute(sql.CATALOG_COMMAND, values)).fetchone()
        result = row["result"]
        if result.get("outcome") != "succeeded":
            raise _command_problem(result.get("outcome", ""))
        state = result.get("state") or {}
        return {
            "outcome": "succeeded", "targetId": result["targetId"],
            "legacyId": result["legacyId"], "datasetRevision": result["datasetRevision"],
            "rowVersion": state.get("row_version"), "correlationId": str(correlation),
        }

    try:
        if connection is not None:
            return await execute(connection)
        async with request.app.state.db.admin() as active:
            async with active.transaction():
                return await execute(active)
    except ApiProblem:
        raise
    except (pg_errors.InvalidParameterValue, pg_errors.CheckViolation) as error:
        raise BadRequest("Команда каталога отклонена") from error
    except pg_errors.Error as error:
        raise ApiProblem(503, "Service Unavailable", "Административная база недоступна") from error


def _no_store(body: Any, status: int = 200, correlation: uuid.UUID | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if correlation:
        headers["X-Correlation-Id"] = str(correlation)
    return JSONResponse(body, status_code=status, headers=headers)


def _csrf_response(request: Request, body: dict[str, Any]) -> JSONResponse:
    token = issue_csrf(request.app.state.auth)
    body["token"] = token
    response = _no_store(body)
    response.set_cookie("XSRF-TOKEN", token, path="/api/v1/admin", httponly=False,
                        samesite="lax")
    return response


@router.get("/api/v1/admin/csrf")
async def csrf(request: Request, _: Annotated[Principal, Depends(READ)]) -> Response:
    return _csrf_response(request, {"headerName": "X-XSRF-TOKEN", "parameterName": "_csrf"})


@router.get("/api/v1/admin/catalog/session")
async def catalog_session(request: Request, user: Annotated[Principal, Depends(READ)]) -> Response:
    return _csrf_response(request, {"headerName": "X-XSRF-TOKEN",
                                    "canEdit": bool(user.roles & {"EDITOR", "ADMIN"}),
                                    "canDelete": "ADMIN" in user.roles})


@router.get("/api/v1/admin/catalog/institutions")
async def catalog_institutions(request: Request, _: Annotated[Principal, Depends(READ)],
                               after: int = Query(0, ge=0),
                               limit: int = Query(100, ge=1, le=200)) -> Response:
    rows = await request.app.state.db.admin_fetch_all(sql.CATALOG, {"after": after, "limit": limit})
    items = [row["item"] for row in rows]
    return _no_store({"items": items, "nextAfter": items[-1]["legacyId"]
                      if len(items) == limit else None})


@router.get("/api/v1/admin/catalog/institutions/{id}/accounts")
async def catalog_accounts(id: uuid.UUID, request: Request,
                           _: Annotated[Principal, Depends(READ)],
                           after: int = Query(0, ge=0),
                           limit: int = Query(100, ge=1, le=200)) -> Response:
    rows = await request.app.state.db.admin_fetch_all(
        sql.CATALOG_ACCOUNTS, {"institution": id, "after": after, "limit": limit})
    items = [row["item"] for row in rows]
    return _no_store({"items": items, "nextAfter": items[-1]["legacyId"]
                      if len(items) == limit else None})


@router.get("/api/v1/admin/catalog/status")
async def catalog_status(request: Request, _: Annotated[Principal, Depends(READ)]) -> Response:
    row = await request.app.state.db.admin_fetch_one(sql.CATALOG_STATUS)
    try:
        usage = shutil.disk_usage(Path.cwd())
        total, free = usage.total, usage.free
    except OSError:
        total = free = None
    statuses = {platform: os.environ.get(f"MRANKED_INTEGRATIONS_{platform.upper()}", "unknown")
                for platform in PLATFORMS}
    if any(value not in ("configured", "missing", "unknown") for value in statuses.values()):
        raise ApiProblem(500, "Internal Server Error", "Некорректный статус интеграции")
    details = {
        "telegram": "Публичный HTML-источник",
        "vk": "VK_ACCESS_TOKEN · просмотры, лайки, комментарии, репосты",
        "max": f"Пользовательская сессия · chat_id определён у {row['max_native_ids']} из {row['max_accounts']} аккаунтов",
        "rutube": "Официальные публичные API · токен не требуется · просмотры, лайки, комментарии",
    }
    return _no_store({
        "channelCount": row["channels"], "platformCount": row["accounts"],
        "institutionCount": row["institutions"], "mRating": row["rating"],
        "integrations": [{"platform": platform, "status": statuses[platform],
                          "detail": details[platform]}
                         for platform in ("telegram", "vk", "max", "rutube")],
        "storage": {"diskTotalBytes": total, "diskFreeBytes": free, "projectBytes": None,
                    "databaseBytes": row["database_bytes"]},
    })


@router.post("/api/v1/admin/catalog/institutions")
async def create_institution(body: InstitutionCreate, request: Request,
                             correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                             user: Annotated[Principal, Depends(WRITE)],
                             _: Annotated[None, Depends(require_csrf)]) -> Response:
    name = _text(body.name, 1000, "Укажите название вуза")
    short_name = _nullable(body.shortName, 1000) or name
    return _no_store(await _catalog_command(request, "institution.create", None, None,
                                            {"name": name, "shortName": short_name},
                                            user.username, correlation))


@router.put("/api/v1/admin/catalog/institutions/{id}")
async def update_institution(id: uuid.UUID, body: InstitutionUpdate, request: Request,
                             correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                             user: Annotated[Principal, Depends(WRITE)],
                             _: Annotated[None, Depends(require_csrf)]) -> Response:
    command = {"name": _text(body.name, 1000, "Укажите название вуза"),
               "shortName": _text(body.shortName, 1000, "Укажите сокращение")}
    return _no_store(await _catalog_command(request, "institution.update", id,
                                            body.expectedRowVersion, command,
                                            user.username, correlation))


@router.delete("/api/v1/admin/catalog/institutions/{id}")
async def delete_institution(id: uuid.UUID, request: Request,
                             correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                             user: Annotated[Principal, Depends(ADMIN)],
                             _: Annotated[None, Depends(require_csrf)],
                             expectedRowVersion: int = Query(ge=0)) -> Response:
    return _no_store(await _catalog_command(request, "institution.delete", id,
                                            expectedRowVersion, {}, user.username, correlation))


@router.post("/api/v1/admin/catalog/accounts")
async def upsert_account(body: AccountRequest, request: Request,
                         correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                         user: Annotated[Principal, Depends(WRITE)],
                         _: Annotated[None, Depends(require_csrf)]) -> Response:
    command = _account_body(body.platform, body.reference, body.title, body.url,
                            body.institutionId)
    if body.expectedRowVersion is None:
        command["expectedAccountVersions"] = {}
    return _no_store(await _catalog_command(request, "account.upsert", None,
                                            body.expectedRowVersion, command,
                                            user.username, correlation))


async def _account_command(id: uuid.UUID, body: AccountCommand, request: Request,
                           correlation: uuid.UUID, user: Principal, action: str) -> Response:
    native = _nullable(body.nativeId, 200)
    result = await _catalog_command(request, f"account.{action}", id,
                                    body.expectedRowVersion, {"nativeId": native or ""},
                                    user.username, correlation)
    return _no_store(result)


@router.post("/api/v1/admin/catalog/accounts/{id}/enable")
async def enable_account(id: uuid.UUID, body: AccountCommand, request: Request,
                         correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                         user: Annotated[Principal, Depends(WRITE)],
                         _: Annotated[None, Depends(require_csrf)]) -> Response:
    return await _account_command(id, body, request, correlation, user, "enable")


@router.post("/api/v1/admin/catalog/accounts/{id}/disable")
async def disable_account(id: uuid.UUID, body: AccountCommand, request: Request,
                          correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                          user: Annotated[Principal, Depends(WRITE)],
                          _: Annotated[None, Depends(require_csrf)]) -> Response:
    return await _account_command(id, body, request, correlation, user, "disable")


@router.post("/api/v1/admin/catalog/accounts/{id}/native-id")
async def native_id(id: uuid.UUID, body: AccountCommand, request: Request,
                    correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                    user: Annotated[Principal, Depends(WRITE)],
                    _: Annotated[None, Depends(require_csrf)]) -> Response:
    return await _account_command(id, body, request, correlation, user, "native_id")


@router.delete("/api/v1/admin/catalog/accounts/{id}")
async def delete_account(id: uuid.UUID, request: Request,
                         correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                         user: Annotated[Principal, Depends(ADMIN)],
                         _: Annotated[None, Depends(require_csrf)],
                         expectedRowVersion: int = Query(ge=0)) -> Response:
    body = AccountCommand(expectedRowVersion=expectedRowVersion)
    return await _account_command(id, body, request, correlation, user, "delete")


async def _alias(connection: Any, entity_type: str, legacy_id: int) -> uuid.UUID:
    row = await (await connection.execute(sql.RESOLVE_ALIAS, {
        "type": entity_type, "legacy_id": legacy_id,
    })).fetchone()
    if row is None:
        raise NotFound("Ресурс каталога не найден")
    return row["target_uuid"]


async def _version(connection: Any, entity_type: str, entity_id: uuid.UUID,
                   fields: dict[str, str]) -> int:
    supplied = fields.get("expected_row_version")
    if supplied is not None:
        try:
            result = int(supplied)
        except ValueError as error:
            raise BadRequest("Некорректная версия строки") from error
        if result < 0:
            raise BadRequest("Некорректная версия строки")
        return result
    table = ("catalog.visible_institution" if entity_type == "institutions"
             else "catalog.visible_platform_account")
    row = await (await connection.execute(sql.ROW_VERSION.format(table=table),
                                          {"id": entity_id})).fetchone()
    if row is None:
        raise NotFound("Ресурс каталога не найден")
    return row["row_version"]


def _derived_correlation(correlation: uuid.UUID, index: int) -> uuid.UUID:
    digest = hashlib.md5(f"{correlation}:{index}".encode(), usedforsecurity=False).digest()
    return uuid.UUID(bytes=digest, version=3)


def _required(fields: dict[str, str], name: str) -> str:
    if name not in fields:
        raise BadRequest(f"Не заполнено поле {name}")
    return fields[name]


async def _legacy_execute(body: LegacyCommand, request: Request, user: Principal,
                          correlation: uuid.UUID) -> str:
    path, fields = body.path, body.fields
    if path == "/manage/m-rating/update":
        from ..official_rating import refresh
        try:
            await refresh(request, user.username, correlation)
            return "/manage?m_rating_status=updated"
        except ApiProblem:
            raise
        except Exception:
            return "/manage?m_rating_status=error"
    async with request.app.state.db.admin() as connection:
        async with connection.transaction():
            if path == "/manage/institutions":
                name = _text(_required(fields, "name"), 1000, "Укажите название вуза")
                short = _nullable(fields.get("short_name"), 1000) or name
                result = await _catalog_command(request, "institution.create", None, None,
                                                {"name": name, "shortName": short},
                                                user.username, correlation, connection)
                return f"/manage?platform_status=institution-added&institution_id={result['legacyId']}"
            if path == "/manage/channels":
                command = _account_body("telegram", _required(fields, "channel"), None, None, None)
                await _catalog_command(request, "channel.upsert", None, None, command,
                                       user.username, correlation, connection)
                return "/manage?channel_status=added"
            if path == "/manage/platform-accounts":
                platform = _required(fields, "platform")
                if platform not in ("vk", "max", "rutube"):
                    raise BadRequest("Telegram-каналы добавляются через основную форму мониторинга")
                try:
                    legacy_id = int(_required(fields, "institution_id"))
                except ValueError as error:
                    raise BadRequest("Некорректный вуз") from error
                institution = await _alias(connection, "institutions", legacy_id)
                command = _account_body(platform, _required(fields, "reference"),
                                        fields.get("title"), fields.get("url"), institution)
                await _catalog_command(request, "account.upsert", None, None, command,
                                       user.username, correlation, connection)
                return "/manage?platform_status=account-added"

            institution_match = re.fullmatch(r"/manage/institutions/([1-9][0-9]*)(/accounts)?", path)
            if institution_match:
                legacy_id = int(institution_match.group(1))
                institution = await _alias(connection, "institutions", legacy_id)
                if institution_match.group(2):
                    references = {
                        "telegram": fields.get("telegram", ""), "vk": fields.get("vk", ""),
                        "max": fields.get("max_account", ""), "rutube": fields.get("rutube", ""),
                    }
                    selected = [(platform, value) for platform, value in references.items()
                                if value and value.strip()]
                    if not selected:
                        raise BadRequest("Укажите хотя бы один аккаунт")
                    expected_institution = (int(fields["expected_row_version"])
                                            if "expected_row_version" in fields else None)
                    expected_accounts: dict[str, int] | None = None
                    if "expected_account_versions" in fields:
                        try:
                            decoded = json.loads(fields["expected_account_versions"])
                            if (not isinstance(decoded, dict) or len(decoded) > 2000
                                    or any(not isinstance(value, int) or value < 0
                                           or str(uuid.UUID(key)) != key.lower()
                                           for key, value in decoded.items())):
                                raise ValueError
                            expected_accounts = decoded
                        except (ValueError, TypeError) as error:
                            raise BadRequest("Некорректные версии аккаунтов") from error
                    for index, (platform, reference) in enumerate(selected):
                        command = _account_body(platform, reference, None, None, institution)
                        if expected_institution is not None:
                            command["expectedInstitutionVersion"] = expected_institution
                        if expected_accounts is not None:
                            command["expectedAccountVersions"] = expected_accounts
                        await _catalog_command(request, "account.upsert", None, None, command,
                                               user.username,
                                               _derived_correlation(correlation, index), connection)
                    return f"/manage?platform_status=accounts-updated&institution_id={legacy_id}"
                version = await _version(connection, "institutions", institution, fields)
                command = {"name": _text(_required(fields, "name"), 1000,
                                         "Укажите название вуза"),
                           "shortName": _text(_required(fields, "short_name"), 1000,
                                              "Укажите сокращение")}
                await _catalog_command(request, "institution.update", institution, version,
                                       command, user.username, correlation, connection)
                return f"/manage?platform_status=institution-updated&institution_id={legacy_id}"

            account_match = re.fullmatch(
                r"/manage/(channels|platform-accounts)/([1-9][0-9]*)/(enable|disable|delete|native-id)",
                path)
            if account_match:
                entity_type = account_match.group(1).replace("-", "_")
                legacy_id = int(account_match.group(2))
                operation = account_match.group(3)
                channel = entity_type == "channels"
                if channel and operation == "native-id":
                    raise NotFound("Маршрут не найден")
                account = await _alias(connection, entity_type, legacy_id)
                parent_row = await (await connection.execute(sql.PARENT_LEGACY_ID,
                                                              {"id": account})).fetchone()
                if parent_row is None:
                    raise NotFound("Аккаунт не найден")
                parent = parent_row["legacy_id"]
                version = await _version(connection, entity_type, account, fields)
                native = _required(fields, "native_id").strip() if operation == "native-id" else ""
                action = ("channel.delete" if channel and operation == "delete"
                          else "account." + operation.replace("-", "_"))
                await _catalog_command(request, action, account, version, {"nativeId": native},
                                       user.username, correlation, connection)
                if channel:
                    return "/manage?channel_status=deleted" if operation == "delete" else "/manage"
                status = {"enable": "account-enabled", "disable": "account-disabled",
                          "delete": "account-deleted", "native-id": "native-id-updated"}[operation]
                return f"/manage?platform_status={status}&institution_id={parent}"
    raise NotFound("Маршрут не найден")


@router.post("/api/v1/admin/catalog/legacy-command")
async def legacy_command(body: LegacyCommand, request: Request,
                         correlation: Annotated[uuid.UUID, Header(alias="X-Correlation-Id")],
                         user: Annotated[Principal, Depends(WRITE)],
                         _: Annotated[None, Depends(require_csrf)]) -> Response:
    if body.path.endswith("/delete") and "ADMIN" not in user.roles:
        raise ApiProblem(403, "Forbidden", "Для удаления требуется роль ADMIN",
                         "urn:m-ranked:problem:forbidden")
    location = await _legacy_execute(body, request, user, correlation)
    return _no_store({"location": location})


class SetEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    expectedRowVersion: int = Field(ge=0)


class CreateExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["all", "telegram", "vk", "max", "rutube"]


def _job(row: dict[str, Any]) -> dict[str, Any]:
    return {"jobId": str(row["id"]), "kind": "collection", "platform": row["platform"],
            "scheduledAt": dto.iso(row["scheduled_at"]), "startedAt": dto.iso(row["started_at"]),
            "completedAt": dto.iso(row["completed_at"]), "status": row["status"],
            "accountCount": row["account_count"], "errorCount": row["error_count"],
            "correlationId": str(row["correlation_id"])}


def _platform_account(row: dict[str, Any]) -> dict[str, Any]:
    return {"accountId": str(row["id"]), "platform": row["platform"],
            "enabled": row["enabled"], "rowVersion": row["row_version"],
            "updatedAt": dto.iso(row["updated_at"])}


@router.get("/api/v1/admin/jobs")
async def jobs(request: Request, _: Annotated[Principal, Depends(READ)],
               platform: Literal["telegram", "vk", "max", "rutube"] | None = None,
               status: Literal["pending", "running", "succeeded", "partial", "failed",
                               "skipped", "cancelled"] | None = None,
               limit: int = Query(50, ge=1, le=100)) -> Response:
    rows = await request.app.state.db.admin_fetch_all(
        sql.JOBS, {"platform": platform or "", "status": status or "", "limit": limit})
    return _no_store({"items": [_job(row) for row in rows]})


@router.get("/api/v1/admin/jobs/{jobId}")
async def job(jobId: uuid.UUID, request: Request, _: Annotated[Principal, Depends(READ)],
              accountResultLimit: int = Query(100, ge=1, le=200)) -> Response:
    async with request.app.state.db.admin() as connection:
        row = await (await connection.execute(sql.JOB, {"job": jobId})).fetchone()
        if row is None:
            raise NotFound("Задание сбора не найдено")
        fetched = await (await connection.execute(
            sql.ACCOUNT_RESULTS, {"job": jobId, "limit": accountResultLimit+1})).fetchall()
    visible = fetched[:accountResultLimit]
    results = [{"resultId": item["id"], "platformAccountId": str(item["platform_account_id"]),
                "startedAt": dto.iso(item["started_at"]),
                "completedAt": dto.iso(item["completed_at"]), "status": item["status"],
                "discoveredCount": item["discovered_count"],
                "snapshotCount": item["snapshot_count"],
                "sanitizedErrorCode": item["sanitized_error_code"]} for item in visible]
    return _no_store({"job": _job(row), "accountResults": results,
                      "accountResultsTruncated": len(fetched) > accountResultLimit})


@router.get("/api/v1/admin/platform-accounts/{accountId}")
async def platform_account(accountId: uuid.UUID, request: Request,
                           _: Annotated[Principal, Depends(READ)]) -> Response:
    row = await request.app.state.db.admin_fetch_one(sql.PLATFORM_ACCOUNT, {"account": accountId})
    if row is None:
        raise NotFound("Аккаунт платформы не найден")
    return _no_store(_platform_account(row))


@router.put("/api/v1/admin/platform-accounts/{accountId}/enabled")
async def set_platform_account_enabled(
    accountId: uuid.UUID, body: SetEnabled, request: Request,
    user: Annotated[Principal, Depends(WRITE)],
    _: Annotated[None, Depends(require_csrf)],
    correlation: Annotated[uuid.UUID | None, Header(alias="X-Correlation-Id")] = None,
) -> Response:
    correlation = correlation or uuid.uuid4()
    outcome: str
    account: dict[str, Any] | None
    revision: int | None = None
    async with request.app.state.db.admin() as connection:
        async with connection.transaction():
            account = await (await connection.execute(
                sql.LOCK_ACCOUNT, {"account": accountId})).fetchone()
            if account is None:
                outcome = "not_found"
                before = after = None
            else:
                before = {"enabled": account["enabled"], "rowVersion": account["row_version"]}
                if account["enabled"] == body.enabled:
                    outcome = "idempotent"
                    after = before
                elif account["row_version"] != body.expectedRowVersion:
                    outcome = "version_conflict"
                    after = before
                else:
                    account = await (await connection.execute(sql.UPDATE_ACCOUNT, {
                        "account": accountId, "enabled": body.enabled,
                        "expected": body.expectedRowVersion,
                    })).fetchone()
                    revision_row = await (await connection.execute(
                        sql.INSERT_REVISION, {"correlation": correlation})).fetchone()
                    revision = revision_row["id"]
                    await connection.execute(sql.QUEUE_PROJECTION, {"revision": revision})
                    await connection.execute(sql.QUEUE_ENABLED, {
                        "revision": revision, "account": accountId,
                        "tag": f"platform-account:{accountId}", "enabled": account["enabled"],
                        "row_version": account["row_version"],
                    })
                    after = {"enabled": account["enabled"], "rowVersion": account["row_version"]}
                    outcome = "updated"
            await connection.execute(sql.AUDIT_ENABLED, {
                "actor": user.username[:200], "account": accountId, "correlation": correlation,
                "before": _json(before) if before is not None else None,
                "after": _json(after) if after is not None else None,
                "outcome": "succeeded" if outcome == "updated" else outcome,
            })
    if outcome == "not_found":
        raise NotFound("Аккаунт платформы не найден")
    if outcome == "version_conflict":
        raise ApiProblem(409, "Conflict", "Версия аккаунта изменилась",
                         "urn:m-ranked:problem:optimistic-lock")
    assert account is not None
    return _no_store({"account": _platform_account(account), "changed": outcome == "updated",
                      "datasetRevision": revision, "correlationId": str(correlation),
                      "outcome": outcome}, correlation=correlation)


@router.post("/api/v1/admin/exports")
async def create_export(body: CreateExport, request: Request,
                        user: Annotated[Principal, Depends(WRITE)],
                        _: Annotated[None, Depends(require_csrf)]) -> Response:
    job = await request.app.state.export_jobs.create(user.username, body.platform)
    response = _no_store(job.view(), status=202)
    response.headers["Location"] = f"/api/v1/admin/exports/{job.id}"
    return response


@router.get("/api/v1/admin/exports/{id}")
async def export_status(id: uuid.UUID, request: Request,
                        user: Annotated[Principal, Depends(WRITE)]) -> Response:
    job = await request.app.state.export_jobs.status(user.username, id)
    return _no_store(job.view())


@router.delete("/api/v1/admin/exports/{id}")
async def cancel_export(id: uuid.UUID, request: Request,
                        user: Annotated[Principal, Depends(WRITE)],
                        _: Annotated[None, Depends(require_csrf)]) -> Response:
    job = await request.app.state.export_jobs.cancel(user.username, id)
    return _no_store(job.view())


@router.get("/api/v1/admin/exports/{id}/download")
async def download_export(id: uuid.UUID, request: Request,
                          user: Annotated[Principal, Depends(WRITE)]) -> Response:
    job, path = await request.app.state.export_jobs.download(user.username, id)
    return FileResponse(path, media_type="text/csv; charset=utf-8",
                        filename=f"publications-{job.platform}.csv",
                        headers={"Cache-Control": "no-store",
                                 "X-Dataset-Revision": str(job.revision)})
