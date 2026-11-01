from datetime import datetime, timezone

from api import system_overview as overview

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc).timestamp()


def row(offset: float, **sample):
    return {"observed_at": datetime.fromtimestamp(T0 + offset, timezone.utc), "sample": sample}


def cpu(total, idle, iowait=0):
    return {"total": total, "idle": idle, "iowait": iowait}


def traffic(requests, seconds=300, human5xx=0, pages=0, hits=0, p95=None):
    return {"requests": requests, "seconds": seconds, "human5xx": human5xx, "bot503": 0,
            "pages": pages, "pageHits": hits, "p95": p95}


def test_cpu_percent_from_counter_differences_and_reboots() -> None:
    assert overview.cpu_percent({"cpu": cpu(1000, 800)}, {"cpu": cpu(2000, 1300, 100)}) == 40.0
    assert overview.cpu_percent({"cpu": cpu(5000, 4000)}, {"cpu": cpu(100, 50)}) is None
    assert overview.cpu_percent(None, {"cpu": cpu(100, 50)}) is None


def test_series_buckets_gauges_by_mean_and_counters_by_sum() -> None:
    rows = [
        row(0, cpu=cpu(0, 0)),
        row(300, cpu=cpu(1000, 500), memory={"total": 100, "available": 25}, load=[0.1, 1.0, 0.5],
            traffic=traffic(300, human5xx=2, pages=10, hits=9, p95=0.2),
            pipeline={"analysisLag": 600, "ingestAcceptedAt": T0 + 240},
            collection={"vk": {"ok": 10, "failed": 1}}),
        row(600, cpu=cpu(2000, 1500), memory={"total": 100, "available": 75}, load=[0.1, 3.0, 0.5],
            traffic=traffic(600, pages=10, hits=10, p95=0.5),
            collection={"vk": {"ok": 5, "failed": 0}, "max": {"ok": 3, "failed": 2}}),
    ]
    points = overview.series(rows, 3600)
    assert len(points) == 1
    point = points[0]
    assert point["cpu"] == 25.0 and point["memory"] == 50.0 and point["load"] == 2.0
    assert point["requestsPerMinute"] == 90.0
    assert point["humanErrors"] == 2 and point["hitRatio"] == 95.0 and point["p95Ms"] == 500
    assert point["analysisLagMinutes"] == 10.0 and point["ingestDelayMinutes"] == 1.0
    assert point["collectedOk"] == 18 and point["collectedFailed"] == 3
    assert point["at"] == "2026-10-02T12:00:00+00:00"
    # Снимки раньше начала периода — только опора.
    assert overview.series(rows, 300, since=T0 + 450)[0]["at"] == "2026-10-02T12:10:00+00:00"


def test_restarts_sum_increments_and_ignore_manual_resets() -> None:
    rows = [row(0, units={"restarts": {"api": 2, "web": 0}}),
            row(300, units={"restarts": {"api": 4, "web": 0}}),
            row(600, units={"restarts": {"api": 0, "web": 1}}),
            row(900, units={"restarts": {"api": 1, "web": 1}})]
    assert overview.restarts(rows) == {"api": 3, "web": 1}


def test_checks_flag_stale_collection_failed_units_and_full_disk() -> None:
    now = T0 + 600
    latest = {"units": {"failed": ["m-ranked-target-web.service"]},
              "disk": {"total": 100 * 10**9, "free": 4 * 10**9},
              "memory": {"total": 100, "available": 50},
              "pipeline": {"ingestAcceptedAt": now - 60, "analysisLag": 120, "analysisBacklog": 5,
                           "backupAt": now - 3600}}
    freshness = {"telegram": (now - 60, 2700), "vk": (now - 4000, 2700), "max": (None, 2700),
                 "rutube": (now - 7000, 5400)}
    recent = [row(300, traffic=traffic(10, human5xx=30))]
    states = {check["key"]: check["state"] for check in overview.checks(now, now - 120, latest, recent, freshness)}
    assert states == {"collection.telegram": "ok", "collection.vk": "warn", "collection.max": "fail",
                      "collection.rutube": "warn", "ingest": "ok", "analysis": "ok", "units": "fail",
                      "disk": "fail", "memory": "ok", "backup": "ok", "errors": "warn"}


def test_missing_sampler_is_reported_instead_of_host_checks() -> None:
    result = overview.checks(T0, T0 - 3600, {"disk": {}}, [], {})
    assert result[-1] == {"key": "sample", "label": "Снимок сервера", "state": "fail",
                          "detail": "последний 1.0 ч назад"}
    assert not any(check["key"] == "disk" for check in result)


def _summary_rows():
    now = T0 + 7200
    healthy_disk = {"total": 100 * 10**9, "free": 40 * 10**9}
    full_disk = {"total": 100 * 10**9, "free": 4 * 10**9}
    web_down = {"failed": ["m-ranked-target-web.service"]}
    memory = {"total": 100, "available": 50}
    return now, [
        row(0, collection={"telegram": {"ok": 4, "failed": 0, "lastOk": T0 - 100}}),
        row(3600, units={"failed": []}, disk=healthy_disk, memory=memory,
            collection={"telegram": {"ok": 5, "failed": 1, "lastOk": T0 + 3500},
                        "vk": {"ok": 3, "failed": 0, "lastOk": T0 + 3400}}),
        row(6600, units=web_down, disk=full_disk, memory=memory,
            collection={"telegram": {"ok": 6, "failed": 0, "lastOk": T0 + 6500},
                        "max": {"ok": 1, "failed": 2, "lastOk": T0 + 1000}}),
        row(7140, units=web_down, disk=full_disk, memory=memory,
            pipeline={"ingestAcceptedAt": now - 60, "analysisLag": 120, "analysisBacklog": 5,
                      "backupAt": now - 3600},
            traffic=traffic(10, human5xx=30),
            collection={"telegram": {"ok": 2, "failed": 0, "lastOk": T0 + 7000},
                        "vk": {"ok": 1, "failed": 0}}),
    ]


def test_status_summary_matches_route_logic() -> None:
    # Ожидания сняты со старой логики роута до переноса. У Rutube нет ни одного lastOk.
    now, rows = _summary_rows()
    result = overview.status_summary(rows, now, lambda platform: overview.PROFILE_B_FRESHNESS[platform])
    assert result["sampledAt"] == "2026-10-02T13:59:00+00:00"
    assert result["checks"] == [
        {"key": "collection.telegram", "label": "Сбор · Telegram", "state": "ok", "detail": "последний аккаунт 3 мин назад"},
        {"key": "collection.vk", "label": "Сбор · ВКонтакте", "state": "warn", "detail": "последний аккаунт 1.1 ч назад"},
        {"key": "collection.max", "label": "Сбор · MAX", "state": "fail", "detail": "последний аккаунт 1.7 ч назад"},
        {"key": "collection.rutube", "label": "Сбор · Rutube", "state": "fail", "detail": "успешных циклов за 3 часа нет"},
        {"key": "ingest", "label": "Приём с Сервера 1", "state": "ok", "detail": "последний пакет 1 мин назад"},
        {"key": "analysis", "label": "Очередь анализа", "state": "ok", "detail": "отставание 2 мин, в очереди 5"},
        {"key": "units", "label": "Службы", "state": "fail", "detail": "m-ranked-target-web.service"},
        {"key": "disk", "label": "Диск", "state": "fail", "detail": "свободно 4.0 ГБ (4%)"},
        {"key": "memory", "label": "Память", "state": "ok", "detail": "занято 50%"},
        {"key": "backup", "label": "Резервная копия", "state": "ok", "detail": "последняя 1.0 ч назад"},
        {"key": "errors", "label": "Ошибки для людей", "state": "warn", "detail": "30 ответов 5xx за час"},
    ]
    assert result["collection"] == [
        {"platform": "telegram", "ok": 13, "failed": 1, "lastOkAt": "2026-10-02T13:56:40+00:00"},
        {"platform": "vk", "ok": 4, "failed": 0, "lastOkAt": "2026-10-02T12:56:40+00:00"},
        {"platform": "max", "ok": 1, "failed": 2, "lastOkAt": "2026-10-02T12:16:40+00:00"},
        {"platform": "rutube", "ok": 0, "failed": 0, "lastOkAt": None},
    ]


def test_status_summary_without_rows() -> None:
    result = overview.status_summary([], T0, lambda platform: 2700)
    assert result["sampledAt"] is None
    assert result["collection"] == overview.collection([])
    assert result["checks"] == overview.checks(T0, None, None, [], {p: (None, 2700) for p in overview.PLATFORMS})


def test_profile_b_freshness_matches_health_thresholds() -> None:
    from api.config import Settings
    from api.routes.health import _threshold

    # Порог профиля B — не меньше этих значений; при HEALTH_POLL_INTERVAL_MINUTES до 22
    # (по умолчанию 60 → 7200 с) свежесть из настроек их не перекрывает.
    settings = Settings(deployment_profile="b", poll_interval_minutes=5)
    assert settings.freshness_seconds == 600
    assert {p: _threshold(settings, p) for p in overview.PLATFORMS} == overview.PROFILE_B_FRESHNESS
    assert overview.PROFILE_B_FRESHNESS == {"telegram": 2700, "vk": 2700, "max": 2700, "rutube": 5400}


def test_status_summary_reuses_precomputed_period_rows() -> None:
    now, rows = _summary_rows()
    span = overview.RANGES["3h"][0]
    expected = overview.status_summary(rows, now, lambda platform: 2700, span)
    period = overview.period_rows(rows, now, span)
    assert overview.status_summary(rows, now, lambda platform: 2700, span, period=period) == expected


def test_system_route_computes_period_rows_once(monkeypatch) -> None:
    import asyncio
    import json
    from types import SimpleNamespace

    from api.config import Settings
    from api.routes import system as route
    from api.routes.health import _threshold

    now, rows = _summary_rows()
    settings = Settings(deployment_profile="b", poll_interval_minutes=5)

    class Db:
        async def admin_fetch_all(self, sql, params):
            return rows

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        clock=lambda: now, db=Db(), settings=settings)))
    calls = []
    original = overview.period_rows

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(overview, "period_rows", counting)
    monkeypatch.setattr(route, "_CACHE", {})
    response = asyncio.run(route.system(request, None, "3h"))
    assert len(calls) == 1
    # Ответ тот же, что собирался до правки (двойной расчёт периода).
    span, bucket = overview.RANGES["3h"]
    summary = overview.status_summary(rows, now, lambda platform: _threshold(settings, platform), span)
    period = original(rows, now, span)
    expected = {
        "range": "3h", "sampledAt": summary["sampledAt"], "checks": summary["checks"],
        "alerts": summary["alerts"], "host": overview.host(rows[-1]["sample"], rows[-2]["sample"]),
        "pipeline": overview.pipeline(rows[-1]["sample"]),
        "restarts": overview.restarts(period), "collection": summary["collection"],
        "series": overview.series(period, bucket, since=now - span),
        "backups": overview.backups(rows[-1]["sample"]),
    }
    from fastapi.responses import JSONResponse
    assert response.body == JSONResponse(expected).body   # байт в байт
    assert json.loads(response.body)["restarts"] is not None


def test_open_alerts_are_a_check_and_events_of_the_period_are_listed():
    """01.11.2026 панель писала «всё в порядке», а тревога эталона MAX висела с 22.10."""
    def row(minute, alerts):
        sample = {"v": 1, "pipeline": {}, "units": {"failed": []}, "alerts": alerts}
        return {"observed_at": datetime.fromtimestamp(T0 - (60 - minute) * 60, timezone.utc), "sample": sample}
    opened = {"key": "bots", "kind": "open", "urgent": True, "text": "роботы", "since": T0 - 1800, "at": T0 - 1800}
    closed = {**opened, "kind": "resolve", "at": T0 - 600}
    rows = [row(0, {"at": T0 - 3600, "active": [], "events": []}),
            row(30, {"at": T0 - 1800, "active": [opened], "events": [opened]}),
            row(50, {"at": T0 - 600, "active": [], "events": [closed]}),
            row(59, {"at": T0 - 60, "active": [{"key": "analysis_reference", "text": "эталон MAX",
                                                 "urgent": False, "since": T0 - 9 * 86400}], "events": []})]
    summary = overview.status_summary(rows, T0, lambda platform: 2700, span=3600)
    check = next(item for item in summary["checks"] if item["key"] == "alerts")
    assert (check["state"], check["detail"]) == ("warn", "эталон MAX")
    assert [(item["key"], item["kind"]) for item in summary["alerts"]["events"]] == [("bots", "resolve"),
                                                                                   ("bots", "open")]
    assert summary["alerts"]["active"][0]["text"] == "эталон MAX"
    # Сводка не читается — «нет данных»; профиль без тревог — проверки нет вовсе.
    rows[-1]["sample"]["alerts"] = None
    assert next(item for item in overview.status_summary(rows, T0, lambda platform: 2700)["checks"]
                if item["key"] == "alerts")["state"] == "unknown"
    del rows[-1]["sample"]["alerts"]
    assert all(item["key"] != "alerts" for item in overview.status_summary(rows, T0, lambda platform: 2700)["checks"])
