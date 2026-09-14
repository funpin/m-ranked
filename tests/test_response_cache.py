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


def test_entry_survives_invalidation_until_the_floor() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30)
    _put(cache)

    assert cache.invalidate(TAGS) == 0, "свежая запись не выбрасывается"
    entry = cache.get("k")
    assert entry is not None and entry.value == "v"
    # Жизнь укорочена до границы, а не до полного TTL.
    assert entry.expires_at <= entry.born_at + 30 + 1e-6


def test_repeated_invalidation_does_not_extend_the_floor() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=30)
    _put(cache)
    for _ in range(5):
        cache.invalidate(TAGS)
    entry = cache.get("k")
    assert entry is not None
    assert entry.expires_at <= entry.born_at + 30 + 1e-6


def test_aged_entry_is_dropped_by_invalidation() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0)
    _put(cache)
    assert cache.invalidate(TAGS) == 1
    assert cache.get("k") is None


def test_untagged_entry_is_not_touched() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0)
    _put(cache)
    assert cache.invalidate(frozenset({"comparison"})) == 0
    assert cache.get("k") is not None


def test_entry_expires_at_the_floor() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=0.05)
    _put(cache)
    cache.invalidate(TAGS)
    assert cache.get("k") is not None
    time.sleep(0.08)
    assert cache.get("k") is None, "после границы запись больше не отдаётся"


def test_floor_never_outlives_the_ttl() -> None:
    cache = ResponseCache(capacity=8, ttl_seconds=1, min_age_seconds=600)
    _put(cache)
    cache.invalidate(TAGS)
    entry = cache.get("k")
    assert entry is not None
    assert entry.expires_at <= entry.born_at + 1 + 1e-6


def test_negative_floor_is_rejected() -> None:
    with pytest.raises(ValueError):
        ResponseCache(capacity=8, ttl_seconds=600, min_age_seconds=-1)


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
