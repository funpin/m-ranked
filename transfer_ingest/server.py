"""mTLS listener for the transfer ingest endpoint.

The listener is deliberately not an ASGI server.  Binding ``producer_id`` to the
client certificate is a security requirement, and uvicorn does not expose the
verified peer certificate to the application.  What it costs us is a request
reader, and that reader is kept tiny on purpose: one method, one path,
mandatory ``Content-Length``, no chunked transfer, no keep-alive pipelining and
a hard byte ceiling applied before the body is read.  Anything that does not
match exactly is refused.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import ssl
import time
from typing import Any, Iterable

from operations.storage.hub import NodeRejected

from .handler import MAX_WIRE_BYTES, IngestHandler


logger = logging.getLogger("transfer_ingest")

MAX_REQUEST_LINE_BYTES = 8 * 1024
MAX_HEADER_BYTES = 32 * 1024
READ_TIMEOUT_SECONDS = 30.0
WRITE_TIMEOUT_SECONDS = 30.0
HANDSHAKE_TIMEOUT_SECONDS = 3.0
REGISTRY_TTL_SECONDS = 30.0

_REASON = {
    200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 409: "Conflict", 411: "Length Required", 412: "Precondition Failed",
    413: "Content Too Large", 431: "Request Header Fields Too Large",
    500: "Internal Server Error",
}


class _BadRequest(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def producer_ids_from_certificate(peer_cert: Any) -> tuple[str, ...]:
    """Identities a verified client certificate is allowed to claim.

    Both the subject common name and every DNS/URI subject alternative name
    count, so a certificate rotated with a new SAN keeps working during the
    overlap window without reissuing the producer's configuration.
    """
    if not peer_cert:
        return ()
    identities: list[str] = []
    for rdn in peer_cert.get("subject", ()):  # type: ignore[union-attr]
        for key, value in rdn:
            if key == "commonName" and value:
                identities.append(str(value))
    for key, value in peer_cert.get("subjectAltName", ()):  # type: ignore[union-attr]
        if key in {"DNS", "URI"} and value:
            identities.append(str(value))
    return tuple(dict.fromkeys(identities))


def build_ssl_context(
    certificate: str, private_key: str, ca_bundle: str,
) -> ssl.SSLContext:
    """TLS 1.3 with a mandatory, CA-verified client certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=ca_bundle)
    context.load_cert_chain(certificate, private_key)
    return context


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    target: str
    headers: dict[str, str]


async def _read_head(reader: asyncio.StreamReader) -> _Request:
    try:
        line = await reader.readuntil(b"\r\n")
    except asyncio.LimitOverrunError as error:
        raise _BadRequest(431, "request_line_too_long") from error
    except (asyncio.IncompleteReadError, ConnectionError) as error:
        raise _BadRequest(400, "incomplete_request") from error
    if len(line) > MAX_REQUEST_LINE_BYTES:
        raise _BadRequest(431, "request_line_too_long")
    parts = line.decode("latin-1").rstrip("\r\n").split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise _BadRequest(400, "malformed_request_line")

    headers: dict[str, str] = {}
    consumed = 0
    while True:
        try:
            raw = await reader.readuntil(b"\r\n")
        except asyncio.LimitOverrunError as error:
            raise _BadRequest(431, "header_too_long") from error
        except (asyncio.IncompleteReadError, ConnectionError) as error:
            raise _BadRequest(400, "incomplete_request") from error
        if raw in (b"\r\n", b"\n"):
            break
        consumed += len(raw)
        if consumed > MAX_HEADER_BYTES:
            raise _BadRequest(431, "headers_too_large")
        name, separator, value = raw.decode("latin-1").rstrip("\r\n").partition(":")
        if not separator:
            raise _BadRequest(400, "malformed_header")
        headers[name.strip().lower()] = value.strip()
    return _Request(parts[0], parts[1], headers)


async def _read_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> bytes:
    if "transfer-encoding" in headers:
        # Без Content-Length предел нельзя применить до чтения, а именно это
        # и требуется: отказ должен случиться раньше аллокации.
        raise _BadRequest(411, "content_length_required")
    raw_length = headers.get("content-length", "")
    if not raw_length.isdigit():
        raise _BadRequest(411, "content_length_required")
    length = int(raw_length)
    if length > MAX_WIRE_BYTES:
        raise _BadRequest(413, "payload_too_large")
    try:
        return await reader.readexactly(length) if length else b""
    except (asyncio.IncompleteReadError, ConnectionError) as error:
        raise _BadRequest(400, "incomplete_body") from error


def _binary_response(status: int, data: bytes) -> bytes:
    head = (
        f"HTTP/1.1 {status} {_REASON.get(status, 'Error')}\r\n"
        "content-type: application/octet-stream\r\n"
        f"content-length: {len(data)}\r\n"
        "connection: close\r\n"
        "cache-control: no-store\r\n"
        "\r\n"
    ).encode("latin-1")
    return head + data


class _NodeDone(Exception):
    """Ответ узловой точки готов; несёт его мимо разбора пачки замеров."""

    def __init__(self, status: int, body: Any, binary: bytes | None):
        super().__init__(status)
        self.status, self.body, self.binary = status, body, binary


def _response(status: int, body: Any) -> bytes:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    head = (
        f"HTTP/1.1 {status} {_REASON.get(status, 'Error')}\r\n"
        "content-type: application/json\r\n"
        f"content-length: {len(encoded)}\r\n"
        "connection: close\r\n"
        "cache-control: no-store\r\n"
        "\r\n"
    ).encode("latin-1")
    return head + encoded


class IngestServer:
    def __init__(
        self,
        handler: IngestHandler,
        *,
        path: str = "/transfer/v1/batches",
        allowed_producers: Iterable[str] | None = None,
        node_hub: Any = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.handler = handler
        self.path = path
        self._allowed = tuple(allowed_producers) if allowed_producers else ()
        # Узлы из реестра серверов (ADR-016): агенты хранилища и сборщики,
        # подключённые из панели без правки окружения приёмника.
        self.node_hub = node_hub
        self._clock = clock
        self._registry: tuple[str, ...] = ()
        self._registry_at = float("-inf")

    def _allowed_now(self) -> tuple[str, ...]:
        if not self._allowed:
            return ()
        if self.node_hub is not None and self._clock() - self._registry_at >= REGISTRY_TTL_SECONDS:
            try:
                self._registry = self.node_hub.allowed_producers()
            except Exception as error:  # noqa: BLE001 — остаётся прежний список
                logger.warning("node registry unavailable class=%s", type(error).__name__)
            self._registry_at = self._clock()
        return self._allowed + self._registry

    async def _serve_node(self, request: "_Request", reader: asyncio.StreamReader,
                          identities: tuple[str, ...]) -> tuple[int, Any, bytes | None]:
        target, _, query = request.target.partition("?")
        params = dict(item.partition("=")[::2] for item in query.split("&") if item)
        parts = target.strip("/").split("/")
        hub = self.node_hub
        if request.method == "POST" and parts == ["node", "v1", "report"]:
            body = await asyncio.wait_for(_read_body(reader, request.headers), timeout=READ_TIMEOUT_SECONDS)
            outcome = await asyncio.to_thread(hub.report, identities, body)
        elif len(parts) == 4 and parts[:3] == ["node", "v1", "objects"] and request.method == "GET":
            try:
                offset, length = int(params.get("offset", "")), int(params.get("length", ""))
            except ValueError as error:
                raise _BadRequest(400, "bad_range") from error
            outcome = await asyncio.to_thread(hub.read_chunk, identities, parts[3], offset, length)
        elif len(parts) == 4 and parts[:3] == ["node", "v1", "objects"] and request.method == "PUT":
            try:
                offset = int(params.get("offset", ""))
            except ValueError as error:
                raise _BadRequest(400, "bad_offset") from error
            body = await asyncio.wait_for(_read_body(reader, request.headers), timeout=READ_TIMEOUT_SECONDS)
            outcome = await asyncio.to_thread(hub.write_chunk, identities, parts[3], offset, body)
        elif len(parts) == 5 and parts[:3] == ["node", "v1", "objects"] and parts[4] == "commit" \
                and request.method == "POST":
            await asyncio.wait_for(_read_body(reader, request.headers), timeout=READ_TIMEOUT_SECONDS)
            outcome = await asyncio.to_thread(hub.commit, identities, parts[3])
        else:
            return 404, {"error": "unknown_endpoint"}, None
        return outcome.status, outcome.body, outcome.binary

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        status, body = 500, {"error": "ingest_failed"}
        binary: bytes | None = None
        try:
            ssl_object = writer.get_extra_info("ssl_object")
            peer_cert = ssl_object.getpeercert() if ssl_object is not None else None
            # CERT_REQUIRED is not enough on its own: in TLS 1.3 the client
            # certificate arrives after the server's Finished, so a client that
            # sends none can still reach the application before OpenSSL fails
            # the session.  Refuse it here, before a single byte is read.
            if not peer_cert:
                raise _BadRequest(403, "client_certificate_required")
            certificate_ids = producer_ids_from_certificate(peer_cert)
            allowed = self._allowed_now()
            peer_ids = (tuple(item for item in certificate_ids if item in allowed)
                        if allowed else certificate_ids)
            request = await asyncio.wait_for(
                _read_head(reader), timeout=READ_TIMEOUT_SECONDS,
            )
            if request.target.startswith("/node/") and self.node_hub is not None:
                try:
                    status, body, binary = await self._serve_node(request, reader, certificate_ids)
                except NodeRejected as error:
                    status, body, binary = error.status, {"error": error.code}, None
                raise _NodeDone(status, body, binary)
            payload = await asyncio.wait_for(
                _read_body(reader, request.headers), timeout=READ_TIMEOUT_SECONDS,
            )
            if request.method != "POST":
                status, body = 405, {"error": "method_not_allowed"}
            elif request.target.split("?")[0] != self.path:
                status, body = 404, {"error": "unknown_endpoint"}
            else:
                outcome = await asyncio.to_thread(
                    self.handler.handle,
                    request.headers,
                    payload,
                    peer_producer_ids=peer_ids,
                )
                status, body = outcome.status, dict(outcome.body)
        except _NodeDone as done:
            status, body, binary = done.status, done.body, done.binary
        except _BadRequest as error:
            status, body = error.status, {"error": error.code}
        except asyncio.TimeoutError:
            status, body = 400, {"error": "request_timeout"}
        except Exception as error:  # noqa: BLE001 - наружу уходит только код
            logger.error("transfer ingest error class=%s", type(error).__name__)
            status, body = 500, {"error": "ingest_failed"}
        try:
            writer.write(_binary_response(status, binary) if binary is not None else _response(status, body))
            await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_SECONDS)
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError):
                pass

    async def start(
        self, host: str, port: int, context: ssl.SSLContext,
    ) -> asyncio.Server:
        return await asyncio.start_server(
            self._serve, host, port, ssl=context,
            ssl_handshake_timeout=HANDSHAKE_TIMEOUT_SECONDS,
            limit=MAX_HEADER_BYTES,
        )
