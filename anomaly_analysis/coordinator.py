from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Protocol
from uuid import UUID, uuid4

from .aggregation import aggregate
from .config import AnalysisManifest
from .domain import Finding, Metric, PublicationHistory

# Versions recorded for a failed attempt whose source history never loaded.
DEFAULT_METRIC_SEMANTICS_VERSION = 1
DEFAULT_CAPABILITY_VERSION = 1
from .postgres import Candidate, PostgresAnalysisRepository, SourceRevision
from .preprocessing import prepare_metric
from .registry import DetectorRegistry


class MetricsSink(Protocol):
    def processed(self, outcome: str, duration_seconds: float) -> None: ...
    def detector(self, detector_id: str, outcome: str) -> None: ...
    def revision(self, analysis_revision: int, source_revision: int) -> None: ...
    def batch(self, size: int) -> None: ...
    def finding(self, detector_id: str, metric: str, severity: str) -> None: ...
    def operational(self, values: dict[str, float]) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    batch_size: int = 20
    lease_seconds: int = 120
    max_points_per_publication: int = 4096
    retry_base_seconds: int = 30
    retry_max_seconds: int = 3600
    backfill_batch_size: int = 50
    backfill_interval_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= self.backfill_interval_seconds <= 86400:
            raise ValueError("worker backfill interval is invalid")
        if not 1 <= self.batch_size <= 100 or not 10 <= self.lease_seconds <= 900:
            raise ValueError("worker batch/lease bounds are invalid")
        if not 1 <= self.max_points_per_publication <= 10000:
            raise ValueError("worker point bound is invalid")
        if not 1 <= self.backfill_batch_size <= 1000:
            raise ValueError("worker backfill bound is invalid")
        if not 1 <= self.retry_base_seconds <= self.retry_max_seconds <= 86400:
            raise ValueError("worker retry bounds are invalid")


class AnalysisCoordinator:
    def __init__(self, repository: PostgresAnalysisRepository, manifest: AnalysisManifest,
                 config: WorkerConfig, metrics: MetricsSink) -> None:
        self.repository = repository
        self.manifest = manifest
        self.config = config
        self.metrics = metrics
        self.registry = DetectorRegistry.from_manifest(manifest)
        self._last_backfill_seed: float | None = None

    def run_once(self) -> int:
        source = self.repository.latest_source_revision()
        if source is None:
            return 0
        # Configuration backfill is bounded and rate-limited; fresh candidates
        # created by the snapshot trigger keep a higher priority than backfill.
        now = time.monotonic()
        if (self._last_backfill_seed is None
                or now - self._last_backfill_seed >= self.config.backfill_interval_seconds):
            self.repository.seed_backfill(self.config.backfill_batch_size, self.manifest.sha256)
            self._last_backfill_seed = now
        self.metrics.operational(self.repository.operational_snapshot())
        claim_token = uuid4()
        candidates = self.repository.claim(self.config.batch_size, self.config.lease_seconds, claim_token)
        self.metrics.batch(len(candidates))
        if not candidates:
            return 0
        try:
            histories = self.repository.extract(tuple(item.publication_id for item in candidates),
                                                source.id, self.config.max_points_per_publication)
        except Exception:
            for candidate in candidates:
                self._publish_failure(candidate, claim_token, uuid4(), source,
                                      datetime.now(timezone.utc), "source_extraction_failed")
            return len(candidates)
        for candidate in candidates:
            started = datetime.now(timezone.utc)
            attempt_key = uuid4()
            history = histories.get(candidate.publication_id)
            try:
                if history is None:
                    raise AnalysisFailure("source_history_unavailable")
                input_hash = analysis_input_hash(history, self.manifest.sha256)
                if self.repository.unchanged(candidate.publication_id, input_hash, self.manifest.sha256):
                    self.repository.complete_noop(candidate, claim_token)
                    self.metrics.processed("unchanged", _elapsed(started))
                    continue
                outcomes = []
                platform_metrics = history.supported_metrics
                prepared_by_metric = {
                    metric: prepare_metric(history.series.get(metric, ()),
                                           max_points=self.config.max_points_per_publication)
                    for metric in platform_metrics
                }
                for detector in self.registry.detectors:
                    for metric in sorted(detector.metadata.supported_metrics & platform_metrics,
                                         key=lambda item: item.value):
                        outcome = detector.evaluate(history, metric, prepared_by_metric[metric])
                        outcomes.append(outcome)
                        self.metrics.detector(detector.metadata.detector_id,
                                              type(outcome).__name__.lower())
                aggregate_result = aggregate(tuple(outcomes))
                findings = tuple(item for item in outcomes if isinstance(item, Finding))
                for finding in findings:
                    self.metrics.finding(finding.detector_id, finding.metric.value, finding.severity.value)
                revision = self.repository.publish_success(
                    candidate, claim_token, attempt_key, source, input_hash, self.manifest.sha256,
                    self.manifest.preprocessing_version, self.manifest.aggregator_version,
                    history.metric_semantics_version, history.capability_version, started,
                    aggregate_result.status, aggregate_result.suspicion_score,
                    aggregate_result.severity.value if aggregate_result.severity else None, findings,
                )
                self.metrics.revision(revision, source.id)
                self.metrics.processed("succeeded", _elapsed(started))
            except Exception as exception:
                code = exception.code if isinstance(exception, AnalysisFailure) else "analysis_processing_failed"
                retry = min(self.config.retry_max_seconds,
                            self.config.retry_base_seconds * 2 ** min(candidate.retry_count, 7))
                self._publish_failure(candidate, claim_token, attempt_key, source, started, code, retry,
                                      history)
        return len(candidates)

    def _publish_failure(self, candidate: Candidate, claim_token: UUID, attempt_key: UUID,
                         source: SourceRevision, started: datetime, code: str,
                         retry: int | None = None, history: PublicationHistory | None = None) -> None:
        retry_seconds = retry if retry is not None else min(
            self.config.retry_max_seconds,
            self.config.retry_base_seconds * 2 ** min(candidate.retry_count, 7),
        )
        try:
            revision = self.repository.publish_failure(
                candidate, claim_token, attempt_key, source, self.manifest.sha256,
                self.manifest.preprocessing_version, self.manifest.aggregator_version,
                history.metric_semantics_version if history else DEFAULT_METRIC_SEMANTICS_VERSION,
                history.capability_version if history else DEFAULT_CAPABILITY_VERSION,
                started, code, retry_seconds,
            )
            self.metrics.revision(revision, source.id)
            self.metrics.processed("failed", _elapsed(started))
        except Exception:
            # The lease is the durable recovery mechanism when even the bounded
            # status write cannot reach PostgreSQL. Continue with sibling work.
            self.metrics.processed("failure_publication_failed", _elapsed(started))


class AnalysisFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def analysis_input_hash(history: PublicationHistory, manifest_hash: str) -> str:
    normalized = {
        metric: prepare_metric(history.series.get(metric, ()),
                               max_points=max(1, len(history.series.get(metric, ()))))
        for metric in Metric
    }
    payload = {
        "publicationId": str(history.publication_id), "platform": history.platform,
        "publishedAt": history.published_at.isoformat(), "deletedAt": history.deleted_at.isoformat() if history.deleted_at else None,
        "historyCompleteness": history.history_completeness,
        "metricSemanticsVersion": history.metric_semantics_version,
        "capabilityVersion": history.capability_version, "manifestHash": manifest_hash,
        "series": {metric.value: [{
            "id": row.snapshot_id, "at": row.observed_at.isoformat(), "age": row.age_seconds,
            "value": row.value, "quality": row.quality.value, "synthetic": row.synthetic,
            "uncertain": row.interval_uncertain, "correction": row.correction_sequence,
            "supersedes": row.supersedes_snapshot_id,
        } for row in normalized[metric].observations] for metric in Metric},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _elapsed(started: datetime) -> float:
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
