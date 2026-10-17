"""Чтение локального API ботом: точные параметры, ошибки, кэш каталога."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from telegram_bot.source import ApiSource, SourceUnavailable, make_client
from telegram_bot.words import TopQuery

FIXTURES = Path(__file__).parent / "fixtures" / "telegram_bot"
OUR_ID = 4


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def source_with(handler, **kwargs) -> tuple[ApiSource, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = make_client("http://api.test", transport=httpx.MockTransport(wrapped))
    return ApiSource(client, **kwargs), seen


def ok(payload: dict):
    return lambda request: httpx.Response(200, json=payload)


def test_source_requests_match_site_defaults():
    source, seen = source_with(ok(fixture("findings_all.json")))
    asyncio.run(source.findings(institution=None, platform="telegram", period="7d", suspicious=False))
    asyncio.run(source.findings(institution=OUR_ID, platform="all", period="30d", suspicious=True))
    assert seen[0].url.path == "/api/v1/findings"
    # Ровно те параметры, что у страницы по умолчанию: иначе ключ кэша API другой.
    assert dict(seen[0].url.params) == {
        "mode": "all", "platform": "telegram", "period": "7d", "anomalies": "exclude", "limit": "50",
    }
    assert dict(seen[1].url.params) == {
        "mode": "institution", "institution": "4", "platform": "all", "period": "30d",
        "anomalies": "include", "limit": "50",
    }
    assert seen[0].headers["user-agent"] == "m-ranked-telegram-bot/1"


def test_other_endpoints_requests():
    def handler(request):
        name = {
            "/api/v1/findings/anomalous": "anomalous.json",
            "/api/v1/compare/dashboard": "dashboard.json",
            "/api/v1/rating/forecast": "forecast.json",
        }[request.url.path]
        return httpx.Response(200, json=fixture(name))

    source, seen = source_with(handler)
    asyncio.run(source.anomalous(institution=OUR_ID, period="7d"))
    asyncio.run(source.dashboard())
    assert asyncio.run(source.forecast())["month"] == "2026-10"
    assert dict(seen[0].url.params) == {
        "mode": "institution", "institution": "4", "period": "7d", "limit": "50",
    }
    assert dict(seen[1].url.params) == {"period": "7d"}
    assert dict(seen[2].url.params) == {}


def test_forecast_404_is_none():
    source, _ = source_with(lambda request: httpx.Response(404, json={"error": "нет"}))
    assert asyncio.run(source.forecast()) is None


def test_client_settings():
    client = make_client("http://api.test")
    assert client.timeout == httpx.Timeout(30.0)
    assert client.headers["user-agent"] == "m-ranked-telegram-bot/1"
    assert client._trust_env is False
    assert client._transport._pool._max_connections == 1
    asyncio.run(client.aclose())


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(500, text="boom"),
    lambda request: httpx.Response(503, text="busy"),
    lambda request: httpx.Response(404, json={}),
    lambda request: httpx.Response(200, text="не json"),
    lambda request: (_ for _ in ()).throw(httpx.ConnectError("нет связи")),
    lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("долго")),
])
def test_source_unavailable_on_5xx_and_connect_error(handler):
    source, _ = source_with(handler)
    with pytest.raises(SourceUnavailable):
        asyncio.run(source.findings(institution=None, platform="all", period="7d", suspicious=False))
    with pytest.raises(SourceUnavailable):
        asyncio.run(source.dashboard())


def test_institutions_from_findings_and_cached_for_an_hour():
    now = [1000.0]
    source, seen = source_with(ok(fixture("findings_all.json")), clock=lambda: now[0])
    first = asyncio.run(source.institutions())
    assert [(i.legacy_id, i.short_name, i.name) for i in first][:2] == [
        (4, "Дельта", "Университет Дельта"), (11, "Альфа", "Университет Альфа")]
    assert first[3].short_name is None
    asyncio.run(source.institutions())
    assert len(seen) == 1
    now[0] += 3599
    asyncio.run(source.institutions())
    assert len(seen) == 1
    now[0] += 2
    asyncio.run(source.institutions())
    assert len(seen) == 2


def test_top_body_loads_short_platform_when_has_more():
    base = fixture("findings_institution.json")
    base["hasMore"] = True
    base["items"] = [i for i in base["items"] if i["platform"] != "vk"]  # ВК не набрал норму
    vk_body = fixture("findings_institution.json")
    vk_body["items"] = [i for i in vk_body["items"] if i["platform"] == "vk"]

    def handler(request):
        if request.url.params["platform"] == "vk":
            return httpx.Response(200, json=vk_body)
        return httpx.Response(200, json=base)

    source, seen = source_with(handler)
    body = asyncio.run(source.top_body(TopQuery(), OUR_ID))
    platforms = [dict(r.url.params)["platform"] for r in seen]
    # Telegram (4) и Rutube (1) тоже короче трёх? Telegram набрал, Rutube и MAX нет.
    assert platforms[0] == "all"
    assert "vk" in platforms and "telegram" not in platforms
    assert {i["platform"] for i in body["items"]} >= {"vk", "telegram", "rutube"}
    assert sum(1 for i in body["items"] if i["platform"] == "vk") == 2


def test_top_body_single_request_without_has_more():
    source, seen = source_with(ok(fixture("findings_institution.json")))
    asyncio.run(source.top_body(TopQuery(), OUR_ID))
    assert len(seen) == 1
    assert seen[0].url.params["institution"] == "4"
    assert seen[0].url.params["mode"] == "institution"


def test_top_body_all_mode_is_one_request():
    source, seen = source_with(ok(fixture("findings_all.json")))
    asyncio.run(source.top_body(TopQuery(who="all", platform="telegram", suspicious=True), OUR_ID))
    assert len(seen) == 1
    assert dict(seen[0].url.params) == {
        "mode": "all", "platform": "telegram", "period": "7d", "anomalies": "include", "limit": "50"}
