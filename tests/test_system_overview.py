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
