"""Задание готовой истории: темп, бюджет, пропуск сбоев и сверка отпечатка."""
from datetime import datetime, timezone
import json
import uuid
import zlib

from api.sql import details
from api.tools import history_pages

PUBLISHED = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, candidates, *, fingerprints=None, oldest=(), broken=()):
        self.candidates = list(candidates)
        self.fingerprints = fingerprints or {}
        self.oldest = list(oldest)
        self.broken = set(broken)
        self.upserts, self.touched, self.skips = [], [], []

    def execute(self, sql, params=None):
        if sql == history_pages.CANDIDATES:
            self.skips.append(list(params["skip"]))
            done = {row["publication_id"] for row in self.upserts} | set(params["skip"])
            return Result([row for row in self.candidates if row["id"] not in done][:params["limit"]])
        if sql == details.HISTORY_FINGERPRINT:
            count, maximum = self.fingerprints.get(params["publication_id"], (2, 20))
            return Result([{"snapshot_count": count, "max_snapshot_id": maximum}])
        if sql == details.HISTORY:
            if params["publication_id"] in self.broken:
                raise TimeoutError("statement timeout")
            assert params["fetch_limit"] == 2001 and params["after_snapshot_id"] is None
            return Result([])
        if sql == history_pages.UPSERT:
            self.upserts.append({"publication_id": params["id"], **params})
            return Result([])
        if sql == history_pages.OLDEST:
            return Result(self.oldest[:params["limit"]])
        if sql == history_pages.TOUCH:
            self.touched.append(params["id"])
            return Result([])
        raise AssertionError(sql)


class Clock:
    def __init__(self, step):
        self.now, self.step, self.slept = 0.0, step, []

    def __call__(self):
        self.now += self.step
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def post():
    return {"id": uuid.uuid4(), "published_at": PUBLISHED}


def test_candidates_are_computed_at_half_speed_within_the_budget():
    connection = FakeConnection([post() for _ in range(500)])
    clock = Clock(0.1)
    done = history_pages.run(connection, max_seconds=10, min_age_days=41, recheck=0, pace=1.0,
                             clock=clock, sleep=clock.sleep)
    assert 0 < done["computed"] < 500
    assert clock.now <= 10 + 1
    # Пауза после каждого поста — не меньше времени его расчёта.
    assert clock.slept and all(seconds >= 0.1 - 1e-9 for seconds in clock.slept)
    stored = connection.upserts[0]
    assert stored["published_month"].isoformat() == "2026-07-01" and stored["items_count"] == 0


def test_a_failing_post_is_skipped_for_the_rest_of_the_run():
    broken, fine = post(), post()
    connection = FakeConnection([broken, fine], broken={broken["id"]})
    clock = Clock(0.01)
    done = history_pages.run(connection, max_seconds=5, min_age_days=41, recheck=0, pace=0,
                             clock=clock, sleep=clock.sleep)
    assert done == {"computed": 1, "rechecked": 0, "refreshed": 0, "failed": 1}
    assert [row["publication_id"] for row in connection.upserts] == [fine["id"]]
    assert connection.skips[-1] == [broken["id"]]


def test_recheck_touches_unchanged_pages_and_rebuilds_corrected_ones():
    same, corrected = uuid.uuid4(), uuid.uuid4()
    oldest = [{"id": same, "published_at": PUBLISHED, "snapshot_count": 2, "max_snapshot_id": 20},
              {"id": corrected, "published_at": PUBLISHED, "snapshot_count": 2, "max_snapshot_id": 20}]
    connection = FakeConnection([], fingerprints={corrected: (3, 31)}, oldest=oldest)
    clock = Clock(0.01)
    done = history_pages.run(connection, max_seconds=5, min_age_days=41, recheck=10, pace=0,
                             clock=clock, sleep=clock.sleep)
    assert done == {"computed": 0, "rechecked": 2, "refreshed": 1, "failed": 0}
    assert connection.touched == [same]
    assert [row["publication_id"] for row in connection.upserts] == [corrected]
    assert (connection.upserts[0]["snapshot_count"], connection.upserts[0]["max_snapshot_id"]) == (3, 31)


def test_stored_json_reads_back_as_the_api_would_serialize_it():
    items = [{"snapshotId": "7", "observedAt": "2026-07-15T12:00:00+00:00", "ageHours": 0.5,
              "reactionsBreakdown": {"👍": 3}, "rawEvidence": {"at": datetime(2026, 7, 15, tzinfo=timezone.utc)}}]
    decoded = json.loads(zlib.decompress(history_pages.encode(items)))
    api = json.dumps(items, ensure_ascii=False, separators=(",", ":"), default=str)
    assert json.dumps(decoded, ensure_ascii=False, separators=(",", ":"), default=str) == api
