#!/usr/bin/env python3
"""Compare process-local and shared response caches against a real Redis.

The miss sample is cache lookup plus filling a deterministic 4 KiB response;
it deliberately excludes the database query, which is identical for both
backends. The multi-worker hit-rate probe warms only worker zero, then routes
one first request for each key across four workers.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.cache import RedisResponseCache, ResponseCache, cache_call

TAGS = frozenset({"overview"})


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


async def latency(cache: Any, samples: int, payload: str) -> dict[str, float]:
    await cache_call(cache.put("hit", payload, '"etag"', TAGS))
    hits: list[float] = []
    misses: list[float] = []
    for index in range(samples):
        started = time.perf_counter_ns()
        assert await cache_call(cache.get("hit")) is not None
        hits.append((time.perf_counter_ns() - started) / 1_000_000)
        key = f"miss-{index}"
        started = time.perf_counter_ns()
        assert await cache_call(cache.get(key)) is None
        await cache_call(cache.put(key, payload, '"etag"', TAGS))
        misses.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "hit_p50_ms": statistics.median(hits),
        "hit_p95_ms": percentile(hits, .95),
        "miss_fill_p50_ms": statistics.median(misses),
        "miss_fill_p95_ms": percentile(misses, .95),
    }


async def first_wave_hit_rate(caches: list[Any], keys: int, payload: str) -> float:
    for index in range(keys):
        await cache_call(caches[0].put(f"hot-{index}", payload, '"etag"', TAGS))
    hits = 0
    for index in range(keys):
        cache = caches[index % len(caches)]
        hits += int(await cache_call(cache.get(f"hot-{index}")) is not None)
    return hits / keys


def local_memory(workers: int, entries: int, payload_size: int) -> int:
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    caches = [ResponseCache(entries + 1, 600) for _ in range(workers)]
    for worker, cache in enumerate(caches):
        for index in range(entries):
            # Encode/decode forces a distinct string object per worker.
            payload = (("x" * (payload_size - 32)) + f"-{worker}-{index}").encode().decode()
            cache.put(f"hot-{index}", payload, '"etag"', TAGS)
    used = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    return used


async def redis_memory(url: str, workers: int, entries: int, payload: str) -> int:
    raw = redis.Redis.from_url(url)
    await raw.flushdb()
    before = int((await raw.info("memory"))["used_memory"])
    namespace = f"bench:cache:{uuid4().hex}"
    caches = [RedisResponseCache(
        url, capacity=entries + 1, ttl_seconds=600, namespace=namespace,
    ) for _ in range(workers)]
    try:
        for cache in caches:
            for index in range(entries):
                await cache.put(f"hot-{index}", payload, '"etag"', TAGS)
        after = int((await raw.info("memory"))["used_memory"])
        return max(0, after - before)
    finally:
        await asyncio.gather(*(cache.close() for cache in caches))
        await raw.aclose()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default=os.environ.get(
        "MRANKED_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    parser.add_argument("--samples", type=int, default=500)
    parser.add_argument("--entries", type=int, default=256)
    parser.add_argument("--payload-bytes", type=int, default=4096)
    args = parser.parse_args()
    payload = json.dumps({"value": "x" * (args.payload_bytes - 20)}, separators=(",", ":"))

    raw = redis.Redis.from_url(args.redis_url)
    try:
        await raw.ping()
        await raw.flushdb()
    finally:
        await raw.aclose()

    local = ResponseCache(args.samples + 2, 600)
    shared = RedisResponseCache(
        args.redis_url, capacity=args.samples + 2, ttl_seconds=600,
        namespace=f"bench:latency:{uuid4().hex}",
    )
    try:
        latency_results = {
            "memory_lru": await latency(local, args.samples, payload),
            "redis": await latency(shared, args.samples, payload),
        }
    finally:
        await shared.close()

    local_one = [ResponseCache(args.entries + 1, 600)]
    local_four = [ResponseCache(args.entries + 1, 600) for _ in range(4)]
    namespace = f"bench:hitrate:{uuid4().hex}"
    redis_one = [RedisResponseCache(
        args.redis_url, capacity=args.entries + 1, ttl_seconds=600, namespace=namespace,
    )]
    redis_four = [RedisResponseCache(
        args.redis_url, capacity=args.entries + 1, ttl_seconds=600, namespace=namespace,
    ) for _ in range(4)]
    try:
        hit_rates = {
            "memory_lru_one_worker": await first_wave_hit_rate(local_one, args.entries, payload),
            "memory_lru_four_workers": await first_wave_hit_rate(local_four, args.entries, payload),
            "redis_one_worker": await first_wave_hit_rate(redis_one, args.entries, payload),
            "redis_four_workers": await first_wave_hit_rate(redis_four, args.entries, payload),
        }
    finally:
        await asyncio.gather(*(cache.close() for cache in redis_one + redis_four))

    memory = {
        "memory_lru_one_worker_bytes": local_memory(1, args.entries, args.payload_bytes),
        "memory_lru_four_workers_bytes": local_memory(4, args.entries, args.payload_bytes),
        "redis_one_worker_server_bytes": await redis_memory(
            args.redis_url, 1, args.entries, payload),
        "redis_four_workers_server_bytes": await redis_memory(
            args.redis_url, 4, args.entries, payload),
    }
    print(json.dumps({
        "samples": args.samples,
        "entries": args.entries,
        "payload_bytes": len(payload.encode()),
        "latency": latency_results,
        "first_wave_hit_rate": hit_rates,
        "memory": memory,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
