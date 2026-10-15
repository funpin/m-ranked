"""Справочник Сервера 2 для сборщиков Сервера 1: доставка без базы (0082).

Правила применения проверяет tests/test_catalog_sync_postgres.py; здесь —
отпечаток, ритм, отказоустойчивость и настоящий mTLS-маршрут.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json

import pytest

from collector_target import transfer_sender
from collector_target.catalog_sync import (
    CATALOG_PATH, CatalogSnapshotSource, CatalogSync, catalog_endpoint, metrics_lines,
)
from collector_target.transfer import HttpsMtlsTransport, InProcessTransport
from transfer_ingest.handler import IngestHandler
from transfer_ingest.server import IngestServer, build_ssl_context

from transfer_pki import build_pki


SNAPSHOT = {"version": 1, "institutions": [{"id": "i"}], "accounts": [{"id": "a"}]}
SNAPSHOT_TEXT = json.dumps(SNAPSHOT)
DIGEST = hashlib.sha256(SNAPSHOT_TEXT.encode()).hexdigest()


class _Connection:
    def __init__(self, log: list, result: dict | None = None, fail: bool = False):
        self.log, self.result, self.fail = log, result or {}, fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        if self.fail:
            raise RuntimeError("lock timeout")
        return self

    def fetchone(self):
        sql = self.log[-1][0]
        if "catalog_sync_snapshot" in sql:
            return {"snapshot": SNAPSHOT_TEXT}
        return {"result": json.dumps(self.result)}


def test_catalog_endpoint_is_the_ingest_origin_with_its_own_path() -> None:
    assert catalog_endpoint("https://s2.example:8443/transfer/v1/batches") == (
        "https://s2.example:8443" + CATALOG_PATH
    )
    for bad in ("http://s2.example/transfer", "https://user:pw@s2.example/x", "s2.example"):
        with pytest.raises(ValueError):
            catalog_endpoint(bad)


def test_source_sends_the_snapshot_only_when_the_digest_differs() -> None:
    log: list = []
    source = CatalogSnapshotSource(lambda: _Connection(log))

    full = json.loads(source.respond(None))
    assert full == {"digest": DIGEST, "snapshot": SNAPSHOT}
    assert json.loads(source.respond("0" * 64)) == full
    assert json.loads(source.respond(DIGEST.upper())) == {"digest": DIGEST, "unchanged": True}
    # Мусор вместо отпечатка не равен ничему.
    assert "snapshot" in json.loads(source.respond("not-a-digest"))


def test_sync_applies_a_new_snapshot_once_and_skips_the_database_while_unchanged() -> None:
    log: list = []
    source = CatalogSnapshotSource(lambda: _Connection([]))
    asked: list = []

    def fetch(known):
        asked.append(known)
        return source.respond(known)

    sync = CatalogSync(
        lambda: _Connection(log, {"accountsInserted": 5, "accountConflicts": 0}),
        fetch, wall_clock=lambda: 1234.0,
    )
    assert sync.run_once() == {"accountsInserted": 5, "accountConflicts": 0}
    applied = [params for sql, params in log if "apply_catalog_sync" in sql]
    assert len(applied) == 1 and json.loads(applied[0][0]) == SNAPSHOT
    assert sync.digest == DIGEST

    assert sync.run_once() == {}
    assert asked == [None, DIGEST]
    assert len([sql for sql, _ in log if "apply_catalog_sync" in sql]) == 1
    assert sync.stats.applied_total == 1
    assert sync.stats.last_success_unix == 1234.0


def test_a_failed_apply_keeps_the_old_digest_so_the_next_pass_retries() -> None:
    source = CatalogSnapshotSource(lambda: _Connection([]))
    failing = CatalogSync(lambda: _Connection([], fail=True), source.respond, clock=lambda: 0.0)

    assert failing.run_if_due() is None
    assert failing.digest is None
    assert failing.stats.failures_total == 1
    assert failing.stats.last_success_unix == 0.0


def test_sync_runs_on_its_own_interval() -> None:
    now = [0.0]
    calls: list = []
    sync = CatalogSync(
        lambda: _Connection([]), lambda known: calls.append(known) or json.dumps(
            {"digest": DIGEST, "snapshot": SNAPSHOT}).encode(),
        interval_seconds=300, clock=lambda: now[0],
    )
    sync.run_if_due()
    now[0] = 299.0
    assert sync.run_if_due() is None
    now[0] = 300.0
    sync.run_if_due()
    assert len(calls) == 2


@pytest.mark.parametrize("answer", [b"[]", b'{"digest":"x"}', json.dumps({"digest": DIGEST}).encode(),
                                    b"not json"])
def test_malformed_answers_count_as_failures_and_never_reach_the_database(answer) -> None:
    log: list = []
    sync = CatalogSync(lambda: _Connection(log), lambda known: answer)
    assert sync.run_if_due() is None
    assert sync.stats.failures_total == 1
    assert log == []


def test_conflicts_are_published_as_a_metric() -> None:
    sync = CatalogSync(
        lambda: _Connection([], {"accountConflicts": 2}),
        CatalogSnapshotSource(lambda: _Connection([])).respond,
    )
    sync.run_once()
    lines = metrics_lines(sync.stats)
    assert "mranked_catalog_sync_account_conflicts 2" in lines
    assert "mranked_catalog_sync_applied_total 1" in lines


def test_profile_a_and_a_zero_interval_do_not_sync(monkeypatch) -> None:
    class Repository:
        def _connection(self):
            raise AssertionError("not used")

    assert transfer_sender.build_catalog_sync(Repository(), InProcessTransport(None)) is None
    transport = HttpsMtlsTransport(
        "https://s2.example:8443/transfer/v1/batches",
        certificate="c", private_key="k", ca_bundle="ca",
    )
    monkeypatch.setenv("COLLECTOR_CATALOG_SYNC_INTERVAL_SECONDS", "0")
    assert transfer_sender.build_catalog_sync(Repository(), transport) is None
    monkeypatch.setenv("COLLECTOR_CATALOG_SYNC_INTERVAL_SECONDS", "600")
    sync = transfer_sender.build_catalog_sync(Repository(), transport)
    assert sync is not None and sync.interval_seconds == 600


# --- real mTLS ----------------------------------------------------------------

class _Consumer:
    def receive(self, envelope):  # pragma: no cover - not reached
        raise AssertionError("catalog requests never reach the batch consumer")


def test_real_mtls_catalog_route_serves_only_allowed_producers(tmp_path) -> None:
    pki = build_pki(tmp_path / "pki")
    good = pki.issue("client-good", "server-1")
    other = pki.issue("client-other", "server-9")
    source = CatalogSnapshotSource(lambda: _Connection([]))

    def transport(identity) -> HttpsMtlsTransport:
        return HttpsMtlsTransport(
            "https://127.0.0.1:1/transfer/v1/batches",
            certificate=str(identity.certificate), private_key=str(identity.private_key),
            ca_bundle=str(pki.ca_bundle),
        )

    async def scenario() -> None:
        server = IngestServer(IngestHandler(_Consumer()), allowed_producers=("server-1",),
                              catalog=source)
        context = build_ssl_context(
            str(pki.server.certificate), str(pki.server.private_key), str(pki.ca_bundle),
        )
        listener = await server.start("127.0.0.1", 0, context)
        port = listener.sockets[0].getsockname()[1]
        url = f"https://127.0.0.1:{port}{CATALOG_PATH}"
        client = transport(good)
        try:
            body = await asyncio.to_thread(client.get_bytes, url, params={}, limit=1 << 20)
            assert json.loads(body) == {"digest": DIGEST, "snapshot": SNAPSHOT}
            body = await asyncio.to_thread(client.get_bytes, url, params={"known": DIGEST}, limit=1 << 20)
            assert json.loads(body) == {"digest": DIGEST, "unchanged": True}
            # Ответ больше предела не дочитывается.
            with pytest.raises(ValueError):
                await asyncio.to_thread(client.get_bytes, url, params={}, limit=10)
            # Сертификат, которому слать пачки нельзя, снимка не получает.
            stranger = transport(other)
            import httpx
            with pytest.raises(httpx.HTTPStatusError) as refused:
                await asyncio.to_thread(stranger.get_bytes, url, params={}, limit=1 << 20)
            assert refused.value.response.status_code == 403
            stranger.close()
            with pytest.raises(httpx.HTTPStatusError) as missing:
                await asyncio.to_thread(
                    client.get_bytes, f"https://127.0.0.1:{port}/catalog/v1/other",
                    params={}, limit=1 << 20,
                )
            assert missing.value.response.status_code == 404
        finally:
            client.close()
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())
