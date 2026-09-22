from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.transfer import (
    HARD_MAX_ENVELOPE_BYTES,
    HttpsMtlsTransport,
    InProcessTransport,
    MAX_COMPRESSION_RATIO,
    TransferAck,
    TransferEnvelope,
    TransferRejected,
    _validate_value,
    decode_events,
    seal_batch,
    validate_envelope,
    with_cursor,
)


def _batch(*, source: dict | None = None):
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    account = AccountRef(
        uuid4(), uuid4(), Platform.TELEGRAM, "channel", "public_web",
        current_username="channel",
    )
    context = CollectionContext.create(
        Platform.TELEGRAM, "default", "test-v1", now, now,
    )
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            "42", now, now, now, now, "text",
            {"views": 1, "reactions": 2, "comments": 3, "shares": None},
            source or {"kind": "test"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "test", "1",
    )
    return CanonicalNormalizer().normalize(raw, context)


def test_envelope_round_trip_and_batch_id_are_deterministic() -> None:
    batch = _batch()
    first = seal_batch(batch, "server-1/default")
    second = seal_batch(batch, "server-1/default")
    assert first.batch_id == second.batch_id
    assert first.payload == second.payload
    decoded = decode_events(with_cursor(first, 11))
    assert decoded == (batch,)


def test_in_process_transport_returns_consumer_ack() -> None:
    envelope = with_cursor(seal_batch(_batch(), "server-1/default"), 1)

    class Consumer:
        def receive(self, value):
            return TransferAck(uuid4(), value.batch_id, value.payload_sha256)

    ack = InProcessTransport(Consumer()).send(envelope)
    assert ack.batch_id == envelope.batch_id


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda item: replace(item, payload=item.payload + b"broken"), "checksum_mismatch"),
        (lambda item: replace(item, schema_version=2), "incompatible_schema"),
        (lambda item: replace(item, record_count=501), "record_count_exceeded"),
        (lambda item: replace(item, uncompressed_bytes=len(item.payload) * (MAX_COMPRESSION_RATIO + 1)), "compression_ratio_exceeded"),
        (lambda item: replace(item, payload_sha256="x" * 64), "invalid_checksum"),
    ],
)
def test_envelope_boundaries_have_bounded_reason_codes(change, code: str) -> None:
    envelope = with_cursor(seal_batch(_batch(), "server-1/default"), 1)
    with pytest.raises(TransferRejected) as raised:
        validate_envelope(change(envelope))
    assert raised.value.code == code


def test_hard_wire_limit_is_checked_before_checksum() -> None:
    envelope = with_cursor(seal_batch(_batch(), "server-1/default"), 1)
    oversized = replace(envelope, payload=b"x" * HARD_MAX_ENVELOPE_BYTES)
    with pytest.raises(TransferRejected) as raised:
        validate_envelope(oversized)
    assert raised.value.code == "envelope_too_large"


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ({"value": "x" * 262_145}, "string_length_exceeded"),
        ({"value": 9_223_372_036_854_775_808}, "numeric_range_exceeded"),
        ({"value": [0] * 10_001}, "collection_count_exceeded"),
        ({"value": [[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]}, "nesting_exceeded"),
    ],
)
def test_decoded_value_bounds_have_bounded_reason_codes(value, code: str) -> None:
    with pytest.raises(TransferRejected) as raised:
        _validate_value(value)
    assert raised.value.code == code


def test_sensitive_source_values_are_redacted_before_envelope() -> None:
    secrets = {
        "access_token": "tok-secret", "cookie": "sid=secret",
        "phone": "+79990001122", "session": "secret-session",
        "dsn": "postgresql://user:password@db/mranked",
    }
    envelope = with_cursor(seal_batch(_batch(source=secrets), "server-1/default"), 1)
    decoded = decode_events(envelope)
    serialized = repr(decoded)
    for secret in secrets.values():
        assert secret not in serialized
    assert all(secret.encode() not in envelope.payload for secret in secrets.values())


def test_https_mtls_skeleton_rejects_unsafe_configuration() -> None:
    with pytest.raises(ValueError):
        HttpsMtlsTransport(
            "http://ready.invalid/transfer", certificate="cert",
            private_key="key", ca_bundle="ca",
        )
    with pytest.raises(ValueError):
        HttpsMtlsTransport(
            "https://user:password@ready.invalid/transfer", certificate="cert",
            private_key="key", ca_bundle="ca",
        )
    sender = HttpsMtlsTransport(
        "https://ready.invalid/transfer", certificate="missing-cert",
        private_key="missing-key", ca_bundle="missing-ca",
    )
    envelope = with_cursor(seal_batch(_batch(), "server-1/default"), 1)
    with pytest.raises(TransferRejected, match="envelope_too_large"):
        sender.send(replace(envelope, payload=b"x" * HARD_MAX_ENVELOPE_BYTES))
