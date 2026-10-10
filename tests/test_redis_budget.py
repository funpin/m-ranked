"""Redis кэша ответов помещается в свою службу, а записи в нём сжаты.

10.10 бюджет данных Redis (maxmemory 256mb) вместе с накладными расходами
аллокатора упёрся в мягкий предел службы (MemoryHigh=288M): ядро отнимало у
Redis страницы, он стоял 60 % времени, и кэш отвечал таймаутами — страницы
пересобирались из базы, p95 и процессор выросли.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from api.cache import Entry, RedisResponseCache, _COMPRESSED

ROOT = Path(__file__).resolve().parents[1]


def _megabytes(text: str) -> float:
    number, unit = re.fullmatch(r"(\d+)\s*([kmg]?)b?", text.strip().lower()).groups()
    return int(number) * {"": 1 / 1048576, "k": 1 / 1024, "m": 1, "g": 1024}[unit]


def test_redis_data_budget_leaves_room_under_the_service_memory_limit():
    conf = (ROOT / "operations/redis/m-ranked.conf").read_text()
    unit = (ROOT / "operations/systemd/m-ranked-target-redis.service").read_text()
    maxmemory = _megabytes(re.search(r"^maxmemory\s+(\S+)", conf, re.M).group(1))
    high = _megabytes(re.search(r"^MemoryHigh=(\S+)", unit, re.M).group(1))
    assert maxmemory <= 0.7 * high, (maxmemory, high)


def test_redis_evicts_only_expiring_entries():
    conf = (ROOT / "operations/redis/m-ranked.conf").read_text()
    policy = re.search(r"^maxmemory-policy\s+(\S+)", conf, re.M).group(1)
    # Набор LRU и наборы тегов без срока жизни: их вытеснение рассогласует кэш.
    assert policy.startswith("volatile-"), policy


def _entry(value: str) -> Entry:
    return Entry(value, '"etag"', 2_000_000_000.0, frozenset({"overview"}), 1_000.0, 1_060.0, 7)


def test_large_entries_are_compressed_and_round_trip_exactly():
    value = json.dumps({"items": [{"observedAt": f"2026-10-10T00:{i % 60:02d}:00Z", "views": i} for i in range(2000)]})
    raw = RedisResponseCache._encode(_entry(value))
    assert raw.startswith(_COMPRESSED)
    assert len(raw) * 4 < len(value)
    decoded = RedisResponseCache._decode(raw)
    assert decoded == _entry(value)


def test_small_entries_and_entries_written_before_compression_still_read():
    small = RedisResponseCache._encode(_entry('{"ok":true}'))
    assert not small.startswith(_COMPRESSED)
    assert RedisResponseCache._decode(small).value == '{"ok":true}'
    legacy = json.dumps({"value": "{}", "etag": "e", "expiresAt": 1.0, "tags": [], "bornAt": 0.0,
                         "freshUntil": 0.5, "revision": 3}).encode()
    assert RedisResponseCache._decode(legacy).revision == 3


def test_corrupt_compressed_entry_is_a_value_error_not_a_crash():
    with pytest.raises(ValueError):
        RedisResponseCache._decode(_COMPRESSED + b"not zlib")
