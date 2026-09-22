"""Кэш публичных ответов: ключ без ревизии, свежесть по возрасту, пересчёт фоном.

Ревизия набора данных на Сервере 2 меняется каждые полторы секунды. Пока она
входила в ключ, запись устаревала быстрее, чем приходил второй посетитель.
Здесь проверяется, что запись одна на логический запрос, отдаётся сразу и
обновляется фоном, а читатель ждёт пересборку, только когда записи нет.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from api import cached
from api.cache import ResponseCache
from api.cached import WARMUP_HEADER, cache_key, published_revision, serve
from api.params import cursor_revision, encode_scoped_cursor

TAGS = frozenset({"overview"})
COMMITTED = datetime(2026, 1, 1, tzinfo=UTC)


def _put(cache: ResponseCache, key: str = "k", value: str = "v", revision: int = 0) -> None:
    cache.put(key, value, '"etag"', TAGS, revision)


class FakeDB:
    def __init__(self, revision: int = 7) -> None:
        self.revision = revision
        self.calls: list[object] = []

    async def fetch_one(self, _query, parameters=None):
        self.calls.append(parameters)
        if parameters and "revision" in parameters:
            return {"id": parameters["revision"], "committed_at": COMMITTED}
        return {"id": self.revision, "committed_at": COMMITTED}


def request(cache, db, *, headers: dict[str, str] | None = None) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(
        cache=cache, db=db,
        settings=SimpleNamespace(statement_timeout_ms=100, cache_refresh_concurrency=2),
    ))
    raw = [(name.encode(), value.encode()) for name, value in (headers or {}).items()]
    return Request({
        "type": "http", "method": "GET", "path": "/api/v1/overview",
        "query_string": b"", "headers": raw, "app": app,
    })


async def _drain() -> None:
    while cached._REFRESHING:
        await asyncio.gather(*list(cached._REFRESHING))


def test_invalidation_marks_stale_but_keeps_serving() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0)
    _put(cache)

    assert cache.invalidate(TAGS) == 1, "запись помечена несвежей"
    entry = cache.get("k")
    assert entry is not None and entry.value == "v", "но продолжает обслуживать"
    assert entry.is_stale(time.monotonic()), "и знает, что несвежая"
    assert entry.expires_at >= entry.born_at + 600 - 1e-6, "и не укорачивает себе жизнь"


def test_fresh_entry_is_not_marked_before_the_floor() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30)
    _put(cache)
    assert cache.invalidate(TAGS) == 1
    entry = cache.get("k")
    assert entry is not None
    # Свежесть держится минимум min_age от рождения: пересчёт не чаще этого.
    assert not entry.is_stale(time.monotonic())
    assert entry.fresh_until >= entry.born_at + 30 - 1e-6


def test_repeated_invalidation_does_not_move_the_deadline() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30)
    _put(cache)
    assert cache.invalidate(TAGS) == 1
    assert cache.invalidate(TAGS) == 0, "повторное уведомление ничего не меняет"
    entry = cache.get("k")
    assert entry is not None
    assert entry.fresh_until <= entry.born_at + 30 + 1e-6


def test_entry_turns_stale_by_age_without_any_notification() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=0.05)
    _put(cache)
    assert not cache.is_stale(cache.get("k"))
    time.sleep(0.08)
    entry = cache.get("k")
    assert entry is not None and cache.is_stale(entry), "несвежая, но ещё отдаётся"


def test_untagged_entry_is_not_touched() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0)
    _put(cache)
    assert cache.invalidate(frozenset({"comparison"})) == 0
    entry = cache.get("k")
    assert entry is not None and not entry.is_stale(time.monotonic())


def test_only_one_refresh_runs_per_key() -> None:
    """Второй читатель несвежей записи не запускает второй пересчёт."""
    cache = ResponseCache(capacity=8, ttl_seconds=600)
    assert cache.begin_refresh("k") is True
    assert cache.begin_refresh("k") is False
    cache.end_refresh("k")
    assert cache.begin_refresh("k") is True


def test_ttl_caps_how_long_an_entry_is_served() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=0.05)
    _put(cache)
    assert cache.get("k") is not None
    time.sleep(0.08)
    assert cache.get("k") is None, "старше TTL ответ уже не отдаётся"


def test_invalid_windows_are_rejected() -> None:
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=-1)
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=0)
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, revision_hold_seconds=0)


def test_key_is_the_logical_request_not_the_revision() -> None:
    query = {"platform": "telegram", "period": "1d"}
    assert cache_key("overview", query) == cache_key("overview", dict(query))
    assert cache_key("overview", {"period": "1d"}) != cache_key("overview", {"period": "7d"})
    assert cache_key("overview", {"period": "1d"}) != cache_key("rating", {"period": "1d"})


def test_published_revision_is_held_for_its_window() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, revision_hold_seconds=0.05)
        db = FakeDB(revision=7)
        assert (await published_revision(db, cache))[0] == 7
        db.revision = 8
        assert (await published_revision(db, cache))[0] == 7, "окно держит ревизию"
        assert len(db.calls) == 1
        await asyncio.sleep(0.08)
        assert (await published_revision(db, cache))[0] == 8
        # Уведомление о записи ревизию не сбрасывает.
        db.revision = 9
        cache.invalidate(TAGS)
        assert (await published_revision(db, cache))[0] == 8
    asyncio.run(scenario())


def test_stale_entry_is_served_at_once_and_refreshed_in_background() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=0.01)
        db = FakeDB(revision=8)
        key = cache_key("overview", {})
        cache.put(key, '{"datasetRevision":7}', '"old"', TAGS, 7)
        await asyncio.sleep(0.02)
        builds: list[int] = []

        async def build(revision, _committed):
            builds.append(revision)
            return {"datasetRevision": revision}

        response = await serve(request(cache, db), "overview", {}, TAGS, build)
        assert response.body == b'{"datasetRevision":7}', "читатель не ждёт пересчёт"
        await _drain()
        assert builds == [8]
        assert cache.get(key).revision == 8
    asyncio.run(scenario())


def test_fresh_entry_is_served_without_touching_the_database() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=60)
        db = FakeDB()
        cache.put(cache_key("overview", {}), '{"warm":true}', '"warm"', TAGS, 7)

        async def must_not_build(_revision, _committed):
            raise AssertionError("fresh response rebuilt")

        response = await serve(request(cache, db), "overview", {}, TAGS, must_not_build)
        assert response.body == b'{"warm":true}'
        assert db.calls == [] and not cached._REFRESHING
    asyncio.run(scenario())


def test_pinned_request_is_served_from_an_entry_of_another_revision() -> None:
    """Страница поста закрепляет карточку аккаунта на ревизии истории. Готовая
    карточка отдаётся и по другой ревизии: пересобирать её на каждый просмотр
    поста стоило полсекунды."""
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=60)
        db = FakeDB()
        cache.put(cache_key("account", {"id": "1"}), '{"datasetRevision":7}', '"a"', TAGS, 7)

        async def must_not_build(_revision, _committed):
            raise AssertionError("pinned request rebuilt a cached answer")

        response = await serve(
            request(cache, db), "account", {"id": "1"}, TAGS, must_not_build,
            pinned_revision=5,
        )
        assert response.body == b'{"datasetRevision":7}'
    asyncio.run(scenario())


def test_missing_pinned_answer_is_built_at_the_pinned_revision() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600)
        db = FakeDB(revision=9)
        built: list[int] = []

        async def build(revision, _committed):
            built.append(revision)
            return {"datasetRevision": revision}

        await serve(request(cache, db), "account", {"id": "1"}, TAGS, build,
                    pinned_revision=5)
        assert built == [5]
    asyncio.run(scenario())


def test_warmup_rebuilds_only_answers_older_than_it_allows() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=0.01)
        db = FakeDB(revision=8)
        key = cache_key("overview", {})
        cache.put(key, '{"datasetRevision":7}', '"old"', TAGS, 7)
        builds: list[int] = []

        async def build(revision, _committed):
            builds.append(revision)
            return {"datasetRevision": revision}

        young = await serve(request(cache, db, headers={WARMUP_HEADER: "60"}),
                            "overview", {}, TAGS, build)
        assert young.body == b'{"datasetRevision":7}' and builds == []
        assert not cached._REFRESHING, "прогрев не запускает фоновых пересчётов"
        await asyncio.sleep(0.05)
        old = await serve(request(cache, db, headers={WARMUP_HEADER: "0.02"}),
                          "overview", {}, TAGS, build)
        assert old.body == b'{"datasetRevision":8}', "старый ответ пересобран сразу"
        assert builds == [8]
    asyncio.run(scenario())


def test_warmup_header_cannot_force_rebuilds_faster_than_freshness() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=8, ttl_seconds=600, fresh_seconds=60)
        db = FakeDB()
        cache.put(cache_key("overview", {}), '{"warm":true}', '"warm"', TAGS, 7)

        async def must_not_build(_revision, _committed):
            raise AssertionError("header forced a rebuild of a fresh answer")

        response = await serve(request(cache, db, headers={WARMUP_HEADER: "0"}),
                               "overview", {}, TAGS, must_not_build)
        assert response.body == b'{"warm":true}'
    asyncio.run(scenario())


def test_background_refreshes_are_bounded_per_process() -> None:
    async def scenario() -> None:
        cache = ResponseCache(capacity=64, ttl_seconds=600, fresh_seconds=0.01)
        db = FakeDB()
        gate = asyncio.Event()
        started = 0

        async def build(revision, _committed):
            nonlocal started
            started += 1
            await gate.wait()
            return {"datasetRevision": revision}

        for index in range(6):
            cache.put(cache_key("overview", {"n": index}), "{}", '"e"', TAGS, 1)
        await asyncio.sleep(0.02)
        for index in range(6):
            await serve(request(cache, db), "overview", {"n": index}, TAGS, build)
        await asyncio.sleep(0)
        assert len(cached._REFRESHING) == 2 and started == 2
        gate.set()
        await _drain()
    asyncio.run(scenario())


def test_cursor_carries_the_revision_its_continuation_needs() -> None:
    cursor = encode_scoped_cursor("00000000-0000-0000-0000-000000000001", 4321, "d")
    assert cursor_revision(cursor) == 4321
    assert cursor_revision(None) is None
    assert cursor_revision("not-a-cursor!") is None


def test_notification_is_free_when_age_already_bounds_freshness() -> None:
    """Уведомления идут каждые полторы секунды. Если свежесть по возрасту
    кончается не позже нижней границы, пометке нечего делать — и перебирать
    тысячи записей прогретого каталога на каждое уведомление нельзя."""
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=60, fresh_seconds=60)
    _put(cache)
    assert cache.invalidate(TAGS) == 0
    assert cache.get("k").fresh_until == pytest.approx(cache.get("k").born_at + 60)


def test_account_card_is_stored_under_every_identifier_it_answers() -> None:
    """Страница поста спрашивает карточку по legacy id, страница аккаунта — по
    UUID. Одна сборка должна обслужить обе."""
    from api.routes.query import _account_aliases

    async def scenario() -> None:
        cache = ResponseCache(capacity=16, ttl_seconds=600, fresh_seconds=60)
        db = FakeDB()
        body = {"accountId": "A0FC5C02-F2BC-5405-AEB1-686F76E258AD",
                "platformAccountLegacyId": 109, "channelLegacyId": 7,
                "datasetRevision": 7}

        async def build(_revision, _committed):
            return body

        await serve(request(cache, db), "account",
                    {"id": "a0fc5c02-f2bc-5405-aeb1-686f76e258ad", "legacyType": "platform_accounts"},
                    TAGS, build, aliases=_account_aliases)

        async def must_not_build(_revision, _committed):
            raise AssertionError("alias was not stored")

        for query in ({"id": "109", "legacyType": "platform_accounts"},
                      {"id": "7", "legacyType": "channels"}):
            response = await serve(request(cache, db), "account", query, TAGS, must_not_build)
            assert b"A0FC5C02" in response.body
    asyncio.run(scenario())
