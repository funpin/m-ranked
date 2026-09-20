"""Measure P1 sealing cost against disposable PostgreSQL.

Requires MRANKED_TEST_POSTGRES_DSN and MRANKED_TEST_POSTGRES_ADMIN_DSN. Setup,
run/account creation and transport delivery are excluded; the measured interval
is exactly ``persist_account_batch`` with or without the transactional seal.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg import connect
from psycopg.rows import dict_row

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository


class Counter:
    value = 0


class CountingCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def execute(self, *args, **kwargs):
        Counter.value += 1
        self.cursor.execute(*args, **kwargs)
        return self

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class CountingConnection:
    def __init__(self, dsn: str):
        self.connection = connect(dsn, autocommit=True, row_factory=dict_row)

    def execute(self, *args, **kwargs):
        Counter.value += 1
        return self.connection.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return CountingCursor(self.connection.cursor(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self.connection, name)


def main() -> int:
    collector_dsn = os.environ["MRANKED_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ["MRANKED_TEST_POSTGRES_ADMIN_DSN"]
    admin = connect(admin_dsn, autocommit=True)

    def factory():
        return CountingConnection(collector_dsn)

    baseline = PostgresCollectorRepository(connection_factory=factory)
    sealed = PostgresCollectorRepository(
        connection_factory=factory, transfer_producer_id="benchmark/default",
    )
    samples: dict[str, list[float | int]] = {
        "before_ms": [], "after_ms": [], "before_round_trips": [],
        "after_round_trips": [],
    }

    def run(repository: PostgresCollectorRepository, label: str) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        institution_id, account_id = uuid4(), uuid4()
        context = CollectionContext.create(
            Platform.TELEGRAM, str(uuid4()), "seal-benchmark-v1", now, now,
        )
        account = AccountRef(
            account_id, institution_id, Platform.TELEGRAM,
            f"benchmark_{account_id.hex}", "public_web",
        )
        admin.execute(
            "INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
            (institution_id, f"seal benchmark {institution_id}"),
        )
        admin.execute(
            """INSERT INTO catalog.platform_account(
                   id,institution_id,platform,canonical_external_id,access_mode
               ) VALUES (%s,%s,'telegram',%s,'public_web')""",
            (account_id, institution_id, account.canonical_external_id),
        )
        batch = CanonicalNormalizer().normalize(RawCollectionBatch(
            account, None,
            (RawPublication(
                "m:1", now, now, now, now, "text",
                {"views": 1, "reactions": 1, "comments": 0, "shares": None},
                {"benchmark": True},
                history_completeness=HistoryCompleteness.COMPLETE,
            ),), "benchmark", "1",
        ), context)
        repository.start_run(context)
        repository.begin_account(context, account, now)
        Counter.value = 0
        started = time.perf_counter()
        repository.persist_account_batch(batch)
        elapsed = (time.perf_counter() - started) * 1000
        samples[f"{label}_ms"].append(round(elapsed, 3))
        samples[f"{label}_round_trips"].append(Counter.value)

    try:
        for _ in range(6):
            run(baseline, "before")
            run(sealed, "after")
    finally:
        baseline.close()
        sealed.close()
        admin.close()
    output = {
        "samples": samples,
        "medianBeforeMs": round(statistics.median(samples["before_ms"]), 3),
        "medianAfterMs": round(statistics.median(samples["after_ms"]), 3),
        "roundTripsBefore": statistics.median(samples["before_round_trips"]),
        "roundTripsAfter": statistics.median(samples["after_round_trips"]),
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
