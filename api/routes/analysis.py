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

ANALYSIS_TAGS = frozenset({"publications", "analysis"})
DISCLAIMER = ("Сигнал аномальной динамики носит информационный характер и сам по себе "
              "не доказывает искусственное происхождение активности или действия университета.")


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
async def publication_analysis(
    legacyId: str, request: Request, legacyType: str = Query("posts"),
    limit: int = Query(25), cursor: str | None = Query(None),
) -> Response:
    if legacyType not in ("posts", "platform_posts"):
        raise BadRequest("неподдерживаемый legacyType")
    page_size = normalize.limit(limit, default=25, maximum=100)
    entity_uuid, legacy_id = normalize.entity_id(legacyId)

    async def build(dataset_revision: int, committed_at: Any) -> dict[str, Any]:
        resolved = await request.app.state.db.fetch_one(sql.RESOLVE, {
            "entity_uuid": entity_uuid, "legacy_id": legacy_id, "legacy_type": legacyType,
        })
        if resolved is None:
            raise NotFound(f"публикация {legacyId} не найдена")
        publication_id = resolved["id"]
        head = await request.app.state.db.fetch_one(
            sql.REVISION, {"publication": publication_id})
        analysis_revision = int(head["analysis_revision"])
        dimensions = f"analysis:{publication_id}:{page_size}"
        after = normalize.scoped_cursor(cursor, analysis_revision, dimensions)
        row = await request.app.state.db.fetch_one(sql.LOAD, {
            "publication": publication_id, "after": after,
            "limit": page_size, "fetch_limit": page_size+1,
        })
        if row is None or int(row["analysis_revision"]) != analysis_revision:
            raise BadRequest("анализ изменился во время чтения")
        findings = row["findings"]
        for finding in findings:
            finding["suspicionScore"] = dto.number(finding["suspicionScore"])
        continuation = row["continuation_id"]
        return {
            "publicationId": str(publication_id), "datasetRevision": dataset_revision,
            "analysisRevision": analysis_revision,
            "sourceDatasetRevision": row["source_dataset_revision_id"],
            "analyzedAt": dto.iso(row["analyzed_at"]), "status": row["status"],
            "sourceRevisionAt": dto.iso(row["source_revision_at"]),
            "suspicionScore": dto.number(row["suspicion_score"]),
            "overallSeverity": row["overall_severity"],
            "manualAssessmentPresent": row["manual_present"],
            "affectedMetrics": row["affected_metrics"],
            "activeFindingCount": row["active_count"], "findings": findings,
            "nextCursor": normalize.encode_scoped_cursor(
                str(continuation) if continuation else None, analysis_revision, dimensions),
            "methodologyVersion": "anomaly-dynamics-v1", "disclaimer": DISCLAIMER,
        }

    return await serve(request, "publication-analysis", {
        "id": legacyId.lower(), "legacyType": legacyType, "limit": page_size,
        "cursor": cursor or "",
    }, ANALYSIS_TAGS, build)


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
