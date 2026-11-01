"""Серверы для вкладки «Серверы», процессы сборщиков для вкладки «Система» и
для бота: состояние сервера, ряды ресурсов, пропуски замеров.

Здесь только арифметика над готовыми строками. Основной сервер меряет себя
снимками ops-sample (host_sample) и живым буфером API, остальные — минутными
точками агента узла (server_node_sample); процессы любого сервера — в
последнем отчёте его агента (server_node.report → processes).
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable, Mapping

from .system_overview import PLATFORMS, PROFILE_B_FRESHNESS, cpu_percent, memory_percent

# Агент отчитывается раз в минуту; три пропуска подряд — сервер не на связи.
# Снимок основного — тоже раз в минуту, но таймеру даём пять минут, как проверке.
ONLINE_SECONDS = {"main": 300, "node": 180}
# Перезапуск свежий, пока прошло меньше этого: панель и бот говорят
# «перезапущен N мин назад», а не «работает».
RESTART_WINDOW_SECONDS = 600
# Пропуск — соседние замеры дальше этого или 2,5 обычных шага.
GAP_MIN_SECONDS = 150
GAP_STEP_FACTOR = 2.5
GAPS_LIMIT = 50
# Службы, перезапуск которых и есть «перезапуск версии» сервера.
MAIN_SERVICES = ("api", "web", "transfer-ingest", "anomaly-analysis")
NODE_SERVICES = ("collector@telegram", "collector@vk", "collector@max", "collector@rutube", "transfer-sender")

LIST_SQL = """
SELECT id, display_name, role, state, platforms, last_seen_at, agent_version, report - 'files' AS report
  FROM ops_and_admin.server_node
 WHERE role = 'main' OR state IN ('active', 'draining')
 ORDER BY role <> 'main', id
"""
NODE_SAMPLES_SQL = """
SELECT observed_at, cpu_percent, memory_total_bytes, memory_available_bytes, swap_used_bytes, load1,
       disk_total_bytes, disk_free_bytes, net_rx_bytes_per_second, net_tx_bytes_per_second,
       disk_read_bytes_per_second, disk_write_bytes_per_second, release
  FROM ops_and_admin.server_node_sample
 WHERE node_id = %(node)s AND observed_at > now() - make_interval(secs => %(seconds)s)
 ORDER BY observed_at
"""
# Ресурсы основного — только нужные ключи снимка, без трафика и сбора.
MAIN_SAMPLES_SQL = """
SELECT observed_at, jsonb_build_object('cpu', sample->'cpu', 'memory', sample->'memory', 'load', sample->'load',
       'disk', sample->'disk', 'cores', sample->'cores', 'units', sample->'units', 'rel', sample->'rel') AS sample
  FROM ops_and_admin.host_sample
 WHERE observed_at >= now() - make_interval(secs => %(seconds)s)
 ORDER BY observed_at
"""
# Циклы площадок за период — по индексу (platform, started_at). Строки
# моста SQLite — не циклы сборщика.
RUNS_SQL = """
SELECT platform::text AS platform, count(*)::integer AS runs,
       count(*) FILTER (WHERE status = 'succeeded')::integer AS succeeded,
       count(*) FILTER (WHERE status = 'partial')::integer AS partial,
       count(*) FILTER (WHERE status = 'failed')::integer AS failed,
       coalesce(sum(account_count), 0)::bigint AS accounts, coalesce(sum(error_count), 0)::bigint AS errors,
       extract(epoch FROM max(started_at)) AS last_started,
       extract(epoch FROM max(completed_at)) AS last_completed,
       extract(epoch FROM min(started_at) FILTER (WHERE completed_at IS NULL AND status = 'running')) AS running_since,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM completed_at - started_at))
         FILTER (WHERE completed_at IS NOT NULL) AS median_seconds
  FROM ingest.collection_run
 WHERE platform::text = ANY(%(platforms)s) AND started_at >= now() - make_interval(secs => %(seconds)s)
   AND collector_version NOT LIKE 'sqlite-bridge/%%'
 GROUP BY platform
"""
# Последний цикл до периода — опора: пропуск мог начаться раньше периода.
RUN_STARTS_SQL = """
SELECT platform::text AS platform, extract(epoch FROM started_at) AS started
  FROM ingest.collection_run
 WHERE platform::text = ANY(%(platforms)s) AND started_at >= now() - make_interval(secs => %(seconds)s)
   AND collector_version NOT LIKE 'sqlite-bridge/%%'
 ORDER BY platform, started_at
"""


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


def _report(row: Mapping[str, Any]) -> dict[str, Any]:
    return row["report"] if isinstance(row.get("report"), dict) else {}


def processes(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _report(row).get("processes")
    return value if isinstance(value, dict) else {}


def _recent_restart(tasks: Iterable[Mapping[str, Any]], names: tuple[str, ...], now: float) -> float | None:
    """Самый поздний старт ключевой службы, если он свежий."""
    starts = [_number(task.get("since")) for task in tasks
              if task.get("unit") in names and not task.get("scheduled") and task.get("active") == "active"]
    latest = max((value for value in starts if value is not None), default=None)
    return latest if latest is not None and now - latest <= RESTART_WINDOW_SECONDS else None


def status(row: Mapping[str, Any], now: float, last_sample: float | None = None) -> dict[str, Any]:
    """Состояние сервера одной строкой: обновляется, перезапущен, нет связи,
    сбой службы или работает. last_sample — время последнего снимка основного."""
    main = row["role"] == "main"
    seen = last_sample if main else (row["last_seen_at"].timestamp() if row.get("last_seen_at") else None)
    found = processes(row)
    tasks = [task for task in found.get("tasks") or [] if isinstance(task, dict)]
    release = found.get("release")
    deploy = found.get("deploy") if isinstance(found.get("deploy"), dict) else None
    failed = sorted(task["unit"] for task in tasks if task.get("active") == "failed" and not task.get("scheduled"))
    result: dict[str, Any] = {"release": release, "seenAt": iso(seen), "since": None, "failed": failed}
    if seen is None or now - seen > ONLINE_SECONDS["main" if main else "node"]:
        return {**result, "state": "offline", "label": "нет связи",
                "detail": "отчётов не было" if seen is None else "последний отчёт давно"}
    if deploy is not None:
        version = deploy.get("version") or "новой версии"
        phase = f" · {deploy['phase']}" if deploy.get("phase") else ""
        return {**result, "state": "updating", "label": f"обновляется до {version}", "detail": f"выкатка{phase}",
                "since": iso(_number(deploy.get("startedAt")))}
    boot = _number(found.get("bootAt"))
    if boot is not None and now - boot <= RESTART_WINDOW_SECONDS:
        return {**result, "state": "restarted", "label": "перезагружен", "detail": "машина загрузилась недавно",
                "since": iso(boot)}
    restarted = _recent_restart(tasks, MAIN_SERVICES if main else NODE_SERVICES, now)
    if restarted is not None:
        return {**result, "state": "restarted", "label": "перезапущен",
                "detail": f"службы перезапущены{f' · {release}' if release else ''}", "since": iso(restarted)}
    if failed:
        return {**result, "state": "degraded", "label": "сбой службы", "detail": ", ".join(failed)}
    return {**result, "state": "ok", "label": "работает", "detail": release or ""}


def gaps(points: list[tuple[float, str | None]], now: float, start: float,
         step: float | None = None) -> dict[str, Any]:
    """Пропуски замеров: соседние точки дальше max(150 с, 2,5 шага). Шаг —
    медиана промежутков, если не задан. points — (время, версия выпуска) по
    возрастанию, с одной точкой до start как опорой. Если версия по краям
    пропуска разная — пропуск пришёлся на обновление."""
    times = [at for at, _ in points]
    intervals = [after - before for before, after in zip(times, times[1:]) if after > before]
    usual = step if step is not None else (median(intervals) if intervals else 60.0)
    threshold = max(GAP_MIN_SECONDS, GAP_STEP_FACTOR * usual)
    found = []
    if points and points[0][0] - start > threshold:
        # Опоры до периода нет: замеров не было с самого его начала.
        found.append({"from": iso(start), "to": iso(points[0][0]), "seconds": round(points[0][0] - start),
                      "cause": None})
    for (before, release_before), (after, release_after) in zip(points, points[1:]):
        if after - before <= threshold or after < start:
            continue
        cause = (f"обновление {release_before} → {release_after}"
                 if release_before and release_after and release_before != release_after else None)
        found.append({"from": iso(max(before, start)), "to": iso(after), "seconds": round(after - max(before, start)),
                      "cause": cause})
    if points and now - points[-1][0] > threshold:
        found.append({"from": iso(max(points[-1][0], start)), "to": None,
                      "seconds": round(now - max(points[-1][0], start)), "cause": None})
    elif not points:
        found.append({"from": iso(start), "to": None, "seconds": round(now - start), "cause": None})
    found.reverse()
    return {"stepSeconds": round(usual), "count": len(found), "seconds": sum(item["seconds"] for item in found),
            "items": found[:GAPS_LIMIT]}


def node_point(row: Mapping[str, Any]) -> dict[str, Any]:
    """Минутная точка агента в форме живой точки панели."""
    total, available = _number(row.get("memory_total_bytes")), _number(row.get("memory_available_bytes"))
    return {
        "at": iso(row["observed_at"].timestamp()),
        "cpu": _number(row.get("cpu_percent")),
        "memory": round(100.0 * (total - available) / total, 1) if total and available is not None else None,
        "memoryUsedBytes": total - available if total and available is not None else None,
        "swapUsedBytes": _number(row.get("swap_used_bytes")),
        "load": _number(row.get("load1")),
        "netRxBytesPerSecond": _number(row.get("net_rx_bytes_per_second")),
        "netTxBytesPerSecond": _number(row.get("net_tx_bytes_per_second")),
        "diskReadBytesPerSecond": _number(row.get("disk_read_bytes_per_second")),
        "diskWriteBytesPerSecond": _number(row.get("disk_write_bytes_per_second")),
    }


def main_points(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Минутные снимки основного в той же форме; первая строка — опора."""
    result, previous = [], None
    for row in rows:
        sample = row["sample"]
        memory = sample.get("memory") or {}
        total, available = _number(memory.get("total")), _number(memory.get("available"))
        swap_total, swap_free = _number(memory.get("swapTotal")), _number(memory.get("swapFree"))
        if previous is not None:
            result.append({
                "at": iso(row["observed_at"].timestamp()), "cpu": cpu_percent(previous, sample),
                "memory": memory_percent(sample),
                "memoryUsedBytes": total - available if total and available is not None else None,
                "swapUsedBytes": swap_total - swap_free if swap_total is not None and swap_free is not None else None,
                "load": _number((sample.get("load") or [None])[0]),
                "netRxBytesPerSecond": None, "netTxBytesPerSecond": None,
                "diskReadBytesPerSecond": None, "diskWriteBytesPerSecond": None,
            })
        previous = sample
    return result


def series(points: list[dict[str, Any]], bucket_seconds: int) -> list[dict[str, Any]]:
    """Корзины графика: средние по шагу; пустая корзина — разрыв линии."""
    keys = ("cpu", "memory", "load", "netRxBytesPerSecond", "netTxBytesPerSecond",
            "diskReadBytesPerSecond", "diskWriteBytesPerSecond")
    buckets: dict[int, dict[str, list[float]]] = {}
    for point in points:
        key = int(datetime.fromisoformat(point["at"]).timestamp() // bucket_seconds) * bucket_seconds
        bucket = buckets.setdefault(key, {name: [] for name in keys})
        for name in keys:
            if point.get(name) is not None:
                bucket[name].append(point[name])
    return [{"at": iso(key), **{name: round(sum(values) / len(values), 2) if values else None
                                for name, values in bucket.items()}}
            for key, bucket in sorted(buckets.items())]


def host_view(row: Mapping[str, Any], latest: dict[str, Any] | None) -> dict[str, Any]:
    """Последние ресурсы сервера-сборщика из отчёта агента."""
    metrics = _report(row).get("metrics") or {}
    memory_total, available = _number(metrics.get("memoryTotalBytes")), _number(metrics.get("memoryAvailableBytes"))
    tasks = [task for task in processes(row).get("tasks") or [] if isinstance(task, dict) and not task.get("scheduled")]
    return {
        "cpuPercent": _number(metrics.get("cpuPercent")) if latest is None else latest.get("cpu"),
        "cores": int(metrics["cpus"]) if _number(metrics.get("cpus")) else None,
        "load": [value for value in (_number(metrics.get(key)) for key in ("load1", "load5", "load15")) if value is not None],
        "memoryTotalBytes": memory_total,
        "memoryUsedBytes": memory_total - available if memory_total and available is not None else None,
        "swapUsedBytes": _number(metrics.get("swapUsedBytes")),
        "diskTotalBytes": _number(metrics.get("diskTotalBytes")),
        "diskFreeBytes": _number(metrics.get("diskFreeBytes")),
        "unitsActive": sum(1 for task in tasks if task.get("active") == "active") if tasks else None,
        "unitsTotal": len(tasks) if tasks else None,
        "failedUnits": sorted(task["unit"] for task in tasks if task.get("active") == "failed"),
    }


def tasks_view(row: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Службы и задания по расписанию из отчёта агента, время — ISO."""
    result = []
    for task in processes(row).get("tasks") or [] if row else []:
        if not isinstance(task, dict):
            continue
        result.append({
            "unit": str(task.get("unit", "")), "scheduled": bool(task.get("scheduled")),
            "active": task.get("active") or "", "sub": task.get("sub") or "", "result": task.get("result"),
            "since": iso(_number(task.get("since"))), "startedAt": iso(_number(task.get("startedAt"))),
            "exitedAt": iso(_number(task.get("exitedAt"))), "restarts": _number(task.get("restarts")),
            "lastAt": iso(_number(task.get("lastAt"))), "nextAt": iso(_number(task.get("nextAt"))),
        })
    return result


def server_item(row: Mapping[str, Any], now: float, last_sample: float | None = None) -> dict[str, Any]:
    return {"id": row["id"], "displayName": row["display_name"], "role": row["role"], "state": row["state"],
            "platforms": sorted(row.get("platforms") or [], key=PLATFORMS.index),
            "status": status(row, now, last_sample)}


def collector_platforms(row: Mapping[str, Any]) -> list[str]:
    """Площадки сборщика; единственный сборщик без назначения собирает всё."""
    return sorted(row.get("platforms") or [], key=PLATFORMS.index) or list(PLATFORMS)


def cycle_gaps(starts: list[Mapping[str, Any]], platforms: list[str], now: float, start: float) -> dict[str, list]:
    """Пропуски сбора по журналу циклов: старты дальше порога свежести площадки.
    Сборщик пишет только изменения, поэтому пробел ищется по циклам, а не по снимкам."""
    by_platform: dict[str, list[tuple[float, str | None]]] = {platform: [] for platform in platforms}
    for row in starts:
        if row["platform"] in by_platform and _number(row.get("started")) is not None:
            by_platform[row["platform"]].append((float(row["started"]), None))
    result = {}
    for platform, points in by_platform.items():
        threshold = PROFILE_B_FRESHNESS.get(platform, 2700)
        # Шаг задан порогом: ждать дольше него — уже тревога сбора.
        result[platform] = gaps(points, now, start, step=threshold / GAP_STEP_FACTOR)["items"]
    return result


def collector_view(row: Mapping[str, Any], runs: list[Mapping[str, Any]], starts: list[Mapping[str, Any]],
                   pipeline: Mapping[str, Any] | None, now: float, span: float) -> dict[str, Any]:
    """Процессы сервера-сборщика: циклы по площадкам, отправитель, задания."""
    found = processes(row)
    platforms = collector_platforms(row)
    metrics = found.get("collectors") if isinstance(found.get("collectors"), dict) else {}
    by_platform = {item["platform"]: item for item in runs}
    gaps_found = cycle_gaps(starts, platforms, now, now - span)
    cycles = []
    for platform in platforms:
        run = by_platform.get(platform) or {}
        live = metrics.get(platform) or {}
        cycles.append({
            "platform": platform,
            "runs": run.get("runs", 0), "succeeded": run.get("succeeded", 0), "partial": run.get("partial", 0),
            "failed": run.get("failed", 0), "accounts": run.get("accounts", 0), "errors": run.get("errors", 0),
            "lastStartedAt": iso(_number(run.get("last_started"))),
            "lastCompletedAt": iso(_number(run.get("last_completed"))),
            "runningSince": iso(_number(run.get("running_since"))),
            "medianSeconds": _number(run.get("median_seconds")),
            "lastSuccessAt": iso(_number(live.get("lastSuccessAt"))),
            "cycleSeconds": _number(live.get("cycleSeconds")),
            "scheduleLagSeconds": _number(live.get("scheduleLagSeconds")),
            "freshnessSeconds": PROFILE_B_FRESHNESS.get(platform, 2700),
            "gaps": gaps_found.get(platform, []),
        })
    transfer = found.get("transfer") if isinstance(found.get("transfer"), dict) else {}
    pipeline = pipeline or {}
    accepted, created = _number(pipeline.get("ingestAcceptedAt")), _number(pipeline.get("ingestBatchCreatedAt"))
    return {
        "server": server_item(row, now),
        "cycles": cycles,
        "transfer": {
            "backlog": _number(transfer.get("backlog")), "delivered": _number(transfer.get("delivered")),
            "failures": _number(transfer.get("failures")),
            "lastAcceptedAt": iso(accepted),
            "queueDelaySeconds": round(accepted - created) if accepted is not None and created is not None else None,
        },
        "tasks": tasks_view(row),
    }
