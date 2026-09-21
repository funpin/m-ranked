"""Bounded canonical-batch transfer protocol used by deployment profiles A and B."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import random
import re
import ssl
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from .model import (
    AccountRef,
    CanonicalAccountBatch,
    CanonicalAccountObservation,
    CanonicalDeletionProbe,
    CanonicalMetricSnapshot,
    CanonicalPublication,
    CollectionContext,
    DeletionProbeOutcome,
    HistoryCompleteness,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    Platform,
    utc,
)
from .normalize import canonical_json, sanitize_evidence


TRANSFER_NAMESPACE = UUID("1d364639-e8b5-5ec0-bc1f-3114619b2bd5")
SCHEMA_VERSION = 1
MAX_RECORDS = 500
MAX_COMPRESSED_BYTES = 8 * 1024 * 1024
HARD_MAX_ENVELOPE_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_NESTING = 16
MAX_STRING_LENGTH = 262_144
MAX_INTEGER = 9_223_372_036_854_775_807
MAX_BATCH_AGE_SECONDS = 30
RETRY_BASE_SECONDS = 1.0
RETRY_MAX_SECONDS = 300.0
RETRY_WINDOW_SECONDS = 3600
RETRY_MAX_ATTEMPTS_PER_WINDOW = 20
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRODUCER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class TransferRejected(ValueError):
    """A bounded, non-secret protocol rejection."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _compress(payload: bytes) -> bytes:
    try:
        from compression import zstd
        return zstd.compress(payload, level=3)
    except ImportError:  # Python 3.13 production image
        import zstandard
        return zstandard.ZstdCompressor(level=3).compress(payload)


def _decompress(payload: bytes, expected_size: int) -> bytes:
    if expected_size > MAX_UNCOMPRESSED_BYTES:
        raise TransferRejected("uncompressed_size_exceeded")
    try:
        from compression import zstd
        frame = zstd.get_frame_info(payload)
        if frame.decompressed_size is not None and frame.decompressed_size > expected_size:
            raise TransferRejected("uncompressed_size_mismatch")
        result = zstd.ZstdDecompressor().decompress(
            payload, max_length=expected_size + 1,
        )
    except ImportError:  # Python 3.13 production image
        import zstandard
        try:
            result = zstandard.ZstdDecompressor().decompress(
                payload, max_output_size=expected_size,
            )
        except zstandard.ZstdError as error:
            raise TransferRejected("invalid_compressed_payload") from error
    except TransferRejected:
        raise
    except Exception as error:
        raise TransferRejected("invalid_compressed_payload") from error
    if len(result) != expected_size:
        raise TransferRejected("uncompressed_size_mismatch")
    return result


def _iso(value: datetime) -> str:
    return utc(value, "transfer timestamp").isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise TransferRejected("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TransferRejected("invalid_timestamp") from error
    return utc(parsed, "transfer timestamp")


def _identity(value: IdentityCandidate) -> dict[str, Any]:
    return {
        "externalId": value.external_id,
        "role": value.role.value,
        "sourceExternalId": value.source_external_id,
        "publicUrl": value.public_url,
    }


def _batch_dict(batch: CanonicalAccountBatch) -> dict[str, Any]:
    observation = batch.account_observation
    return sanitize_evidence({
        "account": {
            "id": batch.account.id,
            "institutionId": batch.account.institution_id,
            "platform": batch.account.platform.value,
            "canonicalExternalId": batch.account.canonical_external_id,
            "accessMode": batch.account.access_mode,
            "currentUsername": batch.account.current_username,
            "currentTitle": batch.account.current_title,
            "currentUrl": batch.account.current_url,
            "nativeExternalId": batch.account.native_external_id,
        },
        "context": {
            "runId": batch.context.run_id,
            "correlationId": batch.context.correlation_id,
            "platform": batch.context.platform.value,
            "partitionKey": batch.context.partition_key,
            "collectorVersion": batch.context.collector_version,
            "scheduledAt": _iso(batch.context.scheduled_at),
            "startedAt": _iso(batch.context.started_at),
        },
        "accountObservation": None if observation is None else {
            "observedAt": _iso(observation.observed_at),
            "collectedAt": _iso(observation.collected_at),
            "subscriberCount": observation.subscriber_count,
            "subscriberDisplay": observation.subscriber_display,
            "quality": observation.quality.value,
            "sourceFingerprint": observation.source_fingerprint,
            "semanticFingerprint": observation.semantic_fingerprint.hex(),
            "sanitizedSource": observation.sanitized_source,
            "username": observation.username,
            "title": observation.title,
            "url": observation.url,
            "nativeExternalId": observation.native_external_id,
        },
        "publications": [{
            "id": item.id,
            "accountId": item.account_id,
            "contentGroupId": item.content_group_id,
            "externalId": item.external_id,
            "sourceExternalId": item.source_external_id,
            "identities": [_identity(identity) for identity in item.identities],
            "publicUrl": item.public_url,
            "publishedAt": _iso(item.published_at),
            "discoveredAt": _iso(item.discovered_at),
            "publicationType": item.publication_type,
            "isRepost": item.is_repost,
            "historyCompleteness": item.history_completeness.value,
            "syntheticBaselineAllowed": item.synthetic_baseline_allowed,
            "qualityFlags": item.quality_flags,
            "snapshot": {
                "observedAt": _iso(item.snapshot.observed_at),
                "collectedAt": _iso(item.snapshot.collected_at),
                "ageSeconds": item.snapshot.age_seconds,
                "samplingBucket": item.snapshot.sampling_bucket,
                "publishedMonth": item.snapshot.published_month.isoformat(),
                "viewsCount": item.snapshot.views_count,
                "reactionsCount": item.snapshot.reactions_count,
                "commentsCount": item.snapshot.comments_count,
                "sharesCount": item.snapshot.shares_count,
                "quality": item.snapshot.quality.value,
                "metricQuality": {key: value.value for key, value in item.snapshot.metric_quality.items()},
                "intervalUncertain": item.snapshot.interval_uncertain,
                "synthetic": item.snapshot.synthetic,
                "reactionBreakdown": item.snapshot.reaction_breakdown,
                "sourceFingerprint": item.snapshot.source_fingerprint,
                "semanticFingerprint": item.snapshot.semantic_fingerprint.hex(),
                "sanitizedSource": item.snapshot.sanitized_source,
            },
        } for item in batch.publications],
        "sourceName": batch.source_name,
        "sourceVersion": batch.source_version,
        "cursor": batch.cursor,
        "deletionProbes": [{
            "publicationId": item.publication_id,
            "observedAt": _iso(item.observed_at),
            "outcome": item.outcome.value,
            "reasonCode": item.reason_code,
            "confirmationThreshold": item.confirmation_threshold,
        } for item in batch.deletion_probes],
        "refreshCursor": batch.refresh_cursor,
    })


def _max_event_time(batch: CanonicalAccountBatch, field: str) -> datetime:
    values = [getattr(item.snapshot, field) for item in batch.publications]
    if batch.account_observation is not None:
        values.append(getattr(batch.account_observation, field))
    if field == "observed_at":
        values.extend(item.observed_at for item in batch.deletion_probes)
    return max(values, default=batch.context.started_at)


def canonical_event(batch: CanonicalAccountBatch) -> dict[str, Any]:
    body = _batch_dict(batch)
    semantic_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    event_id = uuid5(
        TRANSFER_NAMESPACE,
        f"event|{batch.context.platform.value}|{batch.account.id}|{semantic_hash}",
    )
    return {
        "eventId": str(event_id),
        "platform": batch.context.platform.value,
        "accountId": str(batch.account.id),
        "observedAt": _iso(_max_event_time(batch, "observed_at")),
        "collectedAt": _iso(_max_event_time(batch, "collected_at")),
        "sourceSchemaVersion": batch.source_version,
        "semanticHash": semantic_hash,
        "batch": body,
    }


@dataclass(frozen=True, slots=True)
class TransferEnvelope:
    schema_version: int
    batch_id: UUID
    producer_id: str
    first_cursor: int
    last_cursor: int
    created_at: datetime
    record_count: int
    uncompressed_bytes: int
    compression: str
    payload_sha256: str
    payload: bytes

    @property
    def wire_size(self) -> int:
        return len(self.payload) + 1024


@dataclass(frozen=True, slots=True)
class TransferAck:
    receipt_id: UUID
    batch_id: UUID
    checksum: str


def seal_batch(batch: CanonicalAccountBatch, producer_id: str, *, cursor: int = 0) -> TransferEnvelope:
    if not _PRODUCER_ID.fullmatch(producer_id):
        raise TransferRejected("invalid_producer_id")
    event = canonical_event(batch)
    encoded = (canonical_json(event) + "\n").encode("utf-8")
    _validate_value(event)
    compressed = _compress(encoded)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise TransferRejected("compressed_batch_too_large")
    checksum = hashlib.sha256(compressed).hexdigest()
    batch_id = uuid5(TRANSFER_NAMESPACE, f"batch|{checksum}")
    return TransferEnvelope(
        SCHEMA_VERSION, batch_id, producer_id, cursor, cursor,
        _max_event_time(batch, "collected_at"), 1, len(encoded), "zstd",
        checksum, compressed,
    )


def with_cursor(envelope: TransferEnvelope, cursor: int) -> TransferEnvelope:
    return TransferEnvelope(
        envelope.schema_version, envelope.batch_id, envelope.producer_id,
        cursor, cursor, envelope.created_at, envelope.record_count,
        envelope.uncompressed_bytes, envelope.compression,
        envelope.payload_sha256, envelope.payload,
    )


def validate_envelope(envelope: TransferEnvelope, *, accept_schema: bool = True) -> None:
    if envelope.wire_size > HARD_MAX_ENVELOPE_BYTES:
        raise TransferRejected("envelope_too_large")
    if not _PRODUCER_ID.fullmatch(envelope.producer_id):
        raise TransferRejected("invalid_producer_id")
    if accept_schema and envelope.schema_version != SCHEMA_VERSION:
        raise TransferRejected("incompatible_schema")
    if envelope.compression != "zstd":
        raise TransferRejected("unsupported_compression")
    if not 1 <= envelope.record_count <= MAX_RECORDS:
        raise TransferRejected("record_count_exceeded")
    if not 0 < len(envelope.payload) <= MAX_COMPRESSED_BYTES:
        raise TransferRejected("compressed_batch_too_large")
    if not 0 < envelope.uncompressed_bytes <= MAX_UNCOMPRESSED_BYTES:
        raise TransferRejected("uncompressed_size_exceeded")
    if envelope.uncompressed_bytes > len(envelope.payload) * MAX_COMPRESSION_RATIO:
        raise TransferRejected("compression_ratio_exceeded")
    if envelope.first_cursor < 1 or envelope.last_cursor < envelope.first_cursor:
        raise TransferRejected("invalid_cursor_range")
    if not _HEX_SHA256.fullmatch(envelope.payload_sha256):
        raise TransferRejected("invalid_checksum")
    if hashlib.sha256(envelope.payload).hexdigest() != envelope.payload_sha256:
        raise TransferRejected("checksum_mismatch")


def _validate_value(value: Any, depth: int = 0) -> None:
    if depth > MAX_NESTING:
        raise TransferRejected("nesting_exceeded")
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise TransferRejected("string_length_exceeded")
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if value < -MAX_INTEGER or value > MAX_INTEGER:
            raise TransferRejected("numeric_range_exceeded")
        return
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > MAX_INTEGER:
            raise TransferRejected("numeric_range_exceeded")
        return
    if isinstance(value, list):
        if len(value) > MAX_RECORDS * 20:
            raise TransferRejected("collection_count_exceeded")
        for item in value:
            _validate_value(item, depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise TransferRejected("collection_count_exceeded")
        for key, item in value.items():
            _validate_value(str(key), depth + 1)
            _validate_value(item, depth + 1)
        return
    raise TransferRejected("invalid_value_type")


def decode_events(envelope: TransferEnvelope) -> tuple[CanonicalAccountBatch, ...]:
    validate_envelope(envelope)
    raw = _decompress(envelope.payload, envelope.uncompressed_bytes)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise TransferRejected("invalid_jsonl") from error
    if len(lines) != envelope.record_count:
        raise TransferRejected("record_count_mismatch")
    batches: list[CanonicalAccountBatch] = []
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError) as error:
            raise TransferRejected("invalid_jsonl") from error
        _validate_value(event)
        semantic_hash = event.get("semanticHash") if isinstance(event, dict) else None
        body = event.get("batch") if isinstance(event, dict) else None
        if not isinstance(body, dict) or hashlib.sha256(
            canonical_json(body).encode("utf-8")
        ).hexdigest() != semantic_hash:
            raise TransferRejected("semantic_hash_mismatch")
        batches.append(_decode_batch(body))
    return tuple(batches)


def _decode_batch(value: Mapping[str, Any]) -> CanonicalAccountBatch:
    try:
        account_value = value["account"]
        context_value = value["context"]
        account = AccountRef(
            UUID(account_value["id"]), UUID(account_value["institutionId"]),
            Platform(account_value["platform"]), account_value["canonicalExternalId"],
            account_value["accessMode"], account_value.get("currentUsername"),
            account_value.get("currentTitle"), account_value.get("currentUrl"),
            account_value.get("nativeExternalId"),
        )
        context = CollectionContext(
            UUID(context_value["runId"]), UUID(context_value["correlationId"]),
            Platform(context_value["platform"]), context_value["partitionKey"],
            context_value["collectorVersion"], _parse_time(context_value["scheduledAt"]),
            _parse_time(context_value["startedAt"]),
        )
        observation_value = value.get("accountObservation")
        observation = None if observation_value is None else CanonicalAccountObservation(
            _parse_time(observation_value["observedAt"]),
            _parse_time(observation_value["collectedAt"]),
            observation_value.get("subscriberCount"), observation_value.get("subscriberDisplay"),
            ObservationQuality(observation_value["quality"]), observation_value["sourceFingerprint"],
            bytes.fromhex(observation_value["semanticFingerprint"]), observation_value["sanitizedSource"],
            observation_value.get("username"), observation_value.get("title"),
            observation_value.get("url"), observation_value.get("nativeExternalId"),
        )
        publications = []
        for item in value["publications"]:
            snapshot = item["snapshot"]
            publications.append(CanonicalPublication(
                UUID(item["id"]), UUID(item["accountId"]),
                UUID(item["contentGroupId"]) if item.get("contentGroupId") else None,
                item["externalId"], item.get("sourceExternalId"),
                tuple(IdentityCandidate(
                    identity["externalId"], IdentityRole(identity["role"]),
                    identity.get("sourceExternalId"), identity.get("publicUrl"),
                ) for identity in item["identities"]),
                item.get("publicUrl"), _parse_time(item["publishedAt"]),
                _parse_time(item["discoveredAt"]), item["publicationType"],
                bool(item["isRepost"]), HistoryCompleteness(item["historyCompleteness"]),
                bool(item["syntheticBaselineAllowed"]), item["qualityFlags"],
                CanonicalMetricSnapshot(
                    _parse_time(snapshot["observedAt"]), _parse_time(snapshot["collectedAt"]),
                    int(snapshot["ageSeconds"]), int(snapshot["samplingBucket"]),
                    date.fromisoformat(snapshot["publishedMonth"]), snapshot.get("viewsCount"),
                    snapshot.get("reactionsCount"), snapshot.get("commentsCount"),
                    snapshot.get("sharesCount"), ObservationQuality(snapshot["quality"]),
                    {key: ObservationQuality(item_value) for key, item_value in snapshot["metricQuality"].items()},
                    bool(snapshot["intervalUncertain"]), bool(snapshot["synthetic"]),
                    snapshot["reactionBreakdown"], snapshot["sourceFingerprint"],
                    bytes.fromhex(snapshot["semanticFingerprint"]), snapshot["sanitizedSource"],
                ),
            ))
        probes = tuple(CanonicalDeletionProbe(
            UUID(item["publicationId"]), _parse_time(item["observedAt"]),
            DeletionProbeOutcome(item["outcome"]), item["reasonCode"],
            int(item["confirmationThreshold"]),
        ) for item in value["deletionProbes"])
        return CanonicalAccountBatch(
            account, context, observation, tuple(publications), value["sourceName"],
            value["sourceVersion"], value.get("cursor"), probes,
            value.get("refreshCursor"),
        )
    except TransferRejected:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise TransferRejected("invalid_canonical_batch") from error


class EnvelopeConsumer(Protocol):
    def receive(self, envelope: TransferEnvelope) -> TransferAck: ...


class InProcessTransport:
    def __init__(self, consumer: EnvelopeConsumer):
        self.consumer = consumer

    def send(self, envelope: TransferEnvelope) -> TransferAck:
        return self.consumer.receive(envelope)


class HttpsMtlsTransport:
    """P2-ready sender skeleton; certificate provisioning remains out of scope."""

    def __init__(self, endpoint: str, *, certificate: str, private_key: str, ca_bundle: str):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("TRANSFER_HTTPS_ENDPOINT must be an HTTPS URL without credentials")
        if not certificate or not private_key or not ca_bundle:
            raise ValueError("mTLS certificate, private key and CA bundle are required")
        self.endpoint = endpoint
        self.certificate = certificate
        self.private_key = private_key
        self.ca_bundle = ca_bundle

    def send(self, envelope: TransferEnvelope) -> TransferAck:
        validate_envelope(envelope)
        import httpx
        context = ssl.create_default_context(cafile=self.ca_bundle)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(self.certificate, self.private_key)
        response = httpx.post(
            self.endpoint,
            content=envelope.payload,
            headers={
                "content-type": "application/zstd",
                "x-mranked-schema-version": str(envelope.schema_version),
                "x-mranked-batch-id": str(envelope.batch_id),
                "x-mranked-producer-id": envelope.producer_id,
                "x-mranked-first-cursor": str(envelope.first_cursor),
                "x-mranked-last-cursor": str(envelope.last_cursor),
                "x-mranked-created-at": _iso(envelope.created_at),
                "x-mranked-record-count": str(envelope.record_count),
                "x-mranked-uncompressed-bytes": str(envelope.uncompressed_bytes),
                "x-mranked-payload-sha256": envelope.payload_sha256,
            },
            verify=context,
            timeout=httpx.Timeout(connect=3, read=30, write=30, pool=3),
        )
        response.raise_for_status()
        body = response.json()
        return TransferAck(UUID(body["receiptId"]), envelope.batch_id, body["checksum"])


def retry_delay_seconds(attempt: int, random_unit: float) -> float:
    """Экспоненциальная задержка с полным jitter.

    Полный jitter означает равномерный выбор из ``[0, ceiling]``, а не
    отклонение вокруг него: именно это разводит одновременно осиротевшие батчи
    по времени, вместо того чтобы отправить их одной пачкой при восстановлении
    связи. ``attempt`` — номер уже выполненной попытки, начиная с единицы.
    """
    if attempt < 1:
        raise ValueError("attempt must be positive")
    if not 0.0 <= random_unit <= 1.0:
        raise ValueError("random_unit must be within [0, 1]")
    ceiling = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return random_unit * ceiling


def _row(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _restore_provenance(connection: Any, batch: Any) -> None:
    """Восстановить у потребителя происхождение пачки.

    Запись пачки опирается на две строки, которые заводит сборщик до сбора:
    прогон ``ingest.collection_run`` и результат по аккаунту
    ``ingest.collection_account_result``. В конверт они не попадают, потому
    что при in-process доставке уже существуют — обе базы там одна. При
    настоящем переносе между двумя базами их у потребителя нет, и применение
    падало: сначала на внешнем ключе ревизии, затем на отсутствующем
    результате по аккаунту.

    Контекст пачки несёт все нужные поля, так что обе строки
    восстанавливаются без обращения к производителю. Статус ``running``
    отражает состояние на момент запечатывания; завершение проставит сама
    запись пачки.
    """
    context = batch.context
    connection.execute(
        """INSERT INTO ingest.collection_run(
               id, platform, partition_key, collector_version, started_at,
               scheduled_at, status, correlation_id
           ) VALUES (%s,%s,%s,%s,%s,%s,'running',%s)
           ON CONFLICT (id) DO NOTHING""",
        (
            context.run_id,
            context.platform.value,
            context.partition_key,
            context.collector_version,
            context.started_at,
            context.scheduled_at,
            context.correlation_id,
        ),
    )
    connection.execute(
        """INSERT INTO ingest.collection_account_result(
               collection_run_id, platform_account_id, started_at, status
           ) VALUES (%s,%s,%s,'running')
           ON CONFLICT (collection_run_id, platform_account_id) DO NOTHING""",
        (context.run_id, batch.account.id, context.started_at),
    )


class PostgresDataAdapter:
    """Durable inbox plus the existing collector repository write path."""

    def __init__(self, repository: Any):
        self.repository = repository

    def receive(self, envelope: TransferEnvelope) -> TransferAck:
        # All cheap limits and the compressed checksum precede any DB call or
        # decompression allocation.
        validate_envelope(envelope, accept_schema=False)
        incompatible = envelope.schema_version != SCHEMA_VERSION
        batches = () if incompatible else decode_events(envelope)
        event_ids = tuple(
            UUID(canonical_event(batch)["eventId"]) for batch in batches
        )
        with self.repository._connection() as connection, connection.transaction():
            row = connection.execute(
                """INSERT INTO ops_and_admin.transfer_inbox(
                       producer_id,batch_id,schema_version,first_cursor,last_cursor,
                       payload,checksum,record_count,uncompressed_bytes,state,
                       verified_at,reason_code
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                             CASE WHEN %s THEN NULL ELSE transaction_timestamp() END,
                             CASE WHEN %s THEN 'incompatible_schema' ELSE NULL END)
                   ON CONFLICT (producer_id,batch_id) DO NOTHING
                   RETURNING receipt_id,checksum,state""",
                (
                    envelope.producer_id, envelope.batch_id, envelope.schema_version,
                    envelope.first_cursor, envelope.last_cursor,
                    None if incompatible else envelope.payload,
                    envelope.payload_sha256, envelope.record_count,
                    envelope.uncompressed_bytes,
                    "quarantined" if incompatible else "verified",
                    incompatible, incompatible,
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT receipt_id,checksum,state
                         FROM ops_and_admin.transfer_inbox
                        WHERE producer_id=%s AND batch_id=%s FOR UPDATE""",
                    (envelope.producer_id, envelope.batch_id),
                ).fetchone()
            if row is None:
                raise RuntimeError("transfer inbox receipt was not persisted")
            if str(_row(row, "checksum", 1)) != envelope.payload_sha256:
                raise TransferRejected("batch_identity_conflict")
            ack = TransferAck(
                UUID(str(_row(row, "receipt_id", 0))), envelope.batch_id,
                envelope.payload_sha256,
            )
            if not incompatible:
                for index, event_id in enumerate(event_ids):
                    connection.execute(
                        """INSERT INTO ops_and_admin.transfer_inbox_event(
                               receipt_id,event_index,event_id
                           ) VALUES (%s,%s,%s)
                           ON CONFLICT (event_id) DO NOTHING""",
                        (ack.receipt_id, index, event_id),
                    )
        if not incompatible:
            self.apply(ack.receipt_id)
        return ack

    def apply(self, receipt_id: UUID) -> None:
        # Read the durable bytes, then validate/decode outside the applying
        # transaction so malformed input cannot hold database locks.
        with self.repository._connection() as connection:
            row = connection.execute(
                """SELECT schema_version,batch_id,producer_id,first_cursor,last_cursor,
                          received_at,record_count,uncompressed_bytes,checksum,payload,state
                     FROM ops_and_admin.transfer_inbox WHERE receipt_id=%s""",
                (receipt_id,),
            ).fetchone()
        if row is None:
            raise KeyError("unknown transfer receipt")
        if str(_row(row, "state", 10)) == "applied":
            return
        envelope = TransferEnvelope(
            int(_row(row, "schema_version", 0)), UUID(str(_row(row, "batch_id", 1))),
            str(_row(row, "producer_id", 2)), int(_row(row, "first_cursor", 3)),
            int(_row(row, "last_cursor", 4)),
            utc(_row(row, "received_at", 5), "inbox.received_at"),
            int(_row(row, "record_count", 6)), int(_row(row, "uncompressed_bytes", 7)),
            "zstd", str(_row(row, "checksum", 8)), bytes(_row(row, "payload", 9)),
        )
        try:
            batches = decode_events(envelope)
        except TransferRejected as error:
            with self.repository._connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE ops_and_admin.transfer_inbox
                          SET state='quarantined',reason_code=%s,applied_cursor=NULL
                        WHERE receipt_id=%s AND state<>'applied'""",
                    (error.code, receipt_id),
                )
            return
        evidence_ids = [tuple(
            self.repository._metric_evidence_id(
                self.repository._metric_evidence(item.snapshot)
            )
            for item in batch.publications
        ) for batch in batches]
        with self.repository._connection() as connection, connection.transaction():
            locked = connection.execute(
                """SELECT state FROM ops_and_admin.transfer_inbox
                    WHERE receipt_id=%s FOR UPDATE""",
                (receipt_id,),
            ).fetchone()
            if locked is None:
                raise KeyError("unknown transfer receipt")
            if str(_row(locked, "state", 0)) == "applied":
                return
            connection.execute(
                """UPDATE ops_and_admin.transfer_inbox
                      SET state='applying',applying_at=transaction_timestamp(),reason_code=NULL
                    WHERE receipt_id=%s""",
                (receipt_id,),
            )
            accepted = 0
            duplicate = 0
            outcomes: list[str] = []
            for batch, ids in zip(batches, evidence_ids, strict=True):
                _restore_provenance(connection, batch)
                result, _ = self.repository.persist_account_batch_in_transaction(
                    connection, batch, metric_evidence_ids=ids,
                    seal_transfer=False, transfer_replay=True,
                )
                accepted += int(result.revision_id is not None)
                duplicate += int(result.revision_id is None)
                outcomes.append(
                    "accepted" if result.revision_id is not None else "duplicate"
                )
            accounted = accepted + duplicate
            if accounted != envelope.record_count:
                raise RuntimeError("transfer record accounting mismatch")
            connection.execute(
                """UPDATE ops_and_admin.transfer_inbox
                      SET state='applied',accepted_count=%s,duplicate_count=%s,
                          deferred_count=0,rejected_count=0,
                          applied_cursor=last_cursor,applied_at=transaction_timestamp()
                    WHERE receipt_id=%s""",
                (accepted, duplicate, receipt_id),
            )
            for index, outcome in enumerate(outcomes):
                connection.execute(
                    """UPDATE ops_and_admin.transfer_inbox_event
                          SET outcome=%s,reason_code=NULL
                        WHERE receipt_id=%s AND event_index=%s""",
                    (outcome, receipt_id, index),
                )


class PostgresTransferProducer:
    """Oldest-first sender; an ACK is persisted before its watermark advances."""

    def __init__(
        self,
        repository: Any,
        transport: Any,
        metrics: Any = None,
        *,
        random_unit: Any = None,
    ):
        self.repository = repository
        self.transport = transport
        self.metrics = metrics
        # Инъецируемый источник, чтобы задержку можно было проверить точно.
        self._random_unit = random_unit or random.random

    def deliver_pending(self, *, limit: int = 100) -> int:
        delivered = 0
        with self.repository._connection() as connection:
            rows = connection.execute(
                """SELECT cursor,batch_id,producer_id,schema_version,created_at,
                          record_count,uncompressed_bytes,payload_sha256,payload
                     FROM ops_and_admin.transfer_outbox
                    WHERE state IN ('sealed','sent')
                      AND available_at<=transaction_timestamp()
                      AND (
                        attempt_window_started_at IS NULL
                        OR attempt_window_started_at
                             <= transaction_timestamp()-%s*interval '1 second'
                        OR attempt_window_count < %s
                      )
                    ORDER BY cursor LIMIT %s""",
                (RETRY_WINDOW_SECONDS, RETRY_MAX_ATTEMPTS_PER_WINDOW, limit),
            ).fetchall()
        for row in rows:
            envelope = TransferEnvelope(
                int(_row(row, "schema_version", 3)), UUID(str(_row(row, "batch_id", 1))),
                str(_row(row, "producer_id", 2)), int(_row(row, "cursor", 0)),
                int(_row(row, "cursor", 0)), utc(_row(row, "created_at", 4), "outbox.created_at"),
                int(_row(row, "record_count", 5)), int(_row(row, "uncompressed_bytes", 6)),
                "zstd", str(_row(row, "payload_sha256", 7)), bytes(_row(row, "payload", 8)),
            )
            with self.repository._connection() as connection, connection.transaction():
                # Окно скользящее, поэтому счётчик сбрасывается той же записью,
                # что и увеличивается: отдельный проход оставил бы дыру между
                # проверкой и попыткой.
                attempted = connection.execute(
                    """UPDATE ops_and_admin.transfer_outbox
                          SET state='sent',sent_at=transaction_timestamp(),
                              publish_attempts=publish_attempts+1,last_error_code=NULL,
                              attempt_window_started_at=CASE
                                  WHEN attempt_window_started_at IS NULL
                                    OR attempt_window_started_at
                                         <= transaction_timestamp()-%s*interval '1 second'
                                  THEN transaction_timestamp()
                                  ELSE attempt_window_started_at END,
                              attempt_window_count=CASE
                                  WHEN attempt_window_started_at IS NULL
                                    OR attempt_window_started_at
                                         <= transaction_timestamp()-%s*interval '1 second'
                                  THEN 1
                                  ELSE attempt_window_count+1 END
                        WHERE cursor=%s AND state IN ('sealed','sent')
                        RETURNING attempt_window_count""",
                    (RETRY_WINDOW_SECONDS, RETRY_WINDOW_SECONDS, envelope.first_cursor),
                ).fetchone()
            if attempted is None:
                continue
            window_attempt = int(_row(attempted, "attempt_window_count", 0))
            try:
                ack = self.transport.send(envelope)
                if ack.batch_id != envelope.batch_id or ack.checksum != envelope.payload_sha256:
                    raise TransferRejected("invalid_ack")
            except Exception as error:
                code = error.code if isinstance(error, TransferRejected) else "consumer_unavailable"
                # Исчерпанное окно оставляет запись pending с сохранённым
                # payload: недоступность потребителя не является неисправимой
                # ошибкой и не переводит батч в terminal.
                delay = retry_delay_seconds(window_attempt, float(self._random_unit()))
                with self.repository._connection() as connection, connection.transaction():
                    connection.execute(
                        """UPDATE ops_and_admin.transfer_outbox
                              SET last_error_code=%s,
                                  available_at=transaction_timestamp()
                                               +%s*interval '1 second'
                            WHERE cursor=%s AND state='sent'""",
                        (code, delay, envelope.first_cursor),
                    )
                continue
            with self.repository._connection() as connection, connection.transaction():
                connection.execute(
                    """UPDATE ops_and_admin.transfer_outbox
                          SET state='acknowledged',ack_receipt_id=%s,ack_checksum=%s,
                              acknowledged_at=transaction_timestamp()
                        WHERE cursor=%s AND state='sent'""",
                    (ack.receipt_id, ack.checksum, envelope.first_cursor),
                )
            delivered += 1
        self.observe()
        return delivered

    def observe(self) -> None:
        if self.metrics is None or self.repository.transfer_producer_id is None:
            return
        producer = self.repository.transfer_producer_id
        with self.repository._connection() as connection:
            row = connection.execute(
                """SELECT
                     coalesce(max(cursor),0) AS produced,
                     coalesce(max(cursor) FILTER (WHERE state='acknowledged'),0) AS acknowledged,
                     count(*) AS outbox_rows,
                     coalesce(sum(octet_length(payload)),0) AS outbox_bytes,
                     count(*) FILTER (WHERE state IN ('sealed','sent')) AS backlog_rows,
                     coalesce(sum(octet_length(payload)) FILTER (WHERE state IN ('sealed','sent')),0) AS backlog_bytes,
                     coalesce(extract(epoch FROM transaction_timestamp()-min(created_at))
                       FILTER (WHERE state IN ('sealed','sent')),0) AS oldest_age,
                     coalesce(extract(epoch FROM max(acknowledged_at-created_at)),0) AS latency,
                     coalesce(sum(greatest(publish_attempts-1,0)),0) AS retries,
                     count(*) FILTER (WHERE last_error_code='checksum_mismatch') AS checksum_failures,
                     count(*) FILTER (
                       WHERE state IN ('sealed','sent')
                         AND attempt_window_started_at IS NOT NULL
                         AND attempt_window_started_at
                               > transaction_timestamp()-%s*interval '1 second'
                         AND attempt_window_count >= %s
                     ) AS window_exhausted
                   FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
                (RETRY_WINDOW_SECONDS, RETRY_MAX_ATTEMPTS_PER_WINDOW, producer),
            ).fetchone()
            inbox = connection.execute(
                """SELECT coalesce(max(applied_cursor),0) AS applied,
                          coalesce(sum(duplicate_count),0) AS duplicates,
                          coalesce(sum(rejected_count),0) AS rejects,
                          count(*) FILTER (WHERE state='quarantined') AS quarantines,
                          coalesce(sum(record_count-accepted_count-duplicate_count-
                            deferred_count-rejected_count) FILTER (WHERE state='applied'),0)
                            AS unaccounted
                     FROM ops_and_admin.transfer_inbox WHERE producer_id=%s""",
                (producer,),
            ).fetchone()
        self.metrics.transfer(producer, {
            "last_produced_cursor": _row(row, "produced", 0),
            "last_acknowledged_cursor": _row(row, "acknowledged", 1),
            "last_applied_cursor": _row(inbox, "applied", 0),
            "outbox_rows": _row(row, "outbox_rows", 2),
            "outbox_bytes": _row(row, "outbox_bytes", 3),
            "backlog_rows": _row(row, "backlog_rows", 4),
            "backlog_bytes": _row(row, "backlog_bytes", 5),
            "oldest_backlog_age_seconds": _row(row, "oldest_age", 6),
            "batch_latency_seconds": _row(row, "latency", 7),
            "retries_total": _row(row, "retries", 8),
            "checksum_failures_total": _row(row, "checksum_failures", 9),
            "attempt_window_exhausted_rows": _row(row, "window_exhausted", 10),
            "duplicates_total": _row(inbox, "duplicates", 1),
            "rejects_total": _row(inbox, "rejects", 2),
            "quarantines_total": _row(inbox, "quarantines", 3),
            "unaccounted_records": _row(inbox, "unaccounted", 4),
        })

    def purge_acknowledged(self, *, before: datetime, limit: int = 1000) -> int:
        with self.repository._connection() as connection, connection.transaction():
            row = connection.execute(
                """WITH victims AS (
                       SELECT cursor FROM ops_and_admin.transfer_outbox
                        WHERE state='acknowledged' AND acknowledged_at<%s
                        ORDER BY cursor LIMIT %s FOR UPDATE SKIP LOCKED
                   ), deleted AS (
                       DELETE FROM ops_and_admin.transfer_outbox current
                        USING victims WHERE current.cursor=victims.cursor RETURNING 1
                   ) SELECT count(*) AS count FROM deleted""",
                (utc(before, "retention.before"), limit),
            ).fetchone()
        return int(_row(row, "count", 0))
