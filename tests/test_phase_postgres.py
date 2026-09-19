from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from collector_target.model import Platform
from collector_target.phase import PhaseRequest, PostgresPhaseArbiter


def _dsn() -> str:
    value = os.getenv("MRANKED_TEST_POSTGRES_DSN", "").strip()
    if not value:
        pytest.skip("MRANKED_TEST_POSTGRES_DSN is not configured")
    return value


def _request(
    platform: Platform,
    partition: str,
    scheduled_at: datetime,
) -> PhaseRequest:
    return PhaseRequest(
        platform,
        partition,
        "phase-integration-v1",
        scheduled_at,
        scheduled_at,
        datetime.now(timezone.utc),
    )


def test_postgres_phase_claim_is_global_fair_and_recovers_disconnect() -> None:
    pytest.importorskip("psycopg")
    from psycopg.pq import TransactionStatus
    dsn = _dsn()
    partition = f"phase-{uuid4()}"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    first = _request(Platform.TELEGRAM, partition, now - timedelta(minutes=2))
    second = _request(Platform.VK, partition, now - timedelta(minutes=1))
    left = PostgresPhaseArbiter(dsn)
    right = PostgresPhaseArbiter(dsn)
    left.request(first)
    right.request(second)

    assert right.try_acquire(second, stale_after_seconds=60) is None
    lease = left.try_acquire(first, stale_after_seconds=60)
    assert lease is not None
    assert lease.connection.info.transaction_status == TransactionStatus.IDLE  # type: ignore[attr-defined]
    assert right.try_acquire(second, stale_after_seconds=60) is None
    lease.finish("succeeded", now)
    lease.release()

    recovered = right.try_acquire(second, stale_after_seconds=60)
    assert recovered is not None
    # Closing the dedicated session models a process crash: PostgreSQL drops
    # the advisory lock without requiring a cleanup transaction.
    recovered.connection.close()  # type: ignore[attr-defined]

    resumed = _request(Platform.VK, partition, second.scheduled_at)
    assert left.request(resumed)
    after_crash = left.try_acquire(resumed, stale_after_seconds=60)
    assert after_crash is not None
    assert after_crash.alive()
    after_crash.finish("succeeded", now)
    after_crash.release()
