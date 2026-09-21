"""The scheduled warmer is a fault-isolated ordinary public HTTP client."""
from __future__ import annotations

import asyncio

from api.cache_warmup import CacheWarmer


class Response:
    def __init__(self, failing: bool = False) -> None:
        self.failing = failing

    def raise_for_status(self) -> None:
        if self.failing:
            raise RuntimeError("boom")


class Client:
    def __init__(self) -> None:
        self.targets: list[str] = []

    async def get(self, target: str) -> Response:
        self.targets.append(target)
        return Response(failing="broken" in target)


def test_warmup_targets_are_configured_and_failures_are_isolated(tmp_path) -> None:
    async def scenario() -> None:
        client = Client()
        metrics = tmp_path / "warmup.prom"
        warmer = CacheWarmer(
            client, ("/api/v1/overview", "/api/v1/broken", "/api/v1/statistics"),
            interval_seconds=60, metrics_file=metrics,
        )
        assert await warmer.run_once() == (2, 1)
        assert client.targets == [
            "/api/v1/overview", "/api/v1/broken", "/api/v1/statistics",
        ]
        rendered = metrics.read_text(encoding="utf-8")
        assert 'result="success"} 2' in rendered
        assert 'result="failure"} 1' in rendered
        assert warmer.last_completed_unixtime > 0
    asyncio.run(scenario())
