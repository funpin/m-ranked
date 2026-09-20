"""Receiver, mTLS identity binding and the delivery retry policy."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
import ssl
from uuid import uuid4

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.transfer import (
    RETRY_BASE_SECONDS, RETRY_MAX_SECONDS, TransferAck, TransferRejected,
    retry_delay_seconds, seal_batch,
)
from transfer_ingest.handler import (
    MAX_WIRE_BYTES, IngestHandler, envelope_from_headers, producer_is_authorized,
)
from transfer_ingest.server import (
    IngestServer, build_ssl_context, producer_ids_from_certificate,
)

from transfer_pki import build_pki, issue, rogue_ca


PRODUCER = "server-1"


def _batch(partition: str = "ingest"):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    institution_id, account_id = uuid4(), uuid4()
    context = CollectionContext.create(
        Platform.TELEGRAM, f"{partition}-{uuid4()}", "ingest-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"ingest_{account_id.hex}", "public_web",
    )
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            "m:7", now, now, now, now, "text",
            {"views": 5, "reactions": 1, "comments": 0, "shares": None},
            {"kind": "ingest-test"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "ingest-integration", "1",
    )
    return CanonicalNormalizer().normalize(raw, context), context, account


def _envelope(partition: str = "ingest", cursor: int = 1):
    batch, _context, _account = _batch(partition)
    return seal_batch(batch, f"{PRODUCER}/default", cursor=cursor)


def _headers(envelope) -> dict[str, str]:
    from collector_target.transfer import _iso
    return {
        "x-mranked-schema-version": str(envelope.schema_version),
        "x-mranked-batch-id": str(envelope.batch_id),
        "x-mranked-producer-id": envelope.producer_id,
        "x-mranked-first-cursor": str(envelope.first_cursor),
        "x-mranked-last-cursor": str(envelope.last_cursor),
        "x-mranked-created-at": _iso(envelope.created_at),
        "x-mranked-record-count": str(envelope.record_count),
        "x-mranked-uncompressed-bytes": str(envelope.uncompressed_bytes),
        "x-mranked-payload-sha256": envelope.payload_sha256,
    }


class _RecordingConsumer:
    """Stands in for PostgresDataAdapter; integration covers the real one."""

    def __init__(self) -> None:
        self.seen: list = []
        self.receipts: dict = {}

    def receive(self, envelope) -> TransferAck:
        self.seen.append(envelope)
        receipt = self.receipts.setdefault(
            (envelope.producer_id, envelope.batch_id), uuid4(),
        )
        return TransferAck(receipt, envelope.batch_id, envelope.payload_sha256)


# --- identity binding -------------------------------------------------------

@pytest.mark.parametrize(
    ("producer_id", "identities", "allowed"),
    [
        ("server-1/default", ("server-1",), True),
        ("server-1", ("server-1",), True),
        ("server-1/telegram", ("server-1",), True),
        # A bare prefix must not authorise a different host.
        ("server-10/default", ("server-1",), False),
        ("server-2/default", ("server-1",), False),
        ("server-1/default", (), False),
    ],
)
def test_certificate_identity_authorises_only_its_own_producer(
    producer_id: str, identities: tuple[str, ...], allowed: bool,
) -> None:
    assert producer_is_authorized(producer_id, identities) is allowed


def test_producer_header_cannot_impersonate_another_host() -> None:
    envelope = _envelope()
    consumer = _RecordingConsumer()
    outcome = IngestHandler(consumer).handle(
        _headers(envelope), envelope.payload, peer_producer_ids=("server-9",),
    )
    assert outcome.status == 403
    assert outcome.body == {"error": "producer_identity_mismatch"}
    # Rejection happens before the consumer is reached at all.
    assert consumer.seen == []


def test_certificate_identities_cover_common_name_and_alternative_names() -> None:
    peer = {
        "subject": ((("commonName", "server-1"),),),
        "subjectAltName": (("DNS", "server-1-new"), ("IP Address", "10.0.0.1")),
    }
    assert producer_ids_from_certificate(peer) == ("server-1", "server-1-new")
    assert producer_ids_from_certificate(None) == ()


# --- bounds -----------------------------------------------------------------

def test_oversized_payload_is_refused_without_touching_the_consumer() -> None:
    envelope = _envelope()
    consumer = _RecordingConsumer()
    outcome = IngestHandler(consumer).handle(
        _headers(envelope), b"x" * (MAX_WIRE_BYTES + 1),
        peer_producer_ids=(PRODUCER,),
    )
    assert outcome.status == 413
    assert outcome.body == {"error": "payload_too_large"}
    assert consumer.seen == []


@pytest.mark.parametrize(
    ("drop", "code"),
    [
        ("x-mranked-payload-sha256", "missing_envelope_headers"),
        ("x-mranked-batch-id", "missing_envelope_headers"),
    ],
)
def test_missing_envelope_headers_have_bounded_reason_codes(
    drop: str, code: str,
) -> None:
    envelope = _envelope()
    headers = _headers(envelope)
    headers.pop(drop)
    outcome = IngestHandler(_RecordingConsumer()).handle(
        headers, envelope.payload, peer_producer_ids=(PRODUCER,),
    )
    assert outcome.status == 400
    assert outcome.body == {"error": code}


def test_malformed_header_values_do_not_leak_details() -> None:
    envelope = _envelope()
    headers = _headers(envelope)
    headers["x-mranked-record-count"] = "not-a-number"
    outcome = IngestHandler(_RecordingConsumer()).handle(
        headers, envelope.payload, peer_producer_ids=(PRODUCER,),
    )
    assert outcome.body == {"error": "malformed_envelope_headers"}


def test_checksum_mismatch_is_reported_as_a_bounded_code() -> None:
    envelope = _envelope()
    headers = _headers(envelope)
    headers["x-mranked-payload-sha256"] = "0" * 64

    class Checking:
        def receive(self, item):
            from collector_target.transfer import validate_envelope
            validate_envelope(item, accept_schema=False)
            raise AssertionError("must not be reached")

    outcome = IngestHandler(Checking()).handle(
        headers, envelope.payload, peer_producer_ids=(PRODUCER,),
    )
    assert outcome.status == 400
    assert outcome.body == {"error": "checksum_mismatch"}


def test_batch_identity_conflict_is_a_conflict_not_a_bad_request() -> None:
    envelope = _envelope()

    class Conflicting:
        def receive(self, item):
            raise TransferRejected("batch_identity_conflict")

    outcome = IngestHandler(Conflicting()).handle(
        _headers(envelope), envelope.payload, peer_producer_ids=(PRODUCER,),
    )
    assert outcome.status == 409


def test_unexpected_consumer_failure_never_echoes_the_exception() -> None:
    envelope = _envelope()

    class Exploding:
        def receive(self, item):
            raise RuntimeError(
                "dsn=postgresql://user:hunter2@db/mranked token=must-not-leak"
            )

    outcome = IngestHandler(Exploding()).handle(
        _headers(envelope), envelope.payload, peer_producer_ids=(PRODUCER,),
    )
    assert outcome.status == 500
    assert outcome.body == {"error": "ingest_failed"}
    assert "hunter2" not in json.dumps(outcome.body)
    assert "must-not-leak" not in json.dumps(outcome.body)


def test_envelope_is_rebuilt_exactly_from_its_headers() -> None:
    envelope = _envelope()
    assert envelope_from_headers(_headers(envelope), envelope.payload) == envelope


# --- retry policy -----------------------------------------------------------

def test_backoff_grows_exponentially_and_stays_within_its_bounds() -> None:
    ceilings = [retry_delay_seconds(attempt, 1.0) for attempt in range(1, 15)]
    assert ceilings[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert all(
        RETRY_BASE_SECONDS <= value <= RETRY_MAX_SECONDS for value in ceilings
    )
    assert ceilings[-1] == RETRY_MAX_SECONDS
    assert ceilings == sorted(ceilings)


def test_full_jitter_spans_the_whole_interval_and_is_reproducible() -> None:
    # Full jitter draws from [0, ceiling]: that is what spreads simultaneously
    # orphaned batches instead of releasing them as one burst.
    assert retry_delay_seconds(4, 0.0) == 0.0
    assert retry_delay_seconds(4, 0.5) == 4.0
    assert retry_delay_seconds(4, 1.0) == 8.0
    assert retry_delay_seconds(7, 0.25) == retry_delay_seconds(7, 0.25)


@pytest.mark.parametrize("bad", [0, -1])
def test_retry_delay_rejects_a_nonpositive_attempt(bad: int) -> None:
    with pytest.raises(ValueError):
        retry_delay_seconds(bad, 0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_retry_delay_rejects_a_random_unit_outside_the_interval(bad: float) -> None:
    with pytest.raises(ValueError):
        retry_delay_seconds(1, bad)


# --- real TLS ---------------------------------------------------------------

def _client_context(ca_bundle, identity=None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(ca_bundle))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    if identity is not None:
        context.load_cert_chain(str(identity.certificate), str(identity.private_key))
    return context


async def _post(
    port: int, context: ssl.SSLContext, envelope, *, path="/transfer/v1/batches",
    method="POST", producer_override: str | None = None,
) -> tuple[int, dict]:
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", port, ssl=context, server_hostname="localhost",
    )
    headers = _headers(envelope)
    if producer_override is not None:
        headers["x-mranked-producer-id"] = producer_override
    head = f"{method} {path} HTTP/1.1\r\nhost: localhost\r\n"
    head += f"content-length: {len(envelope.payload)}\r\n"
    head += "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    writer.write(head.encode("latin-1") + b"\r\n" + envelope.payload)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionError, ssl.SSLError):
        pass
    head_bytes, _, body = raw.partition(b"\r\n\r\n")
    status = int(head_bytes.split(b" ")[1])
    return status, json.loads(body) if body else {}


async def _with_server(pki, allowed, coroutine, *, consumer=None):
    consumer = consumer or _RecordingConsumer()
    server = IngestServer(IngestHandler(consumer), allowed_producers=allowed)
    context = build_ssl_context(
        str(pki.server.certificate), str(pki.server.private_key), str(pki.ca_bundle),
    )
    listener = await server.start("127.0.0.1", 0, context)
    port = listener.sockets[0].getsockname()[1]
    try:
        return await coroutine(port, consumer)
    finally:
        listener.close()
        await listener.wait_closed()


def test_real_mtls_round_trip_accepts_only_trusted_client_certificates(
    tmp_path,
) -> None:
    pki = build_pki(tmp_path / "pki")
    good = pki.issue("client-good", PRODUCER)
    other = pki.issue("client-other", "server-2")
    rogue = rogue_ca(tmp_path / "pki")
    intruder = issue(
        tmp_path / "pki", "client-rogue", PRODUCER, ca=rogue,
    )

    async def scenario(port, consumer):
        envelope = _envelope(cursor=1)

        # A trusted certificate whose identity matches the header succeeds.
        status, body = await _post(port, _client_context(pki.ca_bundle, good), envelope)
        assert status == 200
        assert body["checksum"] == envelope.payload_sha256
        first_receipt = body["receiptId"]

        # Redelivery of the same batch returns the same receipt, no new effect.
        status, repeat = await _post(
            port, _client_context(pki.ca_bundle, good), envelope,
        )
        assert status == 200
        assert repeat["receiptId"] == first_receipt
        assert repeat["checksum"] == envelope.payload_sha256

        # A trusted certificate belonging to another host cannot claim ours.
        status, body = await _post(
            port, _client_context(pki.ca_bundle, other), _envelope(cursor=2),
        )
        assert status == 403
        assert body == {"error": "producer_identity_mismatch"}

        # Wrong method and wrong path never reach the consumer.
        before = len(consumer.seen)
        status, _ = await _post(
            port, _client_context(pki.ca_bundle, good), _envelope(cursor=3),
            method="GET",
        )
        assert status == 405
        status, _ = await _post(
            port, _client_context(pki.ca_bundle, good), _envelope(cursor=4),
            path="/elsewhere",
        )
        assert status == 404
        assert len(consumer.seen) == before

        # No client certificate at all. TLS 1.3 carries client auth after the
        # server's Finished, so depending on the platform this surfaces either
        # as a transport error or as our own pre-read refusal. Both are a
        # refusal; what must never happen is the batch being accepted.
        before = len(consumer.seen)
        try:
            status, body = await _post(
                port, _client_context(pki.ca_bundle), _envelope(cursor=5),
            )
            assert status == 403
            assert body == {"error": "client_certificate_required"}
        except (ssl.SSLError, ConnectionError, OSError, IndexError):
            pass
        assert len(consumer.seen) == before

        # A certificate signed by an untrusted CA is refused by TLS itself,
        # even though its common name is the expected producer.
        try:
            status, body = await _post(
                port, _client_context(pki.ca_bundle, intruder), _envelope(cursor=6),
            )
            assert status == 403
        except (ssl.SSLError, ConnectionError, OSError, IndexError):
            pass
        assert len(consumer.seen) == before
        return True

    assert asyncio.run(_with_server(pki, (PRODUCER,), scenario))


def test_certificate_rotation_accepts_both_certificates_in_the_overlap(
    tmp_path,
) -> None:
    """A 30-day overlap is only usable if both certificates work at once."""
    pki = build_pki(tmp_path / "pki")
    expiring = pki.issue("client-old", PRODUCER)
    incoming = pki.issue("client-new", PRODUCER)

    async def scenario(port, consumer):
        for index, identity in enumerate((expiring, incoming), start=1):
            status, body = await _post(
                port, _client_context(pki.ca_bundle, identity),
                _envelope(cursor=index),
            )
            assert status == 200, body
        assert len(consumer.seen) == 2
        return True

    assert asyncio.run(_with_server(pki, (PRODUCER,), scenario))


def test_declared_length_above_the_ceiling_is_refused_before_the_body(
    tmp_path,
) -> None:
    """The limit must apply to the declared size, not to what we read."""
    pki = build_pki(tmp_path / "pki")
    good = pki.issue("client-good", PRODUCER)

    async def scenario(port, consumer):
        envelope = _envelope()
        context = _client_context(pki.ca_bundle, good)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=context, server_hostname="localhost",
        )
        head = "POST /transfer/v1/batches HTTP/1.1\r\nhost: localhost\r\n"
        head += f"content-length: {MAX_WIRE_BYTES + 1}\r\n"
        head += "".join(
            f"{name}: {value}\r\n" for name, value in _headers(envelope).items()
        )
        writer.write(head.encode("latin-1") + b"\r\n")
        await writer.drain()
        raw = await reader.read()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, ssl.SSLError):
            pass
        head_bytes, _, body = raw.partition(b"\r\n\r\n")
        assert int(head_bytes.split(b" ")[1]) == 413
        assert json.loads(body) == {"error": "payload_too_large"}
        # Nothing was read into memory and nothing reached the consumer.
        assert consumer.seen == []
        return True

    assert asyncio.run(_with_server(pki, (PRODUCER,), scenario))


def test_chunked_transfer_is_refused_because_the_limit_needs_a_length(
    tmp_path,
) -> None:
    pki = build_pki(tmp_path / "pki")
    good = pki.issue("client-good", PRODUCER)

    async def scenario(port, consumer):
        context = _client_context(pki.ca_bundle, good)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=context, server_hostname="localhost",
        )
        writer.write(
            b"POST /transfer/v1/batches HTTP/1.1\r\nhost: localhost\r\n"
            b"transfer-encoding: chunked\r\n\r\n"
        )
        await writer.drain()
        raw = await reader.read()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, ssl.SSLError):
            pass
        head_bytes, _, body = raw.partition(b"\r\n\r\n")
        assert int(head_bytes.split(b" ")[1]) == 411
        assert json.loads(body) == {"error": "content_length_required"}
        assert consumer.seen == []
        return True

    assert asyncio.run(_with_server(pki, (PRODUCER,), scenario))


def test_the_test_pki_never_escapes_its_temporary_directory(tmp_path) -> None:
    pki = build_pki(tmp_path / "pki")
    identity = pki.issue("client-good", PRODUCER)
    for path in (pki.ca_bundle, pki.server.private_key, identity.private_key):
        assert path.is_file()
        assert tmp_path in path.parents


# --- receiver metrics -------------------------------------------------------

def test_ingest_metrics_count_outcomes_and_never_label_request_content() -> None:
    from transfer_ingest.metrics import IngestMetrics

    metrics = IngestMetrics()
    envelope = _envelope()
    handler = IngestHandler(_RecordingConsumer(), metrics=metrics)

    assert handler.handle(
        _headers(envelope), envelope.payload, peer_producer_ids=(PRODUCER,),
    ).status == 200
    assert handler.handle(
        _headers(envelope), envelope.payload, peer_producer_ids=("server-9",),
    ).status == 403

    rendered = metrics.render()
    assert 'mranked_transfer_ingest_accepted_total{producer="server-1/default"} 1' in rendered
    assert 'reason="producer_identity_mismatch"' in rendered
    # A producer id comes from a verified certificate; anything else that could
    # carry request content must be collapsed rather than become a label.
    metrics.rejected("head\ner=../etc/passwd \"quote\"", "bad code")
    rendered = metrics.render()
    assert "etc/passwd" not in rendered
    assert 'producer="unknown"' in rendered
    assert 'reason="unknown"' in rendered
    for line in rendered.splitlines():
        assert "\n" not in line and line.count('"') % 2 == 0


def test_metrics_failure_never_fails_the_request() -> None:
    class Broken:
        def accepted(self, *args, **kwargs):
            raise RuntimeError("metrics volume is full")

        def rejected(self, *args, **kwargs):
            raise RuntimeError("metrics volume is full")

    envelope = _envelope()
    handler = IngestHandler(_RecordingConsumer(), metrics=Broken())
    assert handler.handle(
        _headers(envelope), envelope.payload, peer_producer_ids=(PRODUCER,),
    ).status == 200
    assert handler.handle(
        _headers(envelope), envelope.payload, peer_producer_ids=("other",),
    ).status == 403
