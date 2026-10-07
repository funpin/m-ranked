from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from operations.storage.compaction import (COMPACT, COMPACTABLE, MONTHS, RELEASE, Settings, released_months, run)

NOW = datetime(2026, 11, 5, 3, tzinfo=timezone.utc)


class Connection:
    def __init__(self, batches, months=(), busy=()):
        self.batches, self.months, self.busy = list(batches), list(months), set(busy)
        self.compacted, self.released, self.boundaries = [], [], set()
        self._rows = []

    def execute(self, sql, params=()):
        if sql == COMPACTABLE:
            self.boundaries.add(params[0])
            self._rows = [{"publication_id": item} for item in (self.batches.pop(0) if self.batches else [])]
        elif sql == COMPACT:
            self.compacted.append(params[0])
            self.boundaries.add(params[1])
            self._rows = [{"moved": 10}]
        elif sql == MONTHS:
            self._rows = [{"month": month} for month in self.months]
        elif sql == RELEASE:
            if params[0] in self.busy:
                raise RuntimeError("lock timeout")
            self.released.append(params[0])
            self._rows = [{"released": True}]
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


def ids(*numbers):
    return [UUID(int=number) for number in numbers]


def test_runs_batches_until_nothing_left_with_one_boundary():
    connection = Connection([ids(1, 2), ids(3)])
    result = run(connection, Settings(hot=timedelta(hours=48), pace=0), clock=lambda: NOW)
    assert connection.compacted == ids(1, 2, 3)
    assert connection.boundaries == {NOW - timedelta(hours=48)}
    assert (result.publications, result.points, result.remaining) == (3, 30, False)


def test_stops_at_the_time_budget_and_says_work_remains():
    ticks = iter([0, 0, 0, 1000, 1000, 1000, 1000])
    connection = Connection([ids(1), ids(2), ids(3)])
    result = run(connection, Settings(budget=timedelta(minutes=10), pace=0), clock=lambda: NOW,
                 monotonic=lambda: next(ticks))
    assert connection.compacted == ids(1) and result.remaining


def test_pauses_in_proportion_to_the_work():
    ticks = iter([0, 0, 0, 4, 4, 4, 4])
    pauses = []
    run(Connection([ids(1)]), Settings(pace=0.5), clock=lambda: NOW, monotonic=lambda: next(ticks),
        sleep=pauses.append)
    assert pauses == [2.0]


def test_releases_only_months_before_the_previous_one_and_survives_a_busy_lock():
    months = [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)]
    connection = Connection([], months=months, busy={date(2026, 8, 1)})
    result = run(connection, Settings(pace=0), clock=lambda: NOW)
    assert connection.released == [date(2026, 9, 1)] and result.released == 1
    assert released_months(months, NOW) == [date(2026, 8, 1), date(2026, 9, 1)]
