from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Iterable
from uuid import UUID

from .domain import Finding, Metric, MetricObservation, ObservationQuality, PublicationHistory


@dataclass(frozen=True, slots=True)
class SourceRevision:
    id: int
    committed_at: datetime


@dataclass(frozen=True, slots=True)
class Candidate:
    publication_id: UUID
    generation: int
    retry_count: int
    config_backfill: bool


class PostgresAnalysisRepository:
    """Narrow adapter over V31 SECURITY DEFINER functions."""

    def __init__(self, dsn: str, *, connection_factory=None) -> None:
        self._dsn = dsn
        self._factory = connection_factory or self._connect

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self._dsn, autocommit=True, row_factory=dict_row,
            options="-c timezone=UTC -c statement_timeout=20000 -c lock_timeout=5000",
        )

    def latest_source_revision(self) -> SourceRevision | None:
        with self._factory() as connection:
            row = connection.execute(
                "SELECT * FROM ops_and_admin.pin_latest_anomaly_source_revision()"
            ).fetchone()
        return None if row is None else SourceRevision(int(row["id"]), row["committed_at"])

    def seed_backfill(self, limit: int, manifest_hash: str) -> int:
        with self._factory() as connection:
            row = connection.execute(
                "SELECT ops_and_admin.seed_anomaly_backfill(%s,%s)", (limit, manifest_hash)
            ).fetchone()
        return int(_first(row))

    def operational_snapshot(self) -> dict[str, float]:
        with self._factory() as connection:
            row = connection.execute(
                "SELECT analytics.anomaly_operational_metrics()"
            ).fetchone()
        value = _first(row)
        if isinstance(value, str):
            value = json.loads(value)
        return {str(key): float(item) for key, item in value.items()}

    def claim(self, limit: int, lease_seconds: int, token: UUID) -> tuple[Candidate, ...]:
        with self._factory() as connection:
            rows = connection.execute(
                "SELECT * FROM ops_and_admin.claim_anomaly_candidates(%s,%s,%s)",
                (limit, lease_seconds, token),
            ).fetchall()
        return tuple(Candidate(row["publication_id"], int(row["dirty_generation"]),
                               int(row["retry_count"]), bool(row["config_backfill"])) for row in rows)

    def extract(
        self, publication_ids: tuple[UUID, ...], source_revision: int, max_points: int
    ) -> dict[UUID, PublicationHistory]:
        with self._factory() as connection:
            rows = connection.execute(
                "SELECT * FROM analytics.extract_publication_history_as_of(%s,%s,%s)",
                (list(publication_ids), source_revision, max_points),
            ).fetchall()
        grouped: dict[UUID, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["publication_id"], []).append(row)
        return {publication_id: _history(materialized, source_revision)
                for publication_id, materialized in grouped.items()}

    def unchanged(self, publication_id: UUID, input_hash: str, manifest_hash: str) -> bool:
        with self._factory() as connection:
            row = connection.execute(
                "SELECT analytics.anomaly_input_is_unchanged(%s,%s,%s)",
                (publication_id, input_hash, manifest_hash),
            ).fetchone()
        return bool(_first(row))

    def complete_noop(self, candidate: Candidate, token: UUID) -> bool:
        with self._factory() as connection:
            row = connection.execute(
                "SELECT ops_and_admin.complete_anomaly_noop(%s,%s,%s)",
                (candidate.publication_id, token, candidate.generation),
            ).fetchone()
        return bool(_first(row))

    def publish_success(
        self, candidate: Candidate, token: UUID, attempt_key: UUID, source: SourceRevision,
        input_hash: str, manifest_hash: str, preprocessor_version: str, aggregator_version: str,
        semantic_version: int, capability_version: int, started_at: datetime,
        status: str, score: float | None, severity: str | None, findings: Iterable[Finding],
    ) -> int:
        payload = json.dumps([_finding_payload(finding) for finding in findings],
                             sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._factory() as connection:
            row = connection.execute(
                """SELECT analytics.publish_anomaly_success(
                   %s::uuid,%s::uuid,%s::bigint,%s::uuid,%s::bigint,%s::text,%s::text,
                   %s::text,%s::text,%s::integer,%s::integer,%s::timestamptz,%s::text,
                   %s::numeric,%s::text,%s::jsonb)""",
                (candidate.publication_id, token, candidate.generation, attempt_key, source.id,
                 input_hash, manifest_hash, preprocessor_version, aggregator_version,
                 semantic_version, capability_version, started_at, status, score, severity, payload),
            ).fetchone()
        return int(_first(row))

    def publish_failure(
        self, candidate: Candidate, token: UUID, attempt_key: UUID, source: SourceRevision,
        manifest_hash: str, preprocessor_version: str, aggregator_version: str,
        semantic_version: int, capability_version: int, started_at: datetime,
        error_code: str, retry_seconds: int,
    ) -> int:
        with self._factory() as connection:
            row = connection.execute(
                """SELECT analytics.publish_anomaly_failure(
                   %s::uuid,%s::uuid,%s::bigint,%s::uuid,%s::bigint,%s::text,%s::text,
                   %s::text,%s::integer,%s::integer,%s::timestamptz,%s::text,%s::integer)""",
                (candidate.publication_id, token, candidate.generation, attempt_key, source.id,
                 manifest_hash, preprocessor_version, aggregator_version, semantic_version,
                 capability_version, started_at, error_code, retry_seconds),
            ).fetchone()
        return int(_first(row))


def _history(rows: list[dict[str, Any]], source_revision: int) -> PublicationHistory:
    first = rows[0]
    metric_rows: dict[Metric, list[MetricObservation]] = {metric: [] for metric in Metric}
    for row in rows:
        for metric in Metric:
            metric_rows[metric].append(MetricObservation(
                row["snapshot_id"], row["observed_at"], int(row["age_seconds"]),
                row[f"{metric.value}_count"], ObservationQuality(row[f"{metric.value}_quality"]),
                bool(row["synthetic"]), bool(row["interval_uncertain"]),
                int(row["correction_sequence"]), row["supersedes_snapshot_id"],
            ))
    observed = sorted({row["observed_at"] for row in rows})
    gaps = tuple((right - left).total_seconds() for left, right in zip(observed, observed[1:])
                 if right > left)
    expected = max(1, round(sorted(gaps)[len(gaps) // 2])) if gaps else None
    return PublicationHistory(
        first["publication_id"], first["institution_id"], first["account_id"], first["platform"],
        first["published_at"], first["history_completeness"], source_revision,
        first["source_revision_at"], max(int(row["metric_semantics_version"]) for row in rows),
        max(int(row["capability_version"]) for row in rows),
        {metric: tuple(items) for metric, items in metric_rows.items()},
        first["deleted_at"], expected,
        frozenset(Metric(value) for value in (first.get("supported_metrics") or ())),
    )


def _finding_payload(finding: Finding) -> dict[str, Any]:
    # Row ids and the stable finding key are derived inside
    # analytics.publish_anomaly_success from the attempt and this identity.
    return {
        "metric": finding.metric.value,
        "detector_id": finding.detector_id, "detector_version": finding.detector_version,
        "score": finding.score, "severity": finding.severity.value,
        "explanation_code": finding.explanation_code,
        "start_at": finding.suspicious_interval.start_at.isoformat(),
        "end_at": finding.suspicious_interval.end_at.isoformat(),
        "start_snapshot_id": finding.suspicious_interval.start_snapshot_id,
        "end_snapshot_id": finding.suspicious_interval.end_snapshot_id,
        "evidence": dict(finding.evidence), "quality_codes": list(finding.quality_codes),
        "alternative_codes": list(finding.alternative_explanation_codes),
    }


def _first(row):
    return next(iter(row.values())) if isinstance(row, dict) else row[0]
