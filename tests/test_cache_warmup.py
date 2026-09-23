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


class JsonResponse:
    def __init__(self, body: object, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self) -> object:
        return self.body


class CatalogClient:
    """Отвечает так, как отвечает API: каталог из одного вуза с одним аккаунтом."""

    def __init__(self, published_at: str) -> None:
        self.published_at = published_at
        self.targets: list[str] = []

    async def get(self, target: str) -> JsonResponse:
        self.targets.append(target)
        path = target.split("?", 1)[0]
        if path == "/api/v1/overview":
            return JsonResponse({"items": [{"accounts": [{"accountId": "acc-1"}]}],
                                 "nextCursor": None})
        if path == "/api/v1/accounts/acc-1":
            return JsonResponse({"institutionLegacyId": 28})
        if path == "/api/v1/accounts/acc-1/publications":
            return JsonResponse({"items": [
                {"publicationId": "post-new", "publishedAt": self.published_at},
                {"publicationId": "post-old", "publishedAt": "2020-01-01T00:00:00+00:00"},
            ]})
        if path == "/api/v1/publications/post-new/history":
            return JsonResponse({
                "publication": {"accountLegacyId": 109, "accountLegacyType": "platform_accounts",
                                "legacyType": "posts"},
                "previousLegacyId": 41, "nextLegacyId": None,
            })
        if path.endswith("/anomaly-analysis"):
            return JsonResponse({}, status_code=404)
        return JsonResponse({})


def test_catalog_warmup_follows_the_requests_pages_make() -> None:
    from datetime import UTC, datetime

    async def scenario() -> None:
        client = CatalogClient(datetime.now(UTC).isoformat())
        warmer = CacheWarmer(client, (), interval_seconds=60, catalog=True,
                             recent_hours=24, concurrency=2)
        succeeded, failed = await warmer.run_once()
        assert failed == 0, "отсутствие анализа — не отказ"
        assert set(client.targets) == {
            "/api/v1/overview?limit=200",
            "/api/v1/accounts/acc-1",
            "/api/v1/accounts/acc-1/publications?limit=100",
            "/api/v1/institutions/28/accounts?platform=all&limit=100",
            "/api/v1/publications/post-new",
            "/api/v1/publications/post-new/history?limit=3000",
            "/api/v1/publications/post-new/anomaly-analysis",
            "/api/v1/accounts/109?legacyType=platform_accounts",
            "/api/v1/publications/41?legacyType=posts",
        }, "старые посты не греются, а связанные запросы страницы поста — греются"
        assert succeeded == len(client.targets)
    asyncio.run(scenario())
