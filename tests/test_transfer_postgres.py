from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4, uuid5

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawAccountObservation, RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository
from collector_target.transfer import (
    InProcessTransport, PostgresDataAdapter, PostgresTransferProducer,
    TRANSFER_NAMESPACE, TransferRejected, seal_batch,
)


def _dsn(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def test_profile_a_transfer_is_durable_idempotent_and_recovers_lost_ack() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin_dsn = _dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN")
    admin = psycopg.connect(admin_dsn, autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"transfer-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"transfer_{account_id.hex}", "public_web",
    )
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            "m:42", now, now, now, now, "text",
            {"views": 10, "reactions": 2, "comments": 1, "shares": None},
            {"access_token": "must-never-cross", "kind": "integration"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "transfer-integration", "1",
    )
    batch = CanonicalNormalizer().normalize(raw, context)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )
    adapter = PostgresDataAdapter(repository)

    class LoseFirstAck:
        calls = 0

        def send(self, envelope):
            self.calls += 1
            ack = adapter.receive(envelope)
            if self.calls == 1:
                raise TimeoutError("simulated ACK loss")
            return ack

    sender = PostgresTransferProducer(repository, LoseFirstAck())
    repository.configure_transfer_sender(sender)
    try:
        _reset_transfer(admin)
        admin.execute(
            "INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
            (institution_id, f"transfer integration {institution_id}"),
        )
        admin.execute(
            """INSERT INTO catalog.platform_account(
                   id,institution_id,platform,canonical_external_id,access_mode
               ) VALUES (%s,%s,'telegram',%s,'public_web')""",
            (account_id, institution_id, account.canonical_external_id),
        )
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        first = repository.persist_account_batch(batch)
        assert first.revision_id is not None

        outbox = admin.execute(
            """SELECT cursor,batch_id,state,publish_attempts,payload,ack_receipt_id
                 FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        assert outbox["state"] == "sent"
        assert outbox["publish_attempts"] == 1
        assert b"must-never-cross" not in bytes(outbox["payload"])
        inbox = admin.execute(
            """SELECT receipt_id,state,accepted_count,duplicate_count,applied_cursor
                 FROM ops_and_admin.transfer_inbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        assert inbox["state"] == "applied"
        assert inbox["accepted_count"] == 0
        assert inbox["duplicate_count"] == 1
        assert inbox["applied_cursor"] == outbox["cursor"]

        admin.execute(
            "UPDATE ops_and_admin.transfer_outbox SET available_at=transaction_timestamp() WHERE cursor=%s",
            (outbox["cursor"],),
        )
        # A new producer instance models restart after the lost ACK.
        restarted_adapter = PostgresDataAdapter(repository)
        restarted = PostgresTransferProducer(
            repository, InProcessTransport(restarted_adapter),
        )
        assert restarted.deliver_pending() == 1
        acknowledged = admin.execute(
            """SELECT state,publish_attempts,ack_receipt_id,ack_checksum
                 FROM ops_and_admin.transfer_outbox WHERE cursor=%s""",
            (outbox["cursor"],),
        ).fetchone()
        assert acknowledged["state"] == "acknowledged"
        assert acknowledged["publish_attempts"] == 2
        assert acknowledged["ack_receipt_id"] == inbox["receipt_id"]

        before = admin.execute(
            """SELECT
                 (SELECT count(*) FROM analytics.dataset_revision WHERE source_run_id=%s) AS revisions,
                 (SELECT count(*) FROM ingest.publication_metric_snapshot WHERE publication_id=%s) AS snapshots""",
            (context.run_id, batch.publications[0].id),
        ).fetchone()
        retry = repository.persist_account_batch(batch)
        after = admin.execute(
            """SELECT
                 (SELECT count(*) FROM analytics.dataset_revision WHERE source_run_id=%s) AS revisions,
                 (SELECT count(*) FROM ingest.publication_metric_snapshot WHERE publication_id=%s) AS snapshots,
                 (SELECT count(*) FROM ops_and_admin.transfer_outbox WHERE producer_id=%s) AS batches""",
            (context.run_id, batch.publications[0].id, producer_id),
        ).fetchone()
        assert retry.revision_id is None
        assert after["revisions"] == before["revisions"] == 1
        assert after["snapshots"] == before["snapshots"]
        assert after["batches"] == 1

        # A later batch followed by reverse-order replay converges to the same
        # latest state and creates no additional revision.
        later_at = now.replace(minute=(now.minute + 1) % 60)
        if later_at <= now:
            from datetime import timedelta
            later_at = now + timedelta(minutes=1)
        later_publication = replace(
            raw.publications[0], observed_at=later_at, collected_at=later_at,
            metrics={"views": 20, "reactions": 3, "comments": 1, "shares": None},
        )
        later_batch = CanonicalNormalizer().normalize(
            replace(raw, publications=(later_publication,)), context,
        )
        later_result = repository.persist_account_batch(later_batch)
        assert later_result.revision_id is not None
        latest_before_reorder = admin.execute(
            """SELECT views_count,dataset_revision_id FROM analytics.publication_latest
                WHERE publication_id=%s""",
            (batch.publications[0].id,),
        ).fetchone()
        revisions_before_reorder = admin.execute(
            "SELECT count(*) AS count FROM analytics.dataset_revision WHERE source_run_id=%s",
            (context.run_id,),
        ).fetchone()["count"]
        ordered_rows = admin.execute(
            """SELECT cursor,batch_id,producer_id,schema_version,created_at,
                      record_count,uncompressed_bytes,payload_sha256,payload
                 FROM ops_and_admin.transfer_outbox WHERE producer_id=%s ORDER BY cursor""",
            (producer_id,),
        ).fetchall()
        from collector_target.transfer import TransferEnvelope
        ordered_envelopes = [TransferEnvelope(
            item["schema_version"], item["batch_id"], f"{producer_id}/reorder",
            item["cursor"], item["cursor"], item["created_at"], item["record_count"],
            item["uncompressed_bytes"], "zstd", item["payload_sha256"], bytes(item["payload"]),
        ) for item in ordered_rows]
        for item in reversed(ordered_envelopes):
            restarted_adapter.receive(item)
        assert admin.execute(
            """SELECT views_count,dataset_revision_id FROM analytics.publication_latest
                WHERE publication_id=%s""",
            (batch.publications[0].id,),
        ).fetchone() == latest_before_reorder
        assert admin.execute(
            "SELECT count(*) AS count FROM analytics.dataset_revision WHERE source_run_id=%s",
            (context.run_id,),
        ).fetchone()["count"] == revisions_before_reorder

        # Corruption is rejected before inbox work.
        inbox_count = admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_inbox",
        ).fetchone()["count"]
        envelope = restarted.transport.consumer.receive  # keep consumer strongly referenced
        del envelope
        row = admin.execute(
            """SELECT cursor,batch_id,producer_id,schema_version,created_at,
                      record_count,uncompressed_bytes,payload_sha256,payload
                 FROM ops_and_admin.transfer_outbox WHERE cursor=%s""",
            (outbox["cursor"],),
        ).fetchone()
        stored = TransferEnvelope(
            row["schema_version"], row["batch_id"], row["producer_id"], row["cursor"], row["cursor"],
            row["created_at"], row["record_count"], row["uncompressed_bytes"], "zstd",
            row["payload_sha256"], bytes(row["payload"]),
        )
        with pytest.raises(TransferRejected) as corrupt:
            adapter.receive(replace(stored, payload=stored.payload + b"corrupt"))
        assert corrupt.value.code == "checksum_mismatch"
        assert admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_inbox",
        ).fetchone()["count"] == inbox_count

        incompatible = replace(
            stored, schema_version=2,
            batch_id=uuid5(TRANSFER_NAMESPACE, f"schema-2|{stored.batch_id}"),
        )
        adapter.receive(incompatible)
        quarantined = admin.execute(
            """SELECT state,reason_code,applied_cursor,payload FROM ops_and_admin.transfer_inbox
                WHERE producer_id=%s AND batch_id=%s""",
            (producer_id, incompatible.batch_id),
        ).fetchone()
        assert quarantined["state"] == "quarantined"
        assert quarantined["reason_code"] == "incompatible_schema"
        assert quarantined["applied_cursor"] is None
        assert quarantined["payload"] is None

        replay = replace(
            stored, producer_id=f"{producer_id}/replay",
            batch_id=uuid5(TRANSFER_NAMESPACE, f"replay|{stored.batch_id}"),
        )
        replay_ack = adapter.receive(replay)
        replay_again = adapter.receive(replay)
        assert replay_ack == replay_again
        replay_row = admin.execute(
            """SELECT state,accepted_count,duplicate_count,applied_cursor
                 FROM ops_and_admin.transfer_inbox WHERE receipt_id=%s""",
            (replay_ack.receipt_id,),
        ).fetchone()
        assert replay_row == {
            "state": "applied", "accepted_count": 0, "duplicate_count": 1,
            "applied_cursor": stored.last_cursor,
        }
    finally:
        repository.close()
        admin.close()


def _reset_transfer(admin) -> None:
    """Start every transfer test from an empty ledger.

    ``deliver_pending`` drains the globally oldest sealed batch first, which is
    the behaviour the failure matrix asks for.  It also means a batch left over
    by an earlier test would be delivered instead of the one under test, so the
    assertions below only hold against a clean ledger.
    """
    admin.execute("DELETE FROM ops_and_admin.transfer_inbox_event")
    admin.execute("DELETE FROM ops_and_admin.transfer_inbox")
    admin.execute("DELETE FROM ops_and_admin.transfer_outbox")


def _seed_account(admin, institution_id, account_id, canonical_external_id) -> None:
    admin.execute(
        "INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
        (institution_id, f"transfer integration {institution_id}"),
    )
    admin.execute(
        """INSERT INTO catalog.platform_account(
               id,institution_id,platform,canonical_external_id,access_mode
           ) VALUES (%s,%s,'telegram',%s,'public_web')""",
        (account_id, institution_id, canonical_external_id),
    )


def _one_publication_batch(context, account, now):
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            "m:42", now, now, now, now, "text",
            {"views": 10, "reactions": 2, "comments": 1, "shares": None},
            {"kind": "integration"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "transfer-integration", "1",
    )
    return CanonicalNormalizer().normalize(raw, context)


def test_consumer_outage_retains_the_batch_and_never_discards_it() -> None:
    """S2 down: the sealed batch stays deliverable and keeps its payload.

    The producer must not treat an unreachable consumer as a terminal failure —
    an outage that silently dropped unacknowledged batches would lose exactly
    the measurements the transfer exists to protect.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"outage-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"outage_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )
    adapter = PostgresDataAdapter(repository)

    class Outage:
        online = False

        def send(self, envelope):
            if not self.online:
                raise ConnectionError("simulated consumer outage")
            return adapter.receive(envelope)

    transport = Outage()
    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, transport),
    )
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        repository.persist_account_batch(batch)

        offline = admin.execute(
            """SELECT state,last_error_code,publish_attempts,payload,
                      available_at>transaction_timestamp() AS deferred
                 FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        # Delivery failed, yet nothing is terminal and the bytes survive.
        assert offline["state"] == "sent"
        assert offline["last_error_code"] == "consumer_unavailable"
        assert offline["publish_attempts"] == 1
        assert offline["payload"] is not None
        assert offline["deferred"] is True
        assert admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_inbox WHERE producer_id=%s",
            (producer_id,),
        ).fetchone()["count"] == 0

        # The link returns; a later drain delivers the very same batch.
        transport.online = True
        admin.execute(
            """UPDATE ops_and_admin.transfer_outbox
                  SET available_at=transaction_timestamp()
                WHERE producer_id=%s""",
            (producer_id,),
        )
        recovered = PostgresTransferProducer(repository, transport)
        assert recovered.deliver_pending() == 1
        settled = admin.execute(
            """SELECT state,last_error_code,publish_attempts
                 FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        assert settled["state"] == "acknowledged"
        assert settled["last_error_code"] is None
        assert settled["publish_attempts"] == 2
    finally:
        repository.close()
        admin.close()


def test_consumer_restart_resumes_an_interrupted_apply() -> None:
    """A consumer that died mid-apply resumes without a second effect."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"restart-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"restart_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )
    adapter = PostgresDataAdapter(repository)
    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, InProcessTransport(adapter)),
    )
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        repository.persist_account_batch(batch)

        receipt = admin.execute(
            "SELECT receipt_id FROM ops_and_admin.transfer_inbox WHERE producer_id=%s",
            (producer_id,),
        ).fetchone()["receipt_id"]
        before = admin.execute(
            """SELECT (SELECT count(*) FROM ingest.publication_metric_snapshot) AS snapshots,
                      (SELECT count(*) FROM analytics.dataset_revision) AS revisions"""
        ).fetchone()

        # Model a process that died between claiming and finishing the apply.
        admin.execute(
            """UPDATE ops_and_admin.transfer_inbox
                  SET state='applying',applied_cursor=NULL
                WHERE receipt_id=%s""",
            (receipt,),
        )
        PostgresDataAdapter(repository).apply(receipt)

        after = admin.execute(
            """SELECT (SELECT count(*) FROM ingest.publication_metric_snapshot) AS snapshots,
                      (SELECT count(*) FROM analytics.dataset_revision) AS revisions"""
        ).fetchone()
        resumed = admin.execute(
            """SELECT state,duplicate_count,applied_cursor
                 FROM ops_and_admin.transfer_inbox WHERE receipt_id=%s""",
            (receipt,),
        ).fetchone()
        assert resumed["state"] == "applied"
        assert resumed["applied_cursor"] is not None
        assert resumed["duplicate_count"] == 1
        assert after == before
    finally:
        repository.close()
        admin.close()


def test_disabled_transfer_mode_seals_nothing() -> None:
    """Profile A with the transport off must behave exactly as before P1."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"disabled-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"disabled_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    # No producer id and no sender: this is COLLECTOR_TRANSFER_MODE=disabled.
    repository = PostgresCollectorRepository(collector_dsn)
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        result = repository.persist_account_batch(batch)

        assert result.revision_id is not None
        assert result.snapshot_count == 1
        assert admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_outbox",
        ).fetchone()["count"] == 0
        assert admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_inbox",
        ).fetchone()["count"] == 0
    finally:
        repository.close()
        admin.close()


def test_exhausted_attempt_window_pauses_delivery_without_discarding() -> None:
    """A consumer that stays down must not be hammered, nor lose the batch.

    The protocol caps attempts per rolling hour and then leaves the record
    pending. `terminal` means an unrecoverable batch, not an unreachable peer,
    so an outage must never reach that state.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    from collector_target.transfer import (
        RETRY_MAX_ATTEMPTS_PER_WINDOW, RETRY_MAX_SECONDS,
    )

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"window-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"window_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )

    class AlwaysDown:
        def send(self, envelope):
            raise ConnectionError("simulated outage")

    # A fixed jitter source makes the stored delay exact instead of a range.
    producer = PostgresTransferProducer(
        repository, AlwaysDown(), random_unit=lambda: 1.0,
    )
    repository.configure_transfer_sender(producer)
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        repository.persist_account_batch(batch)

        def row():
            return admin.execute(
                """SELECT state,attempt_window_count,publish_attempts,payload,
                          last_error_code,
                          extract(epoch FROM available_at-transaction_timestamp())
                              AS wait_seconds
                     FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
                (producer_id,),
            ).fetchone()

        first = row()
        assert first["attempt_window_count"] == 1
        assert first["last_error_code"] == "consumer_unavailable"
        # Full jitter at 1.0 gives exactly the ceiling for this attempt.
        assert 0 < first["wait_seconds"] <= RETRY_MAX_SECONDS

        # Drive the window to its cap. available_at is cleared each round so the
        # cap, not the backoff, is what finally stops delivery.
        for _ in range(RETRY_MAX_ATTEMPTS_PER_WINDOW - 1):
            admin.execute(
                """UPDATE ops_and_admin.transfer_outbox
                      SET available_at=transaction_timestamp()
                    WHERE producer_id=%s""",
                (producer_id,),
            )
            producer.deliver_pending()
        exhausted = row()
        assert exhausted["attempt_window_count"] == RETRY_MAX_ATTEMPTS_PER_WINDOW

        # The cap now holds even with available_at in the past.
        admin.execute(
            """UPDATE ops_and_admin.transfer_outbox
                  SET available_at=transaction_timestamp()
                WHERE producer_id=%s""",
            (producer_id,),
        )
        assert producer.deliver_pending() == 0
        paused = row()
        assert paused["attempt_window_count"] == RETRY_MAX_ATTEMPTS_PER_WINDOW
        assert paused["state"] == "sent"
        assert paused["payload"] is not None

        # Once the hour rolls over the batch is deliverable again and the
        # window restarts rather than resuming where it stopped.
        admin.execute(
            """UPDATE ops_and_admin.transfer_outbox
                  SET available_at=transaction_timestamp(),
                      attempt_window_started_at=transaction_timestamp()
                                                -interval '2 hours'
                WHERE producer_id=%s""",
            (producer_id,),
        )
        producer.deliver_pending()
        resumed = row()
        assert resumed["attempt_window_count"] == 1
        assert resumed["state"] == "sent"
        assert resumed["payload"] is not None
    finally:
        repository.close()
        admin.close()


def test_backoff_recorded_in_the_outbox_grows_between_attempts() -> None:
    """Consecutive failures must wait longer, not re-try at a flat interval."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"backoff-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"backoff_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )

    class AlwaysDown:
        def send(self, envelope):
            raise ConnectionError("simulated outage")

    producer = PostgresTransferProducer(
        repository, AlwaysDown(), random_unit=lambda: 1.0,
    )
    repository.configure_transfer_sender(producer)
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        repository.persist_account_batch(batch)

        waits = []
        for _ in range(4):
            waits.append(float(admin.execute(
                """SELECT extract(epoch FROM available_at-transaction_timestamp())
                          AS wait_seconds
                     FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
                (producer_id,),
            ).fetchone()["wait_seconds"]))
            admin.execute(
                """UPDATE ops_and_admin.transfer_outbox
                      SET available_at=transaction_timestamp()
                    WHERE producer_id=%s""",
                (producer_id,),
            )
            producer.deliver_pending()
        # 1, 2, 4, 8 seconds at full jitter, allowing for statement latency.
        assert all(
            waits[index] < waits[index + 1] for index in range(len(waits) - 1)
        )
        assert waits[0] <= 1.0 and waits[-1] > 4.0
    finally:
        repository.close()
        admin.close()


def test_profile_b_round_trip_over_real_mtls_reaches_the_same_database() -> None:
    """Profile B end to end: HTTPS + mTLS in front of the real data adapter."""
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("httpx")
    from psycopg.rows import dict_row

    import asyncio
    import threading

    from collector_target.transfer import HttpsMtlsTransport
    from transfer_ingest.handler import IngestHandler
    from transfer_ingest.server import IngestServer, build_ssl_context
    from transfer_pki import build_pki

    import tempfile
    from pathlib import Path

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    context = CollectionContext.create(
        Platform.TELEGRAM, f"mtls-{uuid4()}", "transfer-test-v1", now, now,
    )
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"mtls_{account_id.hex}", "public_web",
    )
    batch = _one_publication_batch(context, account, now)
    producer_id = f"server-1/{context.partition_key}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id,
    )

    workspace = tempfile.TemporaryDirectory()
    pki = build_pki(Path(workspace.name) / "pki")
    client = pki.issue("client", "server-1")

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: dict = {}

    def serve() -> None:
        asyncio.set_event_loop(loop)
        server = IngestServer(
            IngestHandler(PostgresDataAdapter(repository)),
            allowed_producers=("server-1",),
        )
        listener = loop.run_until_complete(server.start(
            "127.0.0.1", 0,
            build_ssl_context(
                str(pki.server.certificate), str(pki.server.private_key),
                str(pki.ca_bundle),
            ),
        ))
        state["port"] = listener.sockets[0].getsockname()[1]
        state["listener"] = listener
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=30)

    transport = HttpsMtlsTransport(
        f"https://localhost:{state['port']}/transfer/v1/batches",
        certificate=str(client.certificate),
        private_key=str(client.private_key),
        ca_bundle=str(pki.ca_bundle),
    )
    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, transport),
    )
    try:
        _reset_transfer(admin)
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        repository.persist_account_batch(batch)

        outbox = admin.execute(
            """SELECT state,ack_receipt_id,ack_checksum,payload_sha256
                 FROM ops_and_admin.transfer_outbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        assert outbox["state"] == "acknowledged"
        assert outbox["ack_checksum"] == outbox["payload_sha256"]

        inbox = admin.execute(
            """SELECT receipt_id,state,applied_cursor,duplicate_count
                 FROM ops_and_admin.transfer_inbox WHERE producer_id=%s""",
            (producer_id,),
        ).fetchone()
        # The batch crossed a real TLS connection and was applied by the very
        # adapter production uses; the data is already there, so it is a
        # duplicate rather than a second write.
        assert inbox["state"] == "applied"
        assert inbox["applied_cursor"] is not None
        assert inbox["duplicate_count"] == 1
        assert inbox["receipt_id"] == outbox["ack_receipt_id"]
    finally:
        loop.call_soon_threadsafe(state["listener"].close)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=30)
        loop.close()
        workspace.cleanup()
        repository.close()
        admin.close()


def _identity_batch(account, observed_at, username, native_id, views, run=None):
    context = run or CollectionContext.create(
        Platform.TELEGRAM, f"identity-{uuid4()}", "identity-test-v1",
        observed_at, observed_at,
    )
    raw = RawCollectionBatch(
        account,
        RawAccountObservation(
            observed_at, observed_at, 100 + views, str(100 + views),
            username=username, title=f"{username} title",
            url=f"https://t.me/{username}", native_external_id=native_id,
        ),
        (RawPublication(
            "m:7", observed_at - timedelta(minutes=1), observed_at, observed_at,
            observed_at, "text",
            {"views": views, "reactions": 1, "comments": None, "shares": None},
            {"kind": "integration"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "identity-integration", "1",
    )
    return CanonicalNormalizer().normalize(raw, context)


@pytest.mark.parametrize("admin_native_id", ["333", ""])
def test_server_two_applies_a_batch_older_than_an_admin_identity_edit(
    tmp_path, monkeypatch, admin_native_id: str,
) -> None:
    """S1 sealed an observation before an admin edited the account on S2.

    The edit opens identity versions at the admin's commit time, later than
    the sealed observation. Applying that batch used to raise «account
    identity observation time collision» on every retry, so the inbox never
    drained and the batch's metrics never landed. The admin edit stays
    current; the batch's metrics are applied.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    monkeypatch.setenv("MRANKED_IDENTITY_RECEIPT_DIR", str(tmp_path))
    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"identity_{account_id.hex}", "public_web",
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    producer_id = f"server-1/identity-{uuid4()}"
    repository = PostgresCollectorRepository(collector_dsn)
    adapter = PostgresDataAdapter(repository)
    suffix = account_id.hex[:12]
    try:
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        # S2 already holds an earlier collector observation of the account.
        adapter.receive(seal_batch(
            _identity_batch(account, now - timedelta(minutes=10),
                            f"old_{suffix}", "111", 10),
            producer_id, cursor=1,
        ))
        # S1 seals a newer observation (renamed, new native id) ...
        sealed = _identity_batch(account, now - timedelta(minutes=5),
                                 f"seen_{suffix}", "222", 20)
        envelope = seal_batch(sealed, producer_id, cursor=2)
        # ... and before it reaches S2 an admin edits the account there.
        version = admin.execute(
            "SELECT row_version FROM catalog.platform_account WHERE id=%s",
            (account_id,),
        ).fetchone()["row_version"]
        edit = admin.execute(
            "SELECT ops_and_admin.catalog_command(%s,%s,%s,%s::jsonb,%s,%s) AS r",
            ("account.upsert", None, version, json.dumps({
                "platform": "telegram", "externalKey": account.canonical_external_id,
                "username": f"admin_{suffix}", "title": "Admin title",
                "url": f"https://t.me/admin_{suffix}", "accessMode": "public_web",
                "institutionId": str(institution_id),
            }), "integration-admin", uuid4()),
        ).fetchone()["r"]
        assert edit["outcome"] == "succeeded"
        version = admin.execute(
            "SELECT row_version FROM catalog.platform_account WHERE id=%s",
            (account_id,),
        ).fetchone()["row_version"]
        native = admin.execute(
            "SELECT ops_and_admin.catalog_command(%s,%s,%s,%s::jsonb,%s,%s) AS r",
            ("account.native_id", account_id, version,
             json.dumps({"nativeId": admin_native_id}), "integration-admin", uuid4()),
        ).fetchone()["r"]
        assert native["outcome"] == "succeeded"

        ack = adapter.receive(envelope)
        assert adapter.receive(envelope) == ack

        inbox = admin.execute(
            """SELECT state,accepted_count,duplicate_count
                 FROM ops_and_admin.transfer_inbox WHERE receipt_id=%s""",
            (ack.receipt_id,),
        ).fetchone()
        assert inbox == {"state": "applied", "accepted_count": 1, "duplicate_count": 0}
        # The metrics of the late batch are applied ...
        assert admin.execute(
            """SELECT views_count FROM analytics.publication_latest
                WHERE publication_id=%s""",
            (sealed.publications[0].id,),
        ).fetchone()["views_count"] == 20
        assert admin.execute(
            """SELECT count(*) AS count FROM ingest.account_metric_snapshot
                WHERE platform_account_id=%s AND collection_run_id=%s""",
            (account_id, sealed.context.run_id),
        ).fetchone()["count"] == 1
        # ... while the admin edit, the newer fact, stays current.
        current = admin.execute(
            """SELECT current_username,current_title,current_url
                 FROM catalog.platform_account WHERE id=%s""",
            (account_id,),
        ).fetchone()
        assert current == {
            "current_username": f"admin_{suffix}", "current_title": "Admin title",
            "current_url": f"https://t.me/admin_{suffix}",
        }
        history = admin.execute(
            """SELECT username,source_run_id,valid_to FROM catalog.account_identity_history
                WHERE platform_account_id=%s ORDER BY valid_from""",
            (account_id,),
        ).fetchall()
        assert [row["username"] for row in history] == [f"old_{suffix}", f"admin_{suffix}"]
        assert history[-1]["source_run_id"] is None and history[-1]["valid_to"] is None
        natives = admin.execute(
            """SELECT external_id,valid_to FROM catalog.account_external_identity
                WHERE platform_account_id=%s AND identity_namespace='telegram:native_id'
                ORDER BY valid_from""",
            (account_id,),
        ).fetchall()
        expected_natives = ["111"] + ([admin_native_id] if admin_native_id else [])
        assert [row["external_id"] for row in natives] == expected_natives
        assert (natives[-1]["valid_to"] is None) == bool(admin_native_id)

        # A later observation still versions identity on top of the admin edit.
        later = _identity_batch(account, now + timedelta(minutes=1),
                                f"later_{suffix}", "444", 30)
        adapter.receive(seal_batch(later, producer_id, cursor=3))
        assert admin.execute(
            "SELECT current_username FROM catalog.platform_account WHERE id=%s",
            (account_id,),
        ).fetchone()["current_username"] == f"later_{suffix}"
        assert admin.execute(
            """SELECT external_id FROM catalog.account_external_identity
                WHERE platform_account_id=%s AND identity_namespace='telegram:native_id'
                  AND valid_to IS NULL""",
            (account_id,),
        ).fetchone()["external_id"] == "444"
    finally:
        repository.close()
        admin.close()


@pytest.mark.parametrize("field", ["username", "native_id"])
def test_same_instant_collector_identity_conflict_still_raises(
    tmp_path, monkeypatch, field: str,
) -> None:
    """Two collector runs claim different identities at one instant.

    Neither is newer, so there is no order to version them in; the guard
    stays and the second batch is refused rather than silently dropped.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    monkeypatch.setenv("MRANKED_IDENTITY_RECEIPT_DIR", str(tmp_path))
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    account = AccountRef(
        account_id, institution_id, Platform.TELEGRAM,
        f"collision_{account_id.hex}", "public_web",
    )
    at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    producer_id = f"server-1/collision-{uuid4()}"
    repository = PostgresCollectorRepository(_dsn("MRANKED_TEST_POSTGRES_DSN"))
    adapter = PostgresDataAdapter(repository)
    suffix = account_id.hex[:12]
    try:
        _seed_account(admin, institution_id, account_id, account.canonical_external_id)
        adapter.receive(seal_batch(
            _identity_batch(account, at, f"first_{suffix}", "111", 10), producer_id,
            cursor=1,
        ))
        rival = _identity_batch(
            account, at,
            f"first_{suffix}" if field == "native_id" else f"rival_{suffix}",
            "222" if field == "native_id" else "111", 10,
        )
        with pytest.raises(RuntimeError, match="time collision"):
            adapter.receive(seal_batch(rival, producer_id, cursor=2))
    finally:
        repository.close()
        admin.close()
