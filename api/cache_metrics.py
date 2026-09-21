"""Bounded Prometheus textfiles for response-cache and warmup health."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def atomic_write(path: Path, content: str) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise OSError(f"metrics path must have a provisioned absolute parent: {path}")
    descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def render_cache_metrics(cache: object, backend: str, worker: int | None = None) -> str:
    stats = getattr(cache, "stats")
    labels = f'backend="{backend}",worker="{worker or os.getpid()}"'
    stale_hits = stats["stale_hits"]
    fresh_hits = max(0, stats["hits"] - stale_hits)
    lines = [
        "# TYPE mranked_api_cache_backend_info gauge",
        f"mranked_api_cache_backend_info{{{labels}}} 1",
        "# TYPE mranked_api_cache_requests_total counter",
        f'mranked_api_cache_requests_total{{{labels},result="hit"}} {fresh_hits}',
        f'mranked_api_cache_requests_total{{{labels},result="miss"}} {stats["misses"]}',
        f'mranked_api_cache_requests_total{{{labels},result="stale"}} {stale_hits}',
        "# TYPE mranked_api_cache_entries gauge",
        f"mranked_api_cache_entries{{{labels}}} {stats['entries']}",
        "# TYPE mranked_api_cache_refresh_total counter",
        f'mranked_api_cache_refresh_total{{{labels},result="acquired"}} '
        f'{stats.get("refresh_acquired", 0)}',
        f'mranked_api_cache_refresh_total{{{labels},result="contended"}} '
        f'{stats.get("refresh_contended", 0)}',
        "# TYPE mranked_api_cache_redis_errors_total counter",
        f"mranked_api_cache_redis_errors_total{{{labels}}} {stats.get('redis_errors', 0)}",
        "# TYPE mranked_api_cache_sample_unixtime gauge",
        f"mranked_api_cache_sample_unixtime{{{labels}}} {time.time():.6f}",
    ]
    return "\n".join(lines) + "\n"


class CacheMetricsPublisher:
    def __init__(self, path: Path | None, cache: object, backend: str,
                 interval_seconds: float = 15.0) -> None:
        self.path = path
        self.cache = cache
        self.backend = backend
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.path is not None:
            self._task = asyncio.create_task(self._run(), name="cache-metrics")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self.publish()

    def publish(self) -> None:
        if self.path is None:
            return
        try:
            atomic_write(self.path, render_cache_metrics(self.cache, self.backend))
        except OSError:
            logger.warning("cache metrics publish failed", exc_info=True)

    async def _run(self) -> None:
        while True:
            self.publish()
            await asyncio.sleep(self.interval_seconds)


def render_warmup_metrics(
    *, succeeded: int, failed: int, last_completed_unixtime: float,
) -> str:
    return "\n".join([
        "# TYPE mranked_api_cache_warmup_requests_total counter",
        f'mranked_api_cache_warmup_requests_total{{result="success"}} {succeeded}',
        f'mranked_api_cache_warmup_requests_total{{result="failure"}} {failed}',
        "# TYPE mranked_api_cache_warmup_last_completed_unixtime gauge",
        f"mranked_api_cache_warmup_last_completed_unixtime {last_completed_unixtime:.6f}",
    ]) + "\n"
