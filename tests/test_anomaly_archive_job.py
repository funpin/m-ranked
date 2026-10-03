from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from anomaly_analysis.v2 import archive_job

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, row=None, rowcount=0):
        self.row, self.rowcount = row, rowcount

    def fetchone(self):
        return self.row


class Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Connection:
    def __init__(self, params, open_counts):
        self.params, self.open_counts, self.calls = params, list(open_counts), []

    def transaction(self):
        return Transaction()

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SET state = 'running'" in sql:
            return Result({"id": "job-1", "params": self.params} if self.params is not None else None)
        if "INSERT INTO analytics.post_anomaly_state" in sql:
            return Result(rowcount=3)
        if "SET frozen = false" in sql:
            return Result(rowcount=40)
        if "count(*) FILTER" in sql:
            return Result({"open": self.open_counts.pop(0), "failing": 0})
        return Result()

    def finished(self):
        return next(params for sql, params in self.calls if "finished_at" in sql)


def test_month_posts_are_requeued_and_the_job_waits_until_they_are_frozen_again() -> None:
    connection = Connection({"month": "2026-08", "platform": "max"}, [40, 12, 0])
    sleeps = []
    outcome = archive_job.run(connection, clock=lambda: NOW, sleep=sleeps.append)
    assert outcome == {"id": "job-1", "state": "done", "queued": 40, "seeded": 3}
    assert len(sleeps) == 2
    window = next(params for sql, params in connection.calls if "SET frozen = false" in sql)
    assert window["start"] == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert window["end"] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert window["platform"] == "max"
    assert json.loads(connection.finished()["progress"])["open"] == 0


def test_job_fails_after_the_deadline_with_the_open_count() -> None:
    moments = iter([NOW, NOW + archive_job.DEADLINE + timedelta(seconds=1)])
    connection = Connection({"month": "2026-08"}, [40])
    outcome = archive_job.run(connection, clock=lambda: next(moments), sleep=lambda _: None)
    assert outcome["state"] == "failed"
    assert "40 posts still open" in connection.finished()["error"]


def test_bad_month_fails_the_job_and_an_empty_queue_returns_none() -> None:
    connection = Connection({"month": "2026-13"}, [])
    assert archive_job.run(connection, clock=lambda: NOW)["state"] == "failed"
    assert archive_job.run(Connection(None, []), clock=lambda: NOW) is None
    with pytest.raises(ValueError):
        archive_job.scope({"month": "2026-08", "platform": "ok"})
