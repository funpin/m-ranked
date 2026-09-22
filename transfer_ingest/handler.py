"""Transport-neutral envelope intake.

The HTTP and TLS layers live in :mod:`transfer_ingest.server`; everything that
decides an outcome lives here, so the rules can be tested without sockets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import time
from typing import Any, Mapping
from uuid import UUID

from collector_target.transfer import (
    MAX_COMPRESSED_BYTES,
    TransferEnvelope,
    TransferRejected,
    _parse_time,
)


logger = logging.getLogger("transfer_ingest")

# Больше жёсткого предела протокола не читаем вовсе. Значение отдельно от
# MAX_COMPRESSED_BYTES: последний — предел одного батча, этот — предел того,
# что мы вообще готовы принять в память с провода.
MAX_WIRE_BYTES = 16 * 1024 * 1024

REQUIRED_HEADERS = (
    "x-mranked-schema-version",
    "x-mranked-batch-id",
    "x-mranked-producer-id",
    "x-mranked-first-cursor",
    "x-mranked-last-cursor",
    "x-mranked-created-at",
    "x-mranked-record-count",
    "x-mranked-uncompressed-bytes",
    "x-mranked-payload-sha256",
)


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: int
    body: Mapping[str, Any]


def _rejected(status: int, code: str) -> IngestOutcome:
    # Ответ несёт только ограниченный код. Текст исключения мог бы содержать
    # фрагмент payload или DSN, а он уходит другой стороне.
    return IngestOutcome(status, {"error": code})


def envelope_from_headers(headers: Mapping[str, str], payload: bytes) -> TransferEnvelope:
    """Rebuild the envelope the producer described in its headers."""
    missing = [name for name in REQUIRED_HEADERS if not headers.get(name, "").strip()]
    if missing:
        raise TransferRejected("missing_envelope_headers")
    try:
        schema_version = int(headers["x-mranked-schema-version"])
        batch_id = UUID(headers["x-mranked-batch-id"].strip())
        first_cursor = int(headers["x-mranked-first-cursor"])
        last_cursor = int(headers["x-mranked-last-cursor"])
        created_at = _parse_time(headers["x-mranked-created-at"].strip())
        record_count = int(headers["x-mranked-record-count"])
        uncompressed_bytes = int(headers["x-mranked-uncompressed-bytes"])
    except (ValueError, KeyError) as error:
        raise TransferRejected("malformed_envelope_headers") from error
    return TransferEnvelope(
        schema_version,
        batch_id,
        headers["x-mranked-producer-id"].strip(),
        first_cursor,
        last_cursor,
        created_at,
        record_count,
        uncompressed_bytes,
        "zstd",
        headers["x-mranked-payload-sha256"].strip().lower(),
        payload,
    )


def producer_is_authorized(
    producer_id: str, identities: tuple[str, ...],
) -> bool:
    """Whether a certificate identity may write under this producer id.

    A certificate identifies the host, while a producer id is
    ``<host>/<partition>``: one Server 1 runs an isolated worker per platform
    and they share its certificate.  Matching is therefore either exact or on a
    whole leading segment — never a bare prefix, so ``server-10`` cannot write
    as ``server-1``.
    """
    cleaned = producer_id.strip()
    return any(
        cleaned == identity or cleaned.startswith(f"{identity}/")
        for identity in identities if identity
    )


class IngestHandler:
    """Verify, durably record and apply one envelope."""

    def __init__(self, consumer: Any, *, clock: Any = None, metrics: Any = None) -> None:
        self.consumer = consumer
        self.clock = clock
        self.metrics = metrics

    def _reject(self, producer: str, status: int, code: str) -> IngestOutcome:
        if self.metrics is not None:
            try:
                self.metrics.rejected(producer, code)
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "transfer ingest metrics unavailable class=%s",
                    type(error).__name__,
                )
        return _rejected(status, code)

    def handle(
        self,
        headers: Mapping[str, str],
        payload: bytes,
        *,
        peer_producer_ids: tuple[str, ...],
    ) -> IngestOutcome:
        declared = headers.get("x-mranked-producer-id", "").strip() or "unknown"
        if len(payload) > MAX_WIRE_BYTES or len(payload) > MAX_COMPRESSED_BYTES:
            return self._reject(declared, 413, "payload_too_large")
        try:
            envelope = envelope_from_headers(headers, payload)
        except TransferRejected as error:
            return self._reject(declared, 400, error.code)

        # Сертификат удостоверяет, кем является отправитель; заголовок — лишь
        # то, кем он себя называет. Расхождение означает попытку писать от
        # чужого имени, и при факторе репликации больше единицы это тихо
        # ломает выбор победителя между производителями.
        if not producer_is_authorized(envelope.producer_id, peer_producer_ids):
            logger.warning(
                "transfer ingest identity mismatch peers=%s",
                len(peer_producer_ids),
            )
            return self._reject(declared, 403, "producer_identity_mismatch")

        began = time.monotonic()
        try:
            ack = self.consumer.receive(envelope)
        except TransferRejected as error:
            status = 409 if error.code == "batch_identity_conflict" else 400
            return self._reject(envelope.producer_id, status, error.code)
        except Exception as error:  # noqa: BLE001 - ответ несёт только код
            logger.error(
                "transfer ingest failed class=%s", type(error).__name__,
            )
            return self._reject(envelope.producer_id, 500, "ingest_failed")
        if self.metrics is not None:
            try:
                self.metrics.accepted(
                    envelope.producer_id,
                    duration=time.monotonic() - began,
                    duplicate=False,
                )
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "transfer ingest metrics unavailable class=%s",
                    type(error).__name__,
                )

        # ACK выдаётся только после durable commit в inbox: receive()
        # возвращается лишь после того, как его транзакция зафиксирована.
        return IngestOutcome(200, {
            "receiptId": str(ack.receipt_id),
            "batchId": str(ack.batch_id),
            "checksum": ack.checksum,
        })


def utc_now(clock: Any = None) -> datetime:
    from datetime import timezone
    return clock.now() if clock is not None else datetime.now(timezone.utc)
