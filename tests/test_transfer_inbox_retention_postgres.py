"""Срок хранения квитанций приёма переноса (0060) на одноразовой базе.

    MRANKED_TEST_PACKED_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

ADMIN = os.environ.get("MRANKED_TEST_PACKED_ADMIN_DSN", "")
pytestmark = pytest.mark.skipif(not ADMIN, reason="disposable PostgreSQL DSN is required")
NOW = datetime.now(timezone.utc)


def receipt(connection, producer, cursor, state, applied_days_ago, *, accepted=3, duplicates=1):
    receipt_id = connection.execute("""
        INSERT INTO ops_and_admin.transfer_inbox(producer_id, batch_id, schema_version, first_cursor, last_cursor,
            payload, checksum, record_count, uncompressed_bytes, state, accepted_count, duplicate_count,
            reason_code, applied_at, applied_cursor)
        VALUES (%(producer)s, gen_random_uuid(), 1, %(cursor)s, %(cursor)s,
                CASE WHEN %(state)s = 'applied' THEN NULL ELSE '\\x00'::bytea END, repeat('a', 64), %(records)s, 10, %(state)s,
                %(accepted)s, %(duplicates)s,
                CASE WHEN %(state)s = 'quarantined' THEN 'bad_payload' END,
                CASE WHEN %(state)s = 'applied' THEN %(applied)s END,
                CASE WHEN %(state)s = 'applied' THEN %(cursor)s END)
        RETURNING receipt_id""", {
            "producer": producer, "cursor": cursor, "state": state,
            "records": accepted + duplicates if state == "applied" else 4,
            "accepted": accepted if state == "applied" else 0, "duplicates": duplicates if state == "applied" else 0,
            "applied": NOW - timedelta(days=applied_days_ago)}).fetchone()["receipt_id"]
    connection.execute("""INSERT INTO ops_and_admin.transfer_inbox_event(receipt_id, event_index, event_id, outcome)
                          VALUES (%s, 0, gen_random_uuid(), 'accepted')""", (receipt_id,))
    return receipt_id


def test_old_applied_receipts_go_with_their_events_and_leave_totals():
    producer = f"server-test-{uuid4().hex[:8]}"
    with psycopg.connect(ADMIN, autocommit=True, row_factory=dict_row) as connection:
        old = [receipt(connection, producer, cursor, "applied", 10) for cursor in (1, 2, 3)]
        fresh = receipt(connection, producer, 4, "applied", 1)
        quarantined = receipt(connection, producer, 5, "quarantined", 30)
        pending = receipt(connection, producer, 6, "verified", 30)
        with connection.transaction():
            connection.execute("SET LOCAL ROLE collector_ingest")
            removed = connection.execute("SELECT ops_and_admin.prune_transfer_inbox(%s, 2) AS n",
                                         (NOW - timedelta(days=7),)).fetchone()["n"]
            removed += connection.execute("SELECT ops_and_admin.prune_transfer_inbox(%s, 100) AS n",
                                          (NOW - timedelta(days=7),)).fetchone()["n"]
        left = {row["receipt_id"] for row in connection.execute(
            "SELECT receipt_id FROM ops_and_admin.transfer_inbox WHERE producer_id = %s", (producer,)).fetchall()}
        events = connection.execute("SELECT count(*) AS n FROM ops_and_admin.transfer_inbox_event "
                                    "WHERE receipt_id = ANY (%s)", (old,)).fetchone()["n"]
        rollup = connection.execute("SELECT * FROM ops_and_admin.transfer_inbox_rollup WHERE producer_id = %s",
                                    (producer,)).fetchone()
    assert removed == 3 and left == {fresh, quarantined, pending} and events == 0
    assert (rollup["applied_through_cursor"], rollup["receipts"], rollup["records"], rollup["accepted"],
            rollup["duplicates"]) == (3, 3, 12, 9, 3)
