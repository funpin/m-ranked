from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import UUID

from .model import (
    CanonicalAccountBatch,
    CanonicalAccountObservation,
    CanonicalDeletionProbe,
    CanonicalMetricSnapshot,
    CanonicalPublication,
    CollectionContext,
    DeletionProbeOutcome,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    content_group_uuid,
    nonempty,
    publication_uuid,
    utc,
)


METRIC_NAMES = ("views", "reactions", "comments", "shares")
SECRET_KEY = re.compile(
    r"(?:access[_-]?token|api[_-]?key|api[_-]?hash|authorization|bearer|cookie|"
    r"password|passwd|secret|session|phone|token|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_PAIR = re.compile(
    r"(?i)(access[_-]?token|token|api[_-]?key|api[_-]?hash|password|passwd|"
    r"client[_-]?secret|private[_-]?key|session|cookie)"
    r"(\s*[:=]\s*)([^&\s,;]+)",
)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
DSN_PASSWORD = re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)([^@/\s]+)(@)")
PROBE_REASON_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
AUTHORITATIVE_MISSING_REASONS = {
    "telegram": frozenset({
        "telegram_mtproto_empty_get_messages",
        "telegram_public_http_404",
        "telegram_public_http_410",
        "telegram_public_deleted_marker",
    }),
    "vk": frozenset({"vk_wall_get_by_id_not_found_or_deleted"}),
    "max": frozenset({"max_get_messages_not_found_or_deleted"}),
    "rutube": frozenset({"rutube_video_http_404", "rutube_video_http_410"}),
}


def redact_text(value: str) -> str:
    value = BEARER.sub("Bearer [REDACTED]", value)
    value = SECRET_PAIR.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return DSN_PASSWORD.sub(r"\1[REDACTED]\3", value)


def sanitize_evidence(value: Any, key: str | None = None) -> Any:
    """Recursively redact credentials before evidence, fingerprints, or logs."""
    if key is not None and SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_evidence(item_value, str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(item) for item in value]
    if isinstance(value, (set, frozenset)):
        sanitized = [sanitize_evidence(item) for item in value]
        return sorted(
            sanitized,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, datetime):
        return utc(value, "evidence timestamp").isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return sanitize_evidence(asdict(value))
    if isinstance(value, float) and not math.isfinite(value):
        return "[NON_FINITE]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def canonical_json(value: Any) -> str:
    return json.dumps(
        sanitize_evidence(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def source_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sanitize_error_code(error: BaseException) -> str:
    """Return a bounded, non-secret classification; never include exception text."""
    name = error.__class__.__name__[:80] or "Error"
    raw_code = getattr(error, "code", None)
    if raw_code is None:
        return name
    code = str(raw_code)
    if (
        SECRET_KEY.search(code)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", code)
    ):
        return name
    return f"{name}:{code}" if code else name


def _https(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _counter(value: int | float | None) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, float) and not value.is_integer():
        return None, True
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None, True
    return (None, True) if parsed < 0 else (parsed, False)


def _identities(raw: RawPublication) -> tuple[IdentityCandidate, ...]:
    primary = IdentityCandidate(
        nonempty(raw.external_id, "external_id"),
        IdentityRole.PRIMARY,
        raw.source_external_id,
        _https(raw.public_url),
    )
    result: dict[str, IdentityCandidate] = {primary.external_id: primary}
    for identity in raw.identities:
        external_id = nonempty(identity.external_id, "identity.external_id")
        if external_id == primary.external_id:
            continue
        result.setdefault(
            external_id,
            IdentityCandidate(
                external_id,
                identity.role,
                identity.source_external_id,
                _https(identity.public_url),
            ),
        )
    return tuple(result.values())


class CanonicalNormalizer:
    """Pure normalization pipeline shared by all platform adapters."""

    def normalize(
        self,
        raw: RawCollectionBatch,
        context: CollectionContext,
    ) -> CanonicalAccountBatch:
        if raw.account.platform != context.platform:
            raise ValueError("batch platform does not match collection context")
        account_observation = self._account(raw, context)
        publications = tuple(
            self._publication(raw, publication, context)
            for publication in raw.publications
        )
        deletion_probes = tuple(
            self._deletion_probe(probe, context)
            for probe in raw.deletion_probes
        )
        probe_ids = [probe.publication_id for probe in deletion_probes]
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("only one deletion probe per publication is allowed")
        return CanonicalAccountBatch(
            account=raw.account,
            context=context,
            account_observation=account_observation,
            publications=publications,
            source_name=nonempty(raw.source_name, "source_name"),
            source_version=nonempty(raw.source_version, "source_version"),
            cursor=raw.cursor,
            deletion_probes=deletion_probes,
            refresh_cursor=raw.refresh_cursor,
        )

    @staticmethod
    def _deletion_probe(
        raw: RawDeletionProbe, context: CollectionContext,
    ) -> CanonicalDeletionProbe:
        observed = utc(raw.observed_at, "deletion_probe.observed_at")
        if raw.outcome == DeletionProbeOutcome.CONFIRMED_DELETED:
            raise ValueError("confirmed deletion is derived by the repository")
        reason_code = raw.reason_code.strip()
        if not PROBE_REASON_CODE.fullmatch(reason_code):
            raise ValueError("deletion probe reason_code is invalid")
        if (
            raw.outcome == DeletionProbeOutcome.MISSING
            and reason_code not in AUTHORITATIVE_MISSING_REASONS[context.platform.value]
        ):
            raise ValueError("missing probe reason is not authoritative for platform")
        threshold = int(raw.confirmation_threshold)
        if threshold < 2:
            raise ValueError("deletion confirmation threshold must be at least two")
        return CanonicalDeletionProbe(
            raw.publication_id,
            observed,
            raw.outcome,
            reason_code,
            threshold,
        )

    def _account(
        self,
        batch: RawCollectionBatch,
        context: CollectionContext,
    ) -> CanonicalAccountObservation | None:
        raw = batch.account_observation
        if raw is None:
            return None
        observed = utc(raw.observed_at, "account.observed_at")
        collected = utc(raw.collected_at, "account.collected_at")
        if collected < observed:
            raise ValueError("account.collected_at must not precede observed_at")
        subscribers, invalid = _counter(raw.subscriber_count)
        quality = ObservationQuality.INVALID if invalid else raw.quality
        evidence = sanitize_evidence({
            "platform": context.platform.value,
            "account": str(batch.account.id),
            "observed_at": observed,
            "collected_at": collected,
            "source_name": batch.source_name,
            "source_version": batch.source_version,
            "source": raw.source,
            "subscriber_count": subscribers,
            "subscriber_display": raw.subscriber_display,
            "quality": quality,
            "username": raw.username,
            "title": raw.title,
            "url": raw.url,
            "native_external_id": raw.native_external_id,
        })
        return CanonicalAccountObservation(
            observed, collected, subscribers, raw.subscriber_display,
            quality, source_fingerprint(evidence), evidence,
            _optional_text(raw.username),
            _optional_text(raw.title),
            _https(raw.url),
            _optional_text(raw.native_external_id),
        )

    def _publication(
        self,
        batch: RawCollectionBatch,
        raw: RawPublication,
        context: CollectionContext,
    ) -> CanonicalPublication:
        external_id = nonempty(raw.external_id, "external_id")
        published = utc(raw.published_at, "published_at")
        discovered = utc(raw.discovered_at, "discovered_at")
        observed = utc(raw.observed_at, "observed_at")
        collected = utc(raw.collected_at, "collected_at")
        if discovered < published:
            raise ValueError("discovered_at must not precede published_at")
        if collected < observed:
            raise ValueError("collected_at must not precede observed_at")
        if raw.synthetic and observed != published:
            raise ValueError("synthetic baseline must be observed at publication time")
        invalid_fields: list[str] = []
        values: dict[str, int | None] = {}
        metric_quality: dict[str, ObservationQuality] = {}
        for metric in METRIC_NAMES:
            value, invalid = _counter(raw.metrics.get(metric))
            if metric in raw.suspected_reset_metrics:
                value = None
                metric_quality[metric] = ObservationQuality.SUSPECTED_RESET
            else:
                metric_quality[metric] = raw.metric_quality.get(metric, raw.quality)
            if invalid:
                invalid_fields.append(metric)
                metric_quality[metric] = ObservationQuality.INVALID
            values[metric] = value

        reactions: dict[str, int] = {}
        for key, value in raw.reaction_breakdown.items():
            parsed, invalid = _counter(value)
            if invalid or parsed is None:
                invalid_fields.append(f"reaction:{key}")
                continue
            reactions[nonempty(str(key), "reaction key")] = parsed

        quality = raw.quality
        if invalid_fields:
            quality = ObservationQuality.INVALID
        elif raw.suspected_reset_metrics:
            quality = ObservationQuality.SUSPECTED_RESET
        age_seconds = max(0, int((observed - published).total_seconds()))
        flags = dict(sanitize_evidence(raw.quality_flags))
        if observed < published:
            flags["observed_before_publication"] = True
            quality = ObservationQuality.INVALID
        if invalid_fields:
            flags["invalid_fields"] = sorted(set(invalid_fields))
        interval = int(raw.sampling_interval_seconds)
        if interval <= 0:
            raise ValueError("sampling_interval_seconds must be positive")
        sampling_bucket = (
            -1 if raw.synthetic else
            raw.sampling_bucket if raw.sampling_bucket is not None else
            int(context.scheduled_at.timestamp()) // interval
        )
        if sampling_bucket < 0 and not raw.synthetic:
            raise ValueError("sampling_bucket must be non-negative")
        identities = _identities(raw)
        evidence = sanitize_evidence({
            "platform": context.platform.value,
            "account": str(batch.account.id),
            "external_id": external_id,
            "source_external_id": raw.source_external_id,
            "identities": identities,
            "source_name": batch.source_name,
            "source_version": batch.source_version,
            "scheduled_at": context.scheduled_at,
            "published_at": published,
            "discovered_at": discovered,
            "observed_at": observed,
            "collected_at": collected,
            "publication_type": raw.publication_type,
            "public_url": _https(raw.public_url),
            "is_repost": raw.is_repost,
            "metrics": values,
            "quality": quality,
            "metric_quality": metric_quality,
            "reaction_breakdown": reactions,
            "history_completeness": raw.history_completeness,
            "synthetic": raw.synthetic,
            "interval_uncertain": raw.interval_uncertain,
            "sampling_interval_seconds": interval,
            "sampling_bucket": sampling_bucket,
            "quality_flags": flags,
            "source": raw.source,
        })
        snapshot = CanonicalMetricSnapshot(
            observed_at=observed,
            collected_at=collected,
            age_seconds=0 if raw.synthetic else age_seconds,
            sampling_bucket=int(sampling_bucket),
            published_month=published.date().replace(day=1),
            views_count=values["views"],
            reactions_count=values["reactions"],
            comments_count=values["comments"],
            shares_count=values["shares"],
            quality=quality,
            metric_quality=metric_quality,
            interval_uncertain=raw.interval_uncertain,
            synthetic=raw.synthetic,
            reaction_breakdown=reactions,
            source_fingerprint=source_fingerprint(evidence),
            sanitized_source=evidence,
        )
        return CanonicalPublication(
            id=publication_uuid(batch.account.id, external_id),
            account_id=batch.account.id,
            content_group_id=(
                content_group_uuid(batch.account.id, raw.group_key)
                if raw.group_key else None
            ),
            external_id=external_id,
            source_external_id=raw.source_external_id,
            identities=identities,
            public_url=_https(raw.public_url),
            published_at=published,
            discovered_at=discovered,
            publication_type=nonempty(raw.publication_type, "publication_type"),
            is_repost=raw.is_repost,
            history_completeness=raw.history_completeness,
            synthetic_baseline_allowed=(
                raw.synthetic
                and raw.history_completeness.value == "complete"
            ),
            quality_flags=flags,
            snapshot=snapshot,
        )
