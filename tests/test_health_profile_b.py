"""The presentation host receives batches but never completes collector runs."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from api.routes.health import freshness


@pytest.mark.parametrize("rutube_age_minutes,expected_status", [(60, 200), (91, 503)])
def test_profile_b_health_uses_received_account_batches(
    monkeypatch: pytest.MonkeyPatch, rutube_age_minutes: int, expected_status: int,
) -> None:
    now = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

    class Database:
        async def fetch_value(self, _sql: str) -> dict:
            return {
                "asOf": now.isoformat(), "publishedRevision": 42, "rawRevision": 42,
                "runs": {platform: {"started_at": (now - timedelta(days=5)).isoformat(),
                                    "status": "running"}
                         for platform in ("telegram", "vk", "max", "rutube")},
            }

        async def fetch_all(self, _sql: str) -> list[dict]:
            return [
                {"platform": platform, "completed_at": now - timedelta(minutes=age)}
                for platform, age in (("telegram", 20), ("vk", 15), ("max", 30),
                                      ("rutube", rutube_age_minutes))
            ]

    monkeypatch.setattr("api.routes.health._configured",
                        lambda _settings: {platform: True for platform in
                                           ("telegram", "vk", "max", "rutube")})
    app = SimpleNamespace(state=SimpleNamespace(
        db=Database(), settings=SimpleNamespace(deployment_profile="b", freshness_seconds=600),
    ))
    response = asyncio.run(freshness(Request({"type": "http", "app": app})))
    body = json.loads(response.body)
    assert response.status_code == expected_status
    assert body["freshnessSource"] == "delivered_account"
    assert body["platforms"]["telegram"]["thresholdSeconds"] == 2700
    assert body["platforms"]["rutube"]["thresholdSeconds"] == 5400
    assert body["platforms"]["rutube"]["fresh"] is (expected_status == 200)
