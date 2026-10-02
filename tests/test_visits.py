import asyncio
from datetime import date, datetime, timezone

import pytest

from api import visits
from api.visits import VisitCounter

BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"
# 2026-10-02 12:00 по Москве
NOON = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc).timestamp()


class FakeDatabase:
    def __init__(self) -> None:
        self.salts: dict[date, bytes] = {}
        self.executed: list[tuple[str, dict]] = []
        self.fail = False

    async def admin_execute(self, sql: str, params: dict) -> None:
        if self.fail:
            raise RuntimeError("database is down")
        if sql == visits.SALT_INSERT:
            self.salts.setdefault(params["day"], params["salt"])
        self.executed.append((sql, params))

    async def admin_fetch_one(self, sql: str, params: dict) -> dict:
        return {"salt": self.salts[params["day"]]}


def run(coroutine):
    return asyncio.run(coroutine)


def test_robots_and_short_agents_are_not_visitors() -> None:
    counter = VisitCounter(FakeDatabase(), clock=lambda: NOON)
    assert run(counter.record("1.2.3.4", "Googlebot/2.1 (+http://www.google.com/bot.html)", True)) is False
    assert run(counter.record("1.2.3.4", "curl/8.0", True)) is False
    assert run(counter.record("1.2.3.4", "", True)) is False
    assert run(counter.record("1.2.3.4", BROWSER, True)) is True


def test_same_browser_and_address_is_one_visitor_per_day() -> None:
    database = FakeDatabase()
    now = [NOON]
    counter = VisitCounter(database, clock=lambda: now[0])
    for _ in range(3):
        run(counter.record("1.2.3.4", BROWSER, True))
    run(counter.record("1.2.3.4", BROWSER, False))  # «вкладка ещё открыта»
    run(counter.record("5.6.7.8", BROWSER, True))
    assert run(counter.flush()) == 2
    sql, params = database.executed[-1]
    assert sql == visits.UPSERT
    assert sorted(params["views"]) == [1, 3]
    assert all(len(visitor) == 16 for visitor in params["visitors"])
    assert params["days"] == [date(2026, 10, 2)] * 2
    # Адрес не уходит в базу ни в каком виде, кроме хеша с солью.
    assert all(b"1.2.3.4" not in visitor for visitor in params["visitors"])
    # Следующие сутки — новая соль и новый посетитель.
    now[0] += 86400
    run(counter.record("1.2.3.4", BROWSER, True))
    run(counter.flush())
    assert database.executed[-1][1]["visitors"][0] not in params["visitors"]


def test_failed_flush_keeps_signals_for_the_next_attempt() -> None:
    database = FakeDatabase()
    counter = VisitCounter(database, clock=lambda: NOON)
    run(counter.record("1.2.3.4", BROWSER, True))
    database.fail = True
    with pytest.raises(RuntimeError):
        run(counter.flush())
    database.fail = False
    run(counter.record("1.2.3.4", BROWSER, True))
    assert run(counter.flush()) == 1
    assert database.executed[-1][1]["views"] == [2]


def test_rollup_waits_for_the_first_minutes_after_midnight() -> None:
    database = FakeDatabase()
    midnight = datetime(2026, 10, 2, 21, 2, tzinfo=timezone.utc).timestamp()  # 00:02 МСК
    run(VisitCounter(database, clock=lambda: midnight).rollup())
    assert database.executed == []
    run(VisitCounter(database, clock=lambda: midnight + 600).rollup())
    assert [sql for sql, _ in database.executed] == [visits.ROLLUP, visits.SALT_PURGE]
    assert database.executed[0][1] == {"today": date(2026, 10, 3)}


def test_beacon_answers_204_and_reads_the_client_address(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.config import Settings

    monkeypatch.setenv("API_READ_DB_HOST", "")
    application = create_app(Settings())
    seen = []

    class Counter:
        async def record(self, address, agent, view):
            seen.append((address, agent, view))
            return True

    application.state.visits = Counter()
    client = TestClient(application, client=("127.0.0.1", 50000))
    headers = {"user-agent": BROWSER, "x-real-ip": "203.0.113.7", "content-type": "text/plain"}
    response = client.post("/api/v1/visit", content='{"view":true}', headers=headers)
    assert response.status_code == 204 and response.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/visit", content="ping", headers=headers).status_code == 204
    assert seen == [("203.0.113.7", BROWSER, True), ("203.0.113.7", BROWSER, False)]
    application.state.visits = None
    assert client.post("/api/v1/visit", content="{}", headers=headers).status_code == 204
