"""Сводка состояния системы для панели из снимков ops-sample (миграция 0052).

Здесь только арифметика над готовыми строками: проценты процессора из разности
счётчиков соседних снимков, корзины по часу для недельного графика и проверки
с теми же порогами, что у тревог (operations/scripts/alerts.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PLATFORMS = ("telegram", "vk", "max", "rutube")
RANGES = {"day": (86400, 300), "week": (7 * 86400, 3600)}
# Снимок раз в минуту; дольше пяти минут тишины — таймер не работает.
SAMPLE_STALE_SECONDS = 5 * 60


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


def cpu_percent(previous: dict[str, Any] | None, current: dict[str, Any]) -> float | None:
    before, after = (previous or {}).get("cpu") or {}, current.get("cpu") or {}
    try:
        total = after["total"] - before["total"]
        idle = (after["idle"] + after.get("iowait", 0)) - (before["idle"] + before.get("iowait", 0))
    except (KeyError, TypeError):
        return None
    # Перезагрузка обнуляет счётчики: такую пару не считаем.
    if total <= 0 or idle < 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (1 - idle / total))), 1)


def memory_percent(sample: dict[str, Any]) -> float | None:
    memory = sample.get("memory") or {}
    total, available = _number(memory.get("total")), _number(memory.get("available"))
    if not total or available is None:
        return None
    return round(100.0 * (total - available) / total, 1)


def series(rows: list[dict[str, Any]], bucket_seconds: int, since: float = 0.0) -> list[dict[str, Any]]:
    """Точки графиков. rows — снимки по возрастанию времени; снимки раньше
    since (и первая строка) только опорные для разности счётчиков."""
    buckets: dict[int, dict[str, Any]] = {}
    previous = None
    for row in rows:
        sample, at = row["sample"], row["observed_at"].timestamp()
        if previous is None or at < since:
            previous = sample
            continue
        key = int(at // bucket_seconds) * bucket_seconds
        bucket = buckets.setdefault(key, {
            "cpu": [], "memory": [], "load": [], "lag": [], "ingest": [], "p95": [],
            "requests": 0, "seconds": 0.0, "human5xx": 0, "bot503": 0, "pages": 0, "hits": 0,
            "ok": 0, "failed": 0})
        for name, value in (("cpu", cpu_percent(previous, sample)), ("memory", memory_percent(sample)),
                            ("load", _number((sample.get("load") or [None, None])[1]))):
            if value is not None:
                bucket[name].append(value)
        pipeline = sample.get("pipeline") or {}
        lag = _number(pipeline.get("analysisLag"))
        if lag is not None:
            bucket["lag"].append(lag / 60)
        accepted = _number(pipeline.get("ingestAcceptedAt"))
        if accepted is not None:
            bucket["ingest"].append(max(0.0, at - accepted) / 60)
        traffic = sample.get("traffic")
        if isinstance(traffic, dict) and traffic.get("seconds"):
            bucket["requests"] += traffic.get("requests", 0)
            bucket["seconds"] += traffic["seconds"]
            bucket["human5xx"] += traffic.get("human5xx", 0)
            bucket["bot503"] += traffic.get("bot503", 0)
            bucket["pages"] += traffic.get("pages", 0)
            bucket["hits"] += traffic.get("pageHits", 0)
            if _number(traffic.get("p95")) is not None:
                bucket["p95"].append(traffic["p95"] * 1000)
        for counts in (sample.get("collection") or {}).values():
            bucket["ok"] += counts.get("ok", 0)
            bucket["failed"] += counts.get("failed", 0)
        previous = sample

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    return [{
        "at": _iso(key),
        "cpu": mean(bucket["cpu"]),
        "memory": mean(bucket["memory"]),
        "load": mean(bucket["load"]),
        "requestsPerMinute": round(bucket["requests"] * 60 / bucket["seconds"], 1) if bucket["seconds"] else None,
        "humanErrors": bucket["human5xx"],
        "botRejected": bucket["bot503"],
        "hitRatio": round(100.0 * bucket["hits"] / bucket["pages"], 1) if bucket["pages"] else None,
        # Худшая минута корзины, а не средняя: медленные ответы и ищем.
        "p95Ms": round(max(bucket["p95"])) if bucket["p95"] else None,
        "analysisLagMinutes": mean(bucket["lag"]),
        "ingestDelayMinutes": mean(bucket["ingest"]),
        "collectedOk": bucket["ok"],
        "collectedFailed": bucket["failed"],
    } for key, bucket in sorted(buckets.items())]


def restarts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Автоматические перезапуски служб за период: сумма приростов счётчика.
    Ручной перезапуск обнуляет NRestarts — такой шаг не считается."""
    total: dict[str, int] = {}
    previous: dict[str, int] = {}
    for row in rows:
        current = ((row["sample"].get("units") or {}).get("restarts")) or {}
        for unit, value in current.items():
            if unit in previous and value > previous[unit]:
                total[unit] = total.get(unit, 0) + value - previous[unit]
        previous = current
    return {unit: count for unit, count in sorted(total.items()) if count}


def collection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = {platform: {"platform": platform, "ok": 0, "failed": 0, "lastOkAt": None} for platform in PLATFORMS}
    last: dict[str, float] = {}
    for row in rows[1:]:
        for platform, counts in (row["sample"].get("collection") or {}).items():
            if platform not in totals:
                continue
            totals[platform]["ok"] += counts.get("ok", 0)
            totals[platform]["failed"] += counts.get("failed", 0)
            if _number(counts.get("lastOk")) is not None:
                last[platform] = max(last.get(platform, 0.0), counts["lastOk"])
    for platform, value in last.items():
        totals[platform]["lastOkAt"] = _iso(value)
    return list(totals.values())


def host(latest: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    memory, disk, units = latest.get("memory") or {}, latest.get("disk") or {}, latest.get("units") or {}
    swap_total, swap_free = memory.get("swapTotal"), memory.get("swapFree")
    return {
        "cpuPercent": cpu_percent(previous, latest),
        "cores": latest.get("cores"),
        "load": latest.get("load") or [],
        "memoryTotalBytes": memory.get("total"),
        "memoryUsedBytes": (memory["total"] - memory["available"]
                            if memory.get("total") is not None and memory.get("available") is not None else None),
        "swapUsedBytes": swap_total - swap_free if swap_total is not None and swap_free is not None else None,
        "diskTotalBytes": disk.get("total"),
        "diskFreeBytes": disk.get("free"),
        "unitsActive": units.get("active"),
        "unitsTotal": units.get("total"),
        "failedUnits": units.get("failed") or [],
    }


def pipeline(latest: dict[str, Any]) -> dict[str, Any]:
    values = latest.get("pipeline") or {}
    return {
        "ingestAcceptedAt": _iso(_number(values.get("ingestAcceptedAt"))),
        "analysisLagSeconds": _number(values.get("analysisLag")),
        "analysisBacklog": _number(values.get("analysisBacklog")),
        "analysisCompletedAt": _iso(_number(values.get("analysisCompletedAt"))),
        "normsRunAt": _iso(_number(values.get("normsRunAt"))),
        "tailRunAt": _iso(_number(values.get("tailRunAt"))),
        "backupAt": _iso(_number(values.get("backupAt"))),
    }


def _check(key: str, label: str, state: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "state": state, "detail": detail}


def _age(now: float, epoch: float | None) -> float | None:
    return now - epoch if epoch is not None else None


def _minutes(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f} мин"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} ч"
    return f"{seconds / 86400:.1f} сут"


def checks(now: float, sampled_at: float | None, latest: dict[str, Any] | None,
           recent: list[dict[str, Any]], freshness: dict[str, tuple[float | None, int]]) -> list[dict[str, str]]:
    """Сводные проверки. freshness — платформа → (последний успешный сбор, порог в секундах)."""
    result = []
    for platform in PLATFORMS:
        completed, threshold = freshness.get(platform, (None, 2700))
        age = _age(now, completed)
        name = {"telegram": "Telegram", "vk": "ВКонтакте", "max": "MAX", "rutube": "Rutube"}[platform]
        if age is None:
            result.append(_check(f"collection.{platform}", f"Сбор · {name}", "fail", "успешных циклов за 3 часа нет"))
        else:
            state = "ok" if age <= threshold else "warn" if age <= 2 * threshold else "fail"
            result.append(_check(f"collection.{platform}", f"Сбор · {name}", state, f"последний аккаунт {_minutes(age)} назад"))
    sample_age = _age(now, sampled_at)
    if latest is None or sample_age is None or sample_age > SAMPLE_STALE_SECONDS:
        result.append(_check("sample", "Снимок сервера", "fail",
                             "снимков нет" if sample_age is None else f"последний {_minutes(sample_age)} назад"))
        return result
    values = pipeline(latest)
    accepted = _number((latest.get("pipeline") or {}).get("ingestAcceptedAt"))
    ingest_age = _age(now, accepted)
    result.append(_check("ingest", "Приём с Сервера 1",
                         "unknown" if ingest_age is None else "ok" if ingest_age <= 1200 else "warn" if ingest_age <= 3600 else "fail",
                         "метрики нет" if ingest_age is None else f"последний пакет {_minutes(ingest_age)} назад"))
    lag = values["analysisLagSeconds"]
    result.append(_check("analysis", "Очередь анализа",
                         "unknown" if lag is None else "ok" if lag <= 3 * 3600 else "warn" if lag <= 6 * 3600 else "fail",
                         "метрики нет" if lag is None else f"отставание {_minutes(lag)}, в очереди {values['analysisBacklog'] or 0:.0f}"))
    failed = (latest.get("units") or {}).get("failed") or []
    result.append(_check("units", "Службы", "fail" if failed else "ok",
                         ", ".join(failed) if failed else "все службы работают"))
    disk = latest.get("disk") or {}
    if disk.get("total"):
        share = disk["free"] / disk["total"]
        state = "fail" if share < 0.05 else "warn" if share < 0.12 or disk["free"] < 6 * 10**9 else "ok"
        result.append(_check("disk", "Диск", state, f"свободно {disk['free'] / 10**9:.1f} ГБ ({share:.0%})"))
    used = memory_percent(latest)
    if used is not None:
        result.append(_check("memory", "Память", "warn" if used > 90 else "ok", f"занято {used:.0f}%"))
    backup = _number((latest.get("pipeline") or {}).get("backupAt"))
    backup_age = _age(now, backup)
    result.append(_check("backup", "Резервная копия",
                         "unknown" if backup_age is None else "ok" if backup_age <= 36 * 3600 else "fail",
                         "метрики нет" if backup_age is None else f"последняя {_minutes(backup_age)} назад"))
    errors = sum(((row["sample"].get("traffic") or {}).get("human5xx", 0)) for row in recent)
    result.append(_check("errors", "Ошибки для людей", "ok" if errors < 20 else "warn" if errors < 100 else "fail",
                         f"{errors} ответов 5xx за час"))
    return result
