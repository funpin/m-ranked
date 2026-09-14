"""Кэш публичных ответов: попадания, сброс по тегам и нижняя граница возраста.

На проде уведомление о записи приходит чаще раза в секунду и всегда несёт все
три области сразу. Поведение при таком потоке и проверяется здесь: без нижней
границы возраста кэш не доживал бы до второго читателя.
"""
from __future__ import annotations

import time

import pytest

from api.cache import ResponseCache
from api.cached import cache_key

TAGS = frozenset({"overview"})


def _put(cache: ResponseCache, key: str = "k", value: str = "v") -> None:
    cache.put(key, value, '"etag"', TAGS)


def test_invalidation_marks_stale_but_keeps_serving() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0, stale_seconds=60)
    _put(cache)

    assert cache.invalidate(TAGS) == 1, "запись помечена несвежей"
    entry = cache.get("k")
    assert entry is not None and entry.value == "v", "но продолжает обслуживать"
    assert entry.is_stale(time.monotonic()), "и знает, что несвежая"


def test_fresh_entry_is_not_marked_before_the_floor() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30, stale_seconds=60)
    _put(cache)
    assert cache.invalidate(TAGS) == 1
    entry = cache.get("k")
    assert entry is not None
    # Свежесть держится минимум min_age от рождения: пересчёт не чаще этого.
    assert not entry.is_stale(time.monotonic())
    assert entry.fresh_until >= entry.born_at + 30 - 1e-6


def test_repeated_invalidation_does_not_move_the_deadline() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30, stale_seconds=60)
    _put(cache)
    assert cache.invalidate(TAGS) == 1
    assert cache.invalidate(TAGS) == 0, "повторное уведомление ничего не меняет"
    entry = cache.get("k")
    assert entry is not None
    assert entry.fresh_until <= entry.born_at + 30 + 1e-6


def test_stale_entry_stops_being_served_after_its_window() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0, stale_seconds=0.05)
    _put(cache)
    cache.invalidate(TAGS)
    assert cache.get("k") is not None
    time.sleep(0.08)
    assert cache.get("k") is None, "слишком старую запись отдавать уже нельзя"


def test_untagged_entry_is_not_touched() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0, stale_seconds=60)
    _put(cache)
    assert cache.invalidate(frozenset({"comparison"})) == 0
    entry = cache.get("k")
    assert entry is not None and not entry.is_stale(time.monotonic())


def test_only_one_refresh_runs_per_key() -> None:
    """Второй читатель несвежей записи не запускает второй пересчёт."""
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0, stale_seconds=60)
    assert cache.begin_refresh("k") is True
    assert cache.begin_refresh("k") is False
    cache.end_refresh("k")
    assert cache.begin_refresh("k") is True


def test_ttl_still_caps_a_never_invalidated_entry() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=0.05, min_age_seconds=0, stale_seconds=60)
    _put(cache)
    assert cache.get("k") is not None
    time.sleep(0.08)
    assert cache.get("k") is None, "TTL остаётся страховкой на потерянное уведомление"


def test_negative_windows_are_rejected() -> None:
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=-1)
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, stale_seconds=-1)


def test_live_key_does_not_depend_on_the_current_revision() -> None:
    """Ревизия меняется раз в две секунды и не должна двигать ключ."""
    query = {"platform": "telegram", "period": "1d"}
    assert cache_key("overview", None, query) == cache_key("overview", None, query)


def test_pinned_snapshot_gets_its_own_key() -> None:
    query = {"platform": "telegram", "period": "1d"}
    live = cache_key("overview", None, query)
    pinned = cache_key("overview", 4321, query)
    assert live != pinned
    assert pinned != cache_key("overview", 4322, query)


def test_query_still_separates_keys() -> None:
    assert cache_key("overview", None, {"period": "1d"}) != cache_key(
        "overview", None, {"period": "7d"})
    assert cache_key("overview", None, {"period": "1d"}) != cache_key(
        "rating", None, {"period": "1d"})
