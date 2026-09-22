"""Contract and distributed behaviour of the profile-B response cache."""
from __future__ import annotations

import ast
import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis.asyncio as redis
from starlette.requests import Request

from api.cache import RedisResponseCache, ResponseCache, cache_call
from api.cache_metrics import CacheMetricsPublisher, render_cache_metrics
from api.cached import cache_key, serve

TAGS = frozenset({"overview"})
REDIS_URL = os.environ.get("MRANKED_TEST_REDIS_URL", "")


def run(awaitable):
    return asyncio.run(awaitable)


async def require_redis() -> None:
    if not REDIS_URL:
        pytest.skip("MRANKED_TEST_REDIS_URL не задан; нужен настоящий Redis")
    client = redis.Redis.from_url(REDIS_URL)
    try:
        await client.ping()
        await client.flushdb()
    except Exception as error:
        pytest.skip(f"настоящий Redis недоступен: {error}")
    finally:
        await client.aclose()


def shared_cache(*, ttl: float = 2, fresh: float | None = None, hold: float | None = None,
                 lock: float = 1, namespace: str | None = None) -> RedisResponseCache:
    return RedisResponseCache(
        REDIS_URL, capacity=32, ttl_seconds=ttl, min_age_seconds=0,
        fresh_seconds=fresh, revision_hold_seconds=hold,
        refresh_lock_seconds=lock, timeout_ms=100,
        namespace=namespace or f"test:cache:{uuid4().hex}",
    )


class FakeDB:
    def __init__(self, revision: int = 7) -> None:
        self.revision = revision
        self.calls = 0

    async def fetch_one(self, _query, _parameters=None):
        self.calls += 1
        return {"id": self.revision, "committed_at": datetime(2026, 1, 1, tzinfo=UTC)}


def request(cache, db, *, etag: str | None = None) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(
        cache=cache, db=db, settings=SimpleNamespace(statement_timeout_ms=100),
    ))
    headers = [] if etag is None else [(b"if-none-match", etag.encode())]
    return Request({
        "type": "http", "method": "GET", "path": "/api/v1/overview",
        "query_string": b"", "headers": headers, "app": app,
    })


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_cache_contract_hit_miss_ttl_and_tag_invalidation(backend: str) -> None:
    async def scenario() -> None:
        if backend == "redis":
            await require_redis()
            cache = shared_cache(ttl=.08)
        else:
            cache = ResponseCache(32, .08, 0)
        try:
            assert await cache_call(cache.get("answer")) is None
            await cache_call(cache.put("answer", "value", '"etag"', TAGS))
            hit = await cache_call(cache.get("answer"))
            assert hit is not None and hit.value == "value"
            assert await cache_call(cache.invalidate(TAGS)) == 1
            stale = await cache_call(cache.get("answer"))
            assert stale is not None and await cache_call(cache.is_stale(stale))
            await asyncio.sleep(.1)
            assert await cache_call(cache.get("answer")) is None
        finally:
            await cache_call(cache.close())
    run(scenario())


def test_distributed_stale_refresh_has_one_owner_and_all_readers_return() -> None:
    async def scenario() -> None:
        await require_redis()
        namespace = f"test:cache:{uuid4().hex}"
        caches = [shared_cache(namespace=namespace) for _ in range(6)]
        gate = asyncio.Event()
        builds = 0
        db = FakeDB()

        async def build(revision, committed_at):
            nonlocal builds
            assert revision == 7 and committed_at is not None
            builds += 1
            await gate.wait()
            return {"datasetRevision": revision, "fresh": True}

        try:
            key = cache_key("overview", {})
            await caches[0].set_revision(7, datetime(2026, 1, 1, tzinfo=UTC))
            await caches[0].put(key, '{"stale":true}', '"old"', TAGS)
            await caches[0].invalidate(TAGS)
            responses = await asyncio.wait_for(asyncio.gather(*[
                serve(request(cache, db), "overview", {}, TAGS, build)
                for cache in caches
            ]), timeout=.5)
            await asyncio.sleep(.02)
            assert [response.status_code for response in responses] == [200] * len(caches)
            assert all(response.body == b'{"stale":true}' for response in responses)
            assert builds == 1
            gate.set()
            await asyncio.sleep(.05)
        finally:
            gate.set()
            await asyncio.gather(*(cache.close() for cache in caches))
    run(scenario())


def test_distributed_lock_expires_when_owner_dies() -> None:
    async def scenario() -> None:
        await require_redis()
        namespace = f"test:cache:{uuid4().hex}"
        first = shared_cache(lock=.05, namespace=namespace)
        second = shared_cache(lock=.05, namespace=namespace)
        try:
            assert await first.begin_refresh("answer") is True
            assert await second.begin_refresh("answer") is False
            await asyncio.sleep(.08)
            assert await second.begin_refresh("answer") is True
        finally:
            await first.close()
            await second.close()
    run(scenario())


def test_listener_reconnect_does_not_clear_shared_entries() -> None:
    async def scenario() -> None:
        await require_redis()
        namespace = f"test:cache:{uuid4().hex}"
        first = shared_cache(namespace=namespace)
        second = shared_cache(namespace=namespace)
        try:
            await first.set_revision(7, datetime(2026, 1, 1, tzinfo=UTC))
            await first.put("answer", "value", '"etag"', TAGS)
            await second.clear()
            assert (await first.get("answer")).value == "value"
            assert await second.get_revision() is None
            assert (await first.get_revision())[0] == 7
        finally:
            await first.close()
            await second.close()
    run(scenario())


def test_redis_outage_is_database_miss_not_500_and_is_in_metrics() -> None:
    async def scenario() -> None:
        cache = RedisResponseCache(
            "redis://127.0.0.1:1/0", capacity=8, ttl_seconds=60,
            refresh_lock_seconds=1, timeout_ms=20,
        )
        db = FakeDB()
        builds = 0

        async def build(revision, _committed):
            nonlocal builds
            builds += 1
            return {"datasetRevision": revision, "ok": True}

        try:
            response = await serve(request(cache, db), "overview", {}, TAGS, build)
            assert response.status_code == 200
            assert builds == 1 and db.calls == 1
            assert cache.stats["redis_errors"] > 0
            assert "mranked_api_cache_redis_errors_total" in render_cache_metrics(cache, "redis")
        finally:
            await cache.close()
    run(scenario())


def test_warmed_key_serves_first_request_without_database_and_preserves_etag() -> None:
    async def scenario() -> None:
        await require_redis()
        cache = shared_cache()
        committed = datetime(2026, 1, 1, tzinfo=UTC)
        db = FakeDB()

        async def must_not_build(_revision, _committed):
            raise AssertionError("warmed response rebuilt")

        try:
            await cache.set_revision(7, committed)
            await cache.put(cache_key("overview", {}), '{"warmed":true}', '"warm"', TAGS, 7)
            response = await serve(request(cache, db), "overview", {}, TAGS, must_not_build)
            unchanged = await serve(
                request(cache, db, etag='"warm"'), "overview", {}, TAGS, must_not_build,
            )
            assert response.body == b'{"warmed":true}' and response.headers["etag"] == '"warm"'
            assert unchanged.status_code == 304 and unchanged.body == b""
            assert db.calls == 0
        finally:
            await cache.close()
    run(scenario())


def test_revision_change_serves_the_warm_answer_and_refreshes_it() -> None:
    """Смена ревизии больше не промах: ключ её не содержит. Готовый ответ
    отдаётся сразу, а устаревший по возрасту пересобирается фоном."""
    async def scenario() -> None:
        await require_redis()
        cache = shared_cache(fresh=.01)
        db = FakeDB(revision=8)
        builds = 0

        async def build(revision, _committed):
            nonlocal builds
            builds += 1
            return {"datasetRevision": revision}

        try:
            key = cache_key("overview", {})
            await cache.put(key, '{"datasetRevision":7}', '"old"', TAGS, 7)
            await asyncio.sleep(.02)
            response = await serve(request(cache, db), "overview", {}, TAGS, build)
            assert response.body == b'{"datasetRevision":7}'
            await asyncio.sleep(.05)
            assert builds == 1
            assert (await cache.get(key)).revision == 8
        finally:
            await cache.close()
    run(scenario())


def test_published_revision_is_shared_by_every_worker() -> None:
    async def scenario() -> None:
        await require_redis()
        namespace = f"test:cache:{uuid4().hex}"
        first = shared_cache(namespace=namespace, hold=5)
        second = shared_cache(namespace=namespace, hold=5)
        try:
            committed = datetime(2026, 1, 1, tzinfo=UTC)
            assert (await first.set_revision(7, committed))[0] == 7
            assert (await second.set_revision(8, committed))[0] == 7, "второй принимает первую"
            await first.invalidate(TAGS)
            assert (await second.get_revision())[0] == 7, "уведомление её не сбрасывает"
        finally:
            await first.close()
            await second.close()
    run(scenario())


def test_redis_keys_and_values_do_not_contain_secrets() -> None:
    async def scenario() -> None:
        await require_redis()
        namespace = f"test:cache:{uuid4().hex}"
        cache = shared_cache(namespace=namespace)
        raw = redis.Redis.from_url(REDIS_URL)
        secret = "top-secret-token"
        try:
            # Even a caller mistake in the logical key is opaque in Redis.
            await cache.put(
                f"overview?access_token={secret}", '{"public":true}', '"safe"', TAGS,
            )
            # Secret-shaped public content is refused instead of persisted.
            await cache.put(
                "unsafe-value",
                f'{{"authorization":"Bearer {secret}"}}', '"etag"', TAGS,
            )
            keys = await raw.keys(f"{namespace}:*")
            values = [await raw.get(key) for key in keys if b":entry:" in key]
            material = b"\n".join(keys + [value for value in values if value])
            assert values, "the safe public response must actually reach Redis"
            assert secret.encode() not in material
            assert b"authorization" not in material.lower()
        finally:
            await raw.aclose()
            await cache.close()
    run(scenario())


def test_only_public_route_modules_import_the_cache_serve_boundary() -> None:
    root = Path(__file__).resolve().parents[1] / "api" / "routes"
    users = set()
    for source in root.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "serve" for alias in node.names):
                users.add(source.stem)
    assert users == {"analysis", "compare", "query", "statistics"}
    assert users.isdisjoint({"admin", "exports", "health", "sessions"})


def test_profile_a_constructs_no_redis_client_and_defaults_to_one_worker(monkeypatch) -> None:
    from api import cache as cache_module
    from api.app import create_app
    from api.config import Settings

    monkeypatch.setenv("API_DEPLOYMENT_PROFILE", "a")
    monkeypatch.setenv("API_READ_DB_HOST", "")
    monkeypatch.delenv("API_WORKERS", raising=False)
    monkeypatch.setattr(cache_module.redis.Redis, "from_url", lambda *_a, **_k: (
        (_ for _ in ()).throw(AssertionError("profile A touched Redis"))
    ))
    settings = Settings()
    application = create_app(settings)
    assert settings.workers == 1
    assert type(application.state.cache) is ResponseCache


def test_profile_b_selects_the_shared_cache(monkeypatch) -> None:
    from api.app import create_app
    from api.config import Settings

    monkeypatch.setenv("API_DEPLOYMENT_PROFILE", "b")
    monkeypatch.setenv("API_REDIS_URL", "redis://127.0.0.1:56379/15")
    monkeypatch.setenv("API_READ_DB_HOST", "")
    application = create_app(Settings())
    assert type(application.state.cache) is RedisResponseCache


def test_warmup_config_rejects_private_or_secret_bearing_targets(monkeypatch) -> None:
    from api.config import Settings

    monkeypatch.setenv("API_READ_DB_HOST", "")
    for target in (
        '["/api/v1/admin/jobs"]',
        '["/api/v1/overview?access_token=secret"]',
        '["https://example.org/api/v1/overview"]',
    ):
        monkeypatch.setenv("API_CACHE_WARMUP_TARGETS", target)
        with pytest.raises(ValueError, match="публичным относительным"):
            Settings()


def test_cache_metrics_are_published_atomically(tmp_path) -> None:
    target = tmp_path / "cache.prom"
    cache = ResponseCache(8, 60)
    cache.get("missing")
    publisher = CacheMetricsPublisher(target, cache, "memory")
    publisher.publish()
    rendered = target.read_text(encoding="utf-8")
    assert 'result="miss"} 1' in rendered
    assert 'backend="memory",worker="' in rendered
    assert target.stat().st_mode & 0o777 == 0o640
    assert not [item for item in tmp_path.iterdir() if item.name.startswith(".")]
