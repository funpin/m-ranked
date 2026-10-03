"""Снимок состояния Сервера 2 для панели управления.

Раз в минуту таймер собирает то, что уже лежит на машине: счётчики
процессора и памяти из /proc, состояние служб systemd, прирост журнала nginx
с прошлого снимка и метрики конвейера, которые службы и так пишут для
node_exporter. Снимок — одна строка JSON в ops_and_admin.host_sample; панель
читает готовые строки и ничего не считает на запрос.

Размеры каталогов проекта меряются раз в шесть часов: обход страничного кэша
стоит заметно дороже всего остального снимка. Хранится 30 суток — около
43 000 строк по килобайту.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("ops-sample")

VERSION = 1
RETENTION_DAYS = 30
SIZE_INTERVAL_SECONDS = 6 * 3600
BOT_CLASSES = frozenset({"ai_user", "ai_search", "ai_training", "crawler"})
CACHE_HITS = frozenset({"HIT", "STALE", "UPDATING", "REVALIDATED"})
# Не больше 64 МБ журнала за проход и 20 000 времён ответа на перцентили:
# после долгого простоя таймера снимок не должен съесть память службы.
LOG_CHUNK_BYTES = 64 * 1024 * 1024
LATENCY_SAMPLES = 20_000
# Службы, перезапуски которых — признак нестабильности, а не расписания.
LONG_RUNNING = (
    "m-ranked-target-api.service",
    "m-ranked-target-web.service",
    "m-ranked-target-transfer-ingest.service",
    "m-ranked-target-anomaly-analysis.service",
    "m-ranked-target-redis.service",
    "nginx.service",
)

# 127.0.0.1 [25/Sep/2026:22:55:35 +0300] "GET / HTTP/1.1" 200 724 0.000 human HIT "UA"
LINE = re.compile(
    r'^\S+ \[[^\]]+\] "(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\d+) (?P<seconds>[\d.]+) '
    r'(?P<klass>\w+) (?P<cache>\S+) "')


def cpu_counters(text: str) -> dict[str, int]:
    """Суммарные такты процессора из первой строки /proc/stat."""
    names = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
    for line in text.splitlines():
        if line.startswith("cpu "):
            values = [int(value) for value in line.split()[1:len(names) + 1]]
            counters = dict(zip(names, values, strict=False))
            counters["total"] = sum(values)
            return counters
    return {}


def memory(text: str) -> dict[str, int]:
    """Память в байтах из /proc/meminfo."""
    wanted = {"MemTotal": "total", "MemAvailable": "available",
              "SwapTotal": "swapTotal", "SwapFree": "swapFree"}
    result: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name in wanted:
            result[wanted[name]] = int(rest.split()[0]) * 1024
    return result


def empty_traffic() -> dict[str, Any]:
    return {"requests": 0, "human": 0, "bots": 0, "bytes": 0,
            "status": {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0},
            "human5xx": 0, "bot503": 0, "pages": 0, "pageHits": 0}


def add_line(totals: dict[str, Any], latencies: list[float], line: str) -> None:
    match = LINE.match(line)
    if not match:
        return
    status, klass = int(match["status"]), match["klass"]
    request = match["request"].split(" ")
    path = request[1] if len(request) > 1 else ""
    bot = klass in BOT_CLASSES
    totals["requests"] += 1
    totals["bytes"] += int(match["bytes"])
    totals["bots" if bot else "human"] += 1
    group = f"{status // 100}xx"
    if group in totals["status"]:
        totals["status"][group] += 1
    if status >= 500 and not bot:
        totals["human5xx"] += 1
    if status == 503 and bot:
        totals["bot503"] += 1
    if path.startswith(("/_next/", "/api/")) or match["cache"] == "-":
        return
    # Страницы: доля попаданий в страничный кэш и время ответа людям.
    totals["pages"] += 1
    if match["cache"] in CACHE_HITS:
        totals["pageHits"] += 1
    if not bot and len(latencies) < LATENCY_SAMPLES:
        latencies.append(float(match["seconds"]))


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1)]


def read_traffic(path: Path, state: dict[str, Any], now: float) -> dict[str, Any] | None:
    """Прирост журнала доступа с прошлого снимка.

    Первый запуск только запоминает конец файла: старая история не нужна, а
    поворот журнала узнаётся по смене inode.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    position = state.get("log") or {}
    first = not position
    offset = position.get("offset", 0) if position.get("inode") == stat.st_ino else 0
    if offset > stat.st_size:
        offset = 0
    if first:
        offset = stat.st_size
    totals, latencies = empty_traffic(), []
    with path.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(LOG_CHUNK_BYTES)
    # Неполную последнюю строку оставляем на следующий проход.
    complete = data.rfind(b"\n") + 1
    for line in data[:complete].decode("utf-8", "replace").splitlines():
        add_line(totals, latencies, line)
    previous = position.get("at")
    state["log"] = {"inode": stat.st_ino, "offset": offset + complete, "at": now}
    if first or previous is None:
        return None
    totals["seconds"] = round(max(0.0, now - previous), 1)
    totals["p50"] = percentile(latencies, 0.5)
    totals["p95"] = percentile(latencies, 0.95)
    return totals


def unit_states(run: Any = subprocess.run) -> dict[str, Any]:
    """Состояние служб проекта и веб-сервера, перезапуски долгоживущих служб."""
    listing = run(["systemctl", "list-units", "--all", "--plain", "--no-legend",
                   "m-ranked-*", "nginx.service", "docker.service"],
                  capture_output=True, text=True, check=False, timeout=20)
    failed, active, total = [], 0, 0
    for line in listing.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[1] == "not-found":
            continue
        total += 1
        if parts[2] == "failed":
            failed.append(parts[0])
        elif parts[2] == "active":
            active += 1
    shown = run(["systemctl", "show", "-p", "Id,NRestarts", *LONG_RUNNING],
                capture_output=True, text=True, check=False, timeout=20)
    restarts: dict[str, int] = {}
    unit = None
    for line in shown.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "Id":
            unit = value
        elif key == "NRestarts" and unit and value.isdecimal():
            restarts[unit] = int(value)
    return {"failed": sorted(failed), "active": active, "total": total, "restarts": restarts}


def textfile_metrics(directory: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for path in directory.glob("*.prom"):
        try:
            text = path.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("#") or " " not in line:
                continue
            name, _, value = line.rpartition(" ")
            try:
                values[name] = float(value)
            except ValueError:
                pass
    return values


def pipeline(values: dict[str, float]) -> dict[str, float | None]:
    """Метрики конвейера: приём с Сервера 1, анализ, резервные копии."""
    def latest(prefix: str) -> float | None:
        found = [value for name, value in values.items()
                 if (name == prefix or name.startswith(prefix + "{")) and math.isfinite(value)]
        return max(found) if found else None

    def total(prefix: str) -> float | None:
        found = [value for name, value in values.items()
                 if (name == prefix or name.startswith(prefix + "{")) and math.isfinite(value)]
        return sum(found) if found else None

    return {
        "ingestAcceptedAt": latest("mranked_transfer_ingest_last_accepted_unixtime"),
        "ingestAccepted": total("mranked_transfer_ingest_accepted_total"),
        "analysisLag": latest("mranked_anomaly_queue_lag_seconds"),
        "analysisBacklog": latest("mranked_anomaly_due_backlog"),
        "analysisCompletedAt": latest("mranked_anomaly_last_completion_unixtime"),
        "analyses": total("mranked_anomaly_analyses_total"),
        "normsRunAt": latest("mranked_anomaly_norm_last_run_unixtime"),
        "tailRunAt": latest("mranked_anomaly_tail_last_run_unixtime"),
        "backupAt": latest("mranked_backup_last_success_unixtime"),
        "cacheRequests": total("mranked_api_cache_requests_total"),
    }


def directory_bytes(root: Path, run: Any = subprocess.run) -> int | None:
    """Занятое место дерева — как du: жёсткие ссылки один раз, по ссылкам не ходит.

    du на C в разы быстрее обхода из Python: страничный кэш nginx — сотни
    тысяч файлов, и обход в Python съедал полминуты процессора и весь лимит
    памяти службы. Недоступный подкаталог du пропускает с ненулевым кодом
    выхода, итог при этом печатает — его и берём: из-за обрыва счёта на таком
    каталоге панель раньше писала «размер не предоставлен сервером».
    """
    if not root.is_dir():
        return None
    try:
        result = run(["du", "-s", "-x", "--block-size=1", str(root)],
                     capture_output=True, text=True, check=False, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = result.stdout.split("\t", 1)[0].strip()
    return int(first) if first.isdecimal() else None


def size_paths(raw: str) -> dict[str, Path]:
    paths = {}
    for item in raw.split(","):
        name, _, path = item.partition("=")
        if name.strip() and path.strip():
            paths[name.strip()] = Path(path.strip())
    return paths


def build(state: dict[str, Any], now: float, *, proc: Path, log: Path, metrics: Path,
          disk: Path, sizes: dict[str, Path], run: Any = subprocess.run) -> dict[str, Any]:
    usage = shutil.disk_usage(disk)
    sample: dict[str, Any] = {
        "v": VERSION,
        "cpu": cpu_counters((proc / "stat").read_text()),
        "cores": os.cpu_count() or 1,
        "load": list((proc / "loadavg").read_text().split()[:3]),
        "memory": memory((proc / "meminfo").read_text()),
        "disk": {"total": usage.total, "free": usage.free},
        "units": unit_states(run),
        "traffic": read_traffic(log, state, now),
        "pipeline": pipeline(textfile_metrics(metrics)),
    }
    sample["load"] = [float(value) for value in sample["load"]]
    measured = state.get("sizesAt")
    if sizes and (measured is None or now - measured >= SIZE_INTERVAL_SECONDS):
        sample["sizes"] = {name: directory_bytes(path, run) for name, path in sizes.items()}
        state["sizesAt"] = now
    return sample


# Итоги сбора по аккаунтам, завершённым с прошлого снимка. Сначала — циклы
# последних двух часов по индексу (platform, started_at): цикл Rutube длинный.
# Их десятки, и результаты аккаунтов подтягиваются по уникальному индексу
# (collection_run_id, platform_account_id), а не просмотром всей таблицы.
COLLECTION = """
WITH runs AS MATERIALIZED (
  SELECT id, platform FROM ingest.collection_run
  WHERE platform IN ('telegram','vk','max','rutube')
    AND started_at >= to_timestamp(%(since)s) - interval '2 hours'
)
SELECT runs.platform::text AS platform,
  count(*) FILTER (WHERE result.status='succeeded') AS ok,
  count(*) FILTER (WHERE result.status IN ('failed','partial')) AS failed,
  count(*) FILTER (WHERE result.status NOT IN ('succeeded','failed','partial')) AS other,
  extract(epoch FROM max(result.completed_at) FILTER (WHERE result.status='succeeded')) AS last_ok
FROM runs
CROSS JOIN LATERAL (
  SELECT status, completed_at FROM ingest.collection_account_result
  WHERE collection_run_id=runs.id
    AND completed_at > to_timestamp(%(since)s) AND completed_at <= to_timestamp(%(until)s)
) result
GROUP BY runs.platform
"""


def collection(connection: Any, since: float, until: float) -> dict[str, dict[str, Any]]:
    rows = connection.execute(COLLECTION, {"since": since, "until": until}).fetchall()
    return {row[0]: {"ok": row[1], "failed": row[2], "other": row[3],
                     "lastOk": float(row[4]) if row[4] is not None else None} for row in rows}


def store(dsn: str, sample: dict[str, Any], state: dict[str, Any], now: float) -> None:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10) as connection:
        connection.execute("SET statement_timeout = '10s'")
        since = state.get("collectionAt") or now - 300
        sample["collection"] = collection(connection, since, now)
        connection.execute("INSERT INTO ops_and_admin.host_sample(sample) VALUES (%s::jsonb)",
                           (json.dumps(sample),))
        connection.execute(
            "DELETE FROM ops_and_admin.host_sample WHERE observed_at < now() - make_interval(days => %s)",
            (RETENTION_DAYS,))
    state["collectionAt"] = now


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # Роль обслуживания: ей выдана запись снимков, учётные данные уже на месте.
    dsn = os.environ.get("MAINTENANCE_DATABASE_URL", "")
    if not dsn.strip():
        logger.error("MAINTENANCE_DATABASE_URL is required")
        return 2
    state_dir = Path(os.environ.get("OPS_SAMPLE_STATE_DIR", "/var/lib/m-ranked/ops-sample"))
    state_path = state_dir / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    now = time.time()
    sample = build(
        state, now,
        proc=Path("/proc"),
        log=Path(os.environ.get("OPS_SAMPLE_ACCESS_LOG", "/var/log/nginx/m-ranked-access.log")),
        metrics=Path(os.environ.get("OPS_SAMPLE_METRICS_DIR", "/var/lib/node_exporter/textfile_collector")),
        disk=Path(os.environ.get("OPS_SAMPLE_DISK_PATH", "/")),
        sizes=size_paths(os.environ.get(
            "OPS_SAMPLE_SIZE_PATHS",
            "releases=/opt/m-ranked,state=/var/lib/m-ranked,pageCache=/var/cache/nginx")))
    try:
        store(dsn, sample, state, now)
    except Exception as error:  # noqa: BLE001 — снимок необязателен, причина в журнал
        logger.error("снимок не записан: %s", type(error).__name__)
        return 1
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    os.replace(temporary, state_path)
    logger.info("снимок записан: %.2f с", time.time() - now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
