"""Публичный анализ аномалий и append-only административные решения."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from psycopg import errors as pg_errors

from .. import dto, params as normalize
from ..cached import serve
from ..errors import ApiProblem, BadRequest, NotFound
from ..security import Principal, require_csrf, require_roles
from ..sql import analysis as sql

router = APIRouter()

ANALYSIS_TAGS = frozenset({"analysis"})
DISCLAIMER = ("Сигнал аномальной динамики носит информационный характер и сам по себе "
              "не доказывает искусственное происхождение активности или действия университета.")
METHODOLOGY_VERSION = "anomaly-dynamics-v2"
# Названия уровней — те же, что пишет модуль анализа (ADR-006); API его не
# импортирует, совпадение проверяет тест.
LEVEL_LABELS = {
    0: "нет признаков",
    1: "слабый сигнал",
    2: "выраженная аномалия",
    3: "признаки искусственной активности",
}
LEVEL_SYMBOLS = {0: "○", 1: "◔", 2: "◑", 3: "●"}
NOT_ANALYZED = "ещё не проанализирован"
NOT_ANALYZED_SYMBOL = "·"


class ManualSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["views", "reactions", "comments", "shares"]
    severity: Literal["low", "medium", "high"]
    explanationCode: str
    suspiciousStartAt: datetime
    suspiciousEndAt: datetime
    evidence: dict[str, str | int | float | bool | None]

    @field_validator("explanationCode")
    @classmethod
    def explanation(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]{1,80}", value):
            raise ValueError("invalid explanation code")
        return value

    @model_validator(mode="after")
    def interval_and_evidence(self) -> "ManualSignal":
        if (self.suspiciousStartAt.tzinfo is None or self.suspiciousEndAt.tzinfo is None
                or self.suspiciousEndAt <= self.suspiciousStartAt
                or len(self.evidence) > 32
                or len(json.dumps(self.evidence, ensure_ascii=False).encode()) > 8000):
            raise ValueError("invalid anomaly interval or evidence")
        return self


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["explained", "unresolved", "data_error", "dismissed"]
    privateComment: str | None = None

    @field_validator("privateComment")
    @classmethod
    def comment(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("comment is too long")
        return value


def _uuid(value: str, name: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise BadRequest(f"{name} должен быть UUID") from error
    if str(parsed) != value.lower():
        raise BadRequest(f"{name} должен быть каноническим UUID")
    return parsed


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _command_error(error: Exception) -> ApiProblem:
    if isinstance(error, pg_errors.NoDataFound):
        return NotFound("Сигнал аномалии не найден")
    if isinstance(error, (pg_errors.UniqueViolation, pg_errors.ForeignKeyViolation)):
        return ApiProblem(409, "Conflict", "Конфликт идемпотентности или версии",
                          "urn:m-ranked:problem:conflict")
    if isinstance(error, (pg_errors.CheckViolation, pg_errors.InvalidParameterValue,
                          pg_errors.RaiseException)):
        return BadRequest("Команда анализа отклонена")
    return ApiProblem(500, "Internal Server Error", "Команда анализа не выполнена")


@router.get("/api/v1/publications/{legacyId}/anomaly-analysis", tags=["Query"])
async def publication_analysis(legacyId: str, request: Request, legacyType: str = Query("posts")) -> Response:
    if legacyType not in ("posts", "platform_posts"):
        raise BadRequest("неподдерживаемый legacyType")
    entity_uuid, legacy_id = normalize.entity_id(legacyId)

    async def build(dataset_revision: int, committed_at: Any) -> dict[str, Any]:
        resolved = await request.app.state.db.fetch_one(sql.RESOLVE, {
            "entity_uuid": entity_uuid, "legacy_id": legacy_id, "legacy_type": legacyType,
        })
        if resolved is None:
            raise NotFound(f"публикация {legacyId} не найдена")
        publication_id = resolved["id"]
        row = await request.app.state.db.fetch_one(sql.STATE, {"publication": publication_id})
        return analysis_body(str(publication_id), dataset_revision, row)

    # Ответ не зависит от загрузки замеров: теги «publications» здесь нет, иначе
    # каждое уведомление о новой порции данных помечало бы анализ несвежим.
    # Свежесть держит TTL записи — вывод отстаёт от анализа меньше минуты.
    return await serve(request, "publication-analysis", {
        "id": legacyId.lower(), "legacyType": legacyType,
    }, ANALYSIS_TAGS, build)


def analysis_body(publication_id: str, dataset_revision: int, row: dict[str, Any] | None) -> dict[str, Any]:
    """Тело ответа. Пост без анализа — не ошибка, а «ещё не проанализирован»."""
    analyzed = row is not None and row["analyzed_at"] is not None
    level = int(row["level"]) if analyzed else None
    return {
        "publicationId": publication_id, "datasetRevision": dataset_revision,
        "status": "analyzed" if analyzed else "pending",
        "level": level,
        "levelLabel": LEVEL_LABELS[level] if level is not None else NOT_ANALYZED,
        "levelSymbol": LEVEL_SYMBOLS[level] if level is not None else NOT_ANALYZED_SYMBOL,
        "signals": list(row["signals"]) if analyzed else [],
        "quality": dict(row["quality"]) if analyzed and row["quality"] else None,
        "analyzedAt": dto.iso(row["analyzed_at"]) if analyzed else None,
        "lagSeconds": row["lag_seconds"] if analyzed else None,
        "normVersion": row["norm_version_id"] if analyzed else None,
        "detectorVersions": dict(row["detector_versions"] or {}) if analyzed else {},
        "reviewStatus": row["review_status"] if row is not None else "unreviewed",
        "methodologyVersion": METHODOLOGY_VERSION, "disclaimer": DISCLAIMER,
    }


@router.post("/api/v1/admin/publications/{publicationId}/anomaly-signals", tags=["Admin"])
async def create_manual_signal(
    publicationId: str, body: ManualSignal, request: Request,
    idempotency: Annotated[str, Header(alias="Idempotency-Key")],
    correlation: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    user: Annotated[Principal, Depends(require_roles("ADMIN"))] = None,
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> Response:
    publication = _uuid(publicationId, "publicationId")
    idempotency_id = _uuid(idempotency, "Idempotency-Key")
    correlation_id = _uuid(correlation, "X-Correlation-Id") if correlation else uuid.uuid4()
    values = {
        "publication": publication, "metric": body.metric, "severity": body.severity,
        "explanation": body.explanationCode, "start_at": body.suspiciousStartAt,
        "end_at": body.suspiciousEndAt,
        "evidence": json.dumps(body.evidence, ensure_ascii=False, separators=(",", ":")),
        "actor": user.username, "correlation": correlation_id,
        "idempotency": idempotency_id,
        "digest": _digest({"publicationId": publication, **body.model_dump()}),
    }
    try:
        row = await request.app.state.db.admin_fetch_one(sql.CREATE_MANUAL, values)
    except Exception as error:
        raise _command_error(error) from error
    return JSONResponse(row["result"], headers={"Cache-Control": "no-store",
                                                "X-Correlation-Id": str(correlation_id)})


@router.post("/api/v1/admin/anomaly-signals/{findingId}/reviews", tags=["Admin"])
async def append_review(
    findingId: str, body: Review, request: Request,
    idempotency: Annotated[str, Header(alias="Idempotency-Key")],
    correlation: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
    user: Annotated[Principal, Depends(require_roles("ADMIN"))] = None,
    _csrf: Annotated[None, Depends(require_csrf)] = None,
) -> Response:
    finding = _uuid(findingId, "findingId")
    idempotency_id = _uuid(idempotency, "Idempotency-Key")
    correlation_id = _uuid(correlation, "X-Correlation-Id") if correlation else uuid.uuid4()
    values = {
        "finding": finding, "decision": body.decision, "comment": body.privateComment,
        "actor": user.username, "correlation": correlation_id,
        "idempotency": idempotency_id,
        "digest": _digest({"findingId": finding, **body.model_dump()}),
    }
    try:
        row = await request.app.state.db.admin_fetch_one(sql.APPEND_REVIEW, values)
    except Exception as error:
        raise _command_error(error) from error
    return JSONResponse(row["result"], headers={"Cache-Control": "no-store",
                                                "X-Correlation-Id": str(correlation_id)})
