"""Снимок состояния Сервера 2 для панели управления.

Раз в минуту таймер собирает то, что уже лежит на машине: счётчики
процессора и памяти из /proc, состояние служб systemd, прирост журнала nginx
с прошлого снимка и метрики конвейера, которые службы и так пишут для
node_exporter. Снимок — одна строка JSON в ops_and_admin.host_sample; панель
читает готовые строки и ничего не считает на запрос.

После записи снимка собирается alert-inputs.json для alerts.py (у него нет
доступа к базе): сбор по площадкам, p95 страниц и ресурсы узлов. Ошибка этой
части снимок не ломает.

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
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("ops-sample")

VERSION = 1
RETENTION_DAYS = 30
SIZE_INTERVAL_SECONDS = 6 * 3600
BOT_CLASSES = frozenset({"ai_user", "ai_search", "ai_training", "seo", "crawler"})
CACHE_HITS = frozenset({"HIT", "STALE", "UPDATING", "REVALIDATED"})
# Не страницы: служебные файлы и картинки реакций (тот же список, что у
# шлюза в operations/nginx/traffic.conf). Отказ картинки Telegram ждёт 10 с —
# считай мы её страницей, график скорости показывал бы его, а не страницы.
NOT_PAGES = ("/_next/", "/api/", "/emoji/", "/icons/", "/splash/", "/apple-touch-icon",
             "/favicon", "/manifest.webmanifest", "/robots.txt", "/sitemap")
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
    if path.startswith(NOT_PAGES) or match["cache"] == "-":
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
    # Только службы проекта (m-ranked-target-*): временные кандидаты выкатки
    # (systemd-run) не службы сайта и не должны краснить панель.
    listing = run(["systemctl", "list-units", "--all", "--plain", "--no-legend",
                   "m-ranked-target-*", "nginx.service", "docker.service"],
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
        # Когда Сервер 1 запечатал последнюю принятую пачку: разница с приёмом —
        # отставание очереди.
        "ingestBatchCreatedAt": latest("mranked_transfer_ingest_last_batch_created_unixtime"),
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


def backups(directory: Path, request: Path, run: Any = subprocess.run) -> dict[str, Any] | None:
    """Резервные копии для панели: файлы, проверка восстановлением, идёт ли
    дамп сейчас, ждёт ли запрос из панели и чем кончился последний запуск."""
    if not directory.is_dir():
        return None
    files = []
    for path in sorted(directory.glob("mranked-*.dump"), reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append({"name": path.name, "bytes": stat.st_size, "at": stat.st_mtime,
                      "verified": path.with_suffix(".restore-verified.json").is_file()})
    partial = next(iter(directory.glob("mranked-*.dump.partial")), None)
    shown = run(["systemctl", "show", "-p", "ActiveState,Result,ExecMainStatus,InactiveEnterTimestampMonotonic",
                 "m-ranked-target-dump-backup.service"], capture_output=True, text=True, check=False, timeout=20)
    state = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
    return {
        "files": files[:10],
        "running": state.get("ActiveState") in ("activating", "active", "deactivating"),
        "partialBytes": partial.stat().st_size if partial is not None and partial.exists() else None,
        "requested": request.exists(),
        "lastResult": state.get("Result"),
        "lastExitStatus": int(state["ExecMainStatus"]) if state.get("ExecMainStatus", "").isdecimal() else None,
    }


def size_paths(raw: str) -> dict[str, Path]:
    paths = {}
    for item in raw.split(","):
        name, _, path = item.partition("=")
        if name.strip() and path.strip():
            paths[name.strip()] = Path(path.strip())
    return paths


def build(state: dict[str, Any], now: float, *, proc: Path, log: Path, metrics: Path,
          disk: Path, sizes: dict[str, Path], run: Any = subprocess.run,
          backup_dir: Path | None = None, backup_request: Path = Path("/nonexistent")) -> dict[str, Any]:
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
        "backups": backups(backup_dir, backup_request, run) if backup_dir else None,
    }
    sample["load"] = [float(value) for value in sample["load"]]
    measured = state.get("sizesAt")
    if sizes and (measured is None or now - measured >= SIZE_INTERVAL_SECONDS):
        sample["sizes"] = {name: directory_bytes(path, run) for name, path in sizes.items()}
        state["sizesAt"] = now
    return sample


# Итоги сбора по аккаунтам, пришедшим с прошлого снимка. Окно каждой площадки
# начинается с самого позднего завершения, которое прошлые снимки уже видели
# (отметка в state), а не с часов: результаты приходят с Сервера 1 очередью, и
# 18.10.2026 при отставании приёма на 20+ минут строки доезжали с уже
# прошедшим completed_at — окно «с прошлого снимка по часам» их не видело, и
# админка с тревогами решили, что сбор стоит 1,7 ч. Очередь доставляет
# результаты по порядку, поэтому новые строки всегда позже отметки.
# last_result — время последнего результата любого исхода: когда MAX отзывает
# вход, сборщик не пишет результатов вовсе, и по нему «вход отозван» отличается
# от «сбор падает». Сначала — циклы последних часов по индексу (platform,
# started_at): цикл Rutube длинный. Их десятки, и результаты аккаунтов
# подтягиваются по уникальному индексу (collection_run_id,
# platform_account_id), а не просмотром всей таблицы.
COLLECTION_PLATFORMS = ("telegram", "vk", "max", "rutube")
# Отметка не уходит назад дальше окна тревог: иначе после долгого простоя
# площадки запрос тянул бы циклы за сутки.
MARK_MAX_LAG_SECONDS = 3 * 3600
COLLECTION = """
WITH since(platform, ts) AS (
  VALUES ('telegram', %(telegram)s::float8), ('vk', %(vk)s::float8),
         ('max', %(max)s::float8), ('rutube', %(rutube)s::float8)
), runs AS MATERIALIZED (
  SELECT run.id, run.platform, since.ts
  FROM ingest.collection_run run
  JOIN since ON since.platform = run.platform::text
  WHERE run.platform IN ('telegram','vk','max','rutube')
    AND run.started_at >= to_timestamp(%(oldest)s) - interval '2 hours'
)
SELECT runs.platform::text AS platform,
  count(*) FILTER (WHERE result.status='succeeded') AS ok,
  count(*) FILTER (WHERE result.status IN ('failed','partial')) AS failed,
  count(*) FILTER (WHERE result.status NOT IN ('succeeded','failed','partial')) AS other,
  extract(epoch FROM max(result.completed_at) FILTER (WHERE result.status='succeeded')) AS last_ok,
  extract(epoch FROM max(result.completed_at)) AS last_result
FROM runs
CROSS JOIN LATERAL (
  SELECT status, completed_at FROM ingest.collection_account_result
  WHERE collection_run_id=runs.id
    AND completed_at > to_timestamp(runs.ts) AND completed_at <= to_timestamp(%(until)s)
) result
GROUP BY runs.platform
"""


def collection(connection: Any, since: dict[str, float], until: float) -> dict[str, dict[str, Any]]:
    """Итоги по площадкам за окна (since[площадка], until]."""
    params: dict[str, float] = {name: float(since[name]) for name in COLLECTION_PLATFORMS}
    params["oldest"] = min(params.values())
    params["until"] = until
    rows = connection.execute(COLLECTION, params).fetchall()
    return {row[0]: {"ok": row[1], "failed": row[2], "other": row[3],
                     "lastOk": float(row[4]) if row[4] is not None else None,
                     "lastResult": float(row[5]) if row[5] is not None else None} for row in rows}


def collection_marks(state: dict[str, Any], now: float) -> dict[str, float]:
    """Начало окна каждой площадки: последнее виденное завершение, но не
    старше MARK_MAX_LAG_SECONDS. Старый state без отметок — от прошлого снимка."""
    marks = state.get("collectionMarks") or {}
    fallback = state.get("collectionAt") or now - 300
    floor = now - MARK_MAX_LAG_SECONDS
    return {name: max(float(marks.get(name, fallback)), floor) for name in COLLECTION_PLATFORMS}


def advance_marks(since: dict[str, float], found: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Новые отметки: самое позднее завершение в окне; нет строк — отметка стоит."""
    marks = dict(since)
    for name, entry in found.items():
        newest = entry.get("lastResult")
        if name in marks and newest is not None:
            marks[name] = max(marks[name], float(newest))
    return marks


# Входные данные для тревог (operations/scripts/alerts.py, у него нет доступа к
# базе). Все три запроса идут по первичному ключу: host_sample — по
# observed_at, server_node_sample — по (node_id, observed_at).
ALERT_INPUTS_FILE = "alert-inputs.json"
HOURS_BACK = 3
BASELINE_WEEKS = 4
P95_ROWS = 15
# Последние три часа: итоги часа, последние успех и результат, p95 страниц.
RECENT_SAMPLES = """
SELECT sample->'collection', sample->'traffic'->>'p95', extract(epoch FROM observed_at)
FROM ops_and_admin.host_sample
WHERE observed_at >= to_timestamp(%(now)s) - make_interval(hours => %(hours)s)
ORDER BY observed_at DESC
"""
# Тот же час 1–4 недели назад: по одному диапазону ключа на неделю.
WEEKLY_SAMPLES = """
SELECT weeks.w, week_rows.collection
FROM generate_series(1, %(weeks)s) AS weeks(w)
CROSS JOIN LATERAL (
  SELECT sample->'collection' AS collection
  FROM ops_and_admin.host_sample
  WHERE observed_at >= to_timestamp(%(now)s::float8 - weeks.w * 604800 - 3600)
    AND observed_at < to_timestamp(%(now)s::float8 - weeks.w * 604800)
) week_rows
"""
# Последний снимок каждого работающего узла, кроме Сервера 2 (он меряет себя сам),
# и среднее load1 за 15 минут до него: один снимок даёт дребезг тревоги нагрузки.
# Оба чтения — диапазон по ключу (node_id, observed_at). Выключенные и ещё не
# принятые узлы снимков не шлют: без фильтра по state они вечно «молчали» бы.
NODE_SAMPLES = """
SELECT node.id, node.display_name, node.report->'metrics'->>'cpus',
  extract(epoch FROM sample.observed_at), sample.disk_total_bytes, sample.disk_free_bytes,
  sample.memory_total_bytes, sample.memory_available_bytes, load.mean
FROM ops_and_admin.server_node node
CROSS JOIN LATERAL (
  SELECT observed_at, disk_total_bytes, disk_free_bytes, memory_total_bytes, memory_available_bytes
  FROM ops_and_admin.server_node_sample
  WHERE node_id = node.id
  ORDER BY observed_at DESC
  LIMIT 1
) sample
CROSS JOIN LATERAL (
  SELECT avg(recent.load1) AS mean
  FROM ops_and_admin.server_node_sample recent
  WHERE recent.node_id = node.id
    AND recent.observed_at > sample.observed_at - interval '15 minutes'
    AND recent.observed_at <= sample.observed_at
) load
WHERE node.role <> 'main' AND node.state IN ('active', 'draining')
"""


def summarize_collection(hour_rows: list[dict | None], window_rows: list[dict | None],
                         baseline_hours: list[list[dict | None]]) -> dict[str, dict[str, Any]]:
    """Сбор по площадкам для тревог.

    hour_rows — значения sample->'collection' за последние 60 минут, window_rows
    — за 3 часа, baseline_hours — по списку на каждую из 1–4 недель назад (тот
    же час). Неделя без строк не считается: тогда снимков не было вовсе.
    """
    platforms: set[str] = set()
    for rows in (hour_rows, window_rows, *baseline_hours):
        for item in rows:
            platforms.update(item or {})
    weeks = [rows for rows in baseline_hours if rows]
    result: dict[str, dict[str, Any]] = {}
    for platform in sorted(platforms):
        hour = [item[platform] for item in hour_rows if item and platform in item]
        window = [item[platform] for item in window_rows if item and platform in item]
        ok = sum(entry.get("ok", 0) for entry in hour)
        failed = sum(entry.get("failed", 0) for entry in hour)
        other = sum(entry.get("other", 0) for entry in hour)
        last_ok = [entry["lastOk"] for entry in window if entry.get("lastOk") is not None]
        # Строки старого формата без lastResult: любой успех — тоже результат.
        last_result = [entry.get("lastResult") if entry.get("lastResult") is not None else entry.get("lastOk")
                       for entry in window]
        last_result = [value for value in last_result if value is not None]
        weekly = [sum(item[platform].get("ok", 0) for item in rows if item and platform in item) for rows in weeks]
        result[platform] = {
            "hourOk": ok, "hourFailed": failed, "hourResults": ok + failed + other,
            "baselineOk": float(statistics.median(weekly)) if weekly else None,
            "lastOk": max(last_ok) if last_ok else None,
            "lastResult": max(last_result) if last_result else None,
        }
    return result


def page_p95_median(values: list[float | None]) -> float | None:
    """Медиана p95 страниц; снимки без трафика (null) пропускаются."""
    found = [value for value in values if value is not None]
    return float(statistics.median(found)) if found else None


def node_inputs(rows: list[tuple]) -> dict[str, dict[str, Any]]:
    """Последние ресурсы узлов: id -> имя, время снимка, диск, память, среднее
    load1 за 15 минут, ядра."""
    nodes: dict[str, dict[str, Any]] = {}
    for node_id, name, cpus, observed, disk_total, disk_free, memory_total, memory_available, load_mean in rows:
        if observed is None:
            continue
        nodes[node_id] = {
            "name": name, "observedAt": float(observed), "diskTotal": disk_total, "diskFree": disk_free,
            "memoryTotal": memory_total, "memoryAvailable": memory_available,
            "load1Mean15m": float(load_mean) if load_mean is not None else None,
            "cpus": int(cpus) if cpus is not None and cpus.isdecimal() else None}
    return nodes


def write_alert_inputs(path: Path, inputs: dict[str, Any]) -> None:
    """Записать файл атомарно. Служба работает с UMask=0077, а читает его
    alerts.py другим процессом, поэтому права выставляются явно."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(inputs, stream)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def refresh_alert_inputs(connection: Any, now: float, path: Path) -> bool:
    """Собрать входные данные тревог и записать файл. Ошибка только в журнал:
    снимок уже сохранён, а тревоги заметят устаревший файл сами."""
    try:
        recent = connection.execute(RECENT_SAMPLES, {"now": now, "hours": HOURS_BACK}).fetchall()
        weekly = connection.execute(WEEKLY_SAMPLES, {"now": now, "weeks": BASELINE_WEEKS}).fetchall()
        nodes = connection.execute(NODE_SAMPLES).fetchall()
        # Строки пришли от новых к старым: p95 берётся с первых 15.
        window_rows = [row[0] for row in recent]
        hour_rows = [row[0] for row in recent if row[2] >= now - 3600]
        baseline: list[list[dict | None]] = [[] for _ in range(BASELINE_WEEKS)]
        for week, collected in weekly:
            baseline[week - 1].append(collected)
        p95 = [float(row[1]) if row[1] is not None else None for row in recent[:P95_ROWS]]
        write_alert_inputs(path, {
            "at": now,
            "collection": summarize_collection(hour_rows, window_rows, baseline),
            "pageP95Median15m": page_p95_median(p95),
            "nodes": node_inputs(nodes)})
    except Exception as error:  # noqa: BLE001 — тревоги необязательны, причина в журнал
        logger.warning("входные данные тревог не записаны: %s", type(error).__name__)
        return False
    return True


def store(dsn: str, sample: dict[str, Any], state: dict[str, Any], now: float,
          inputs_path: Path | None = None) -> None:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10) as connection:
        connection.execute("SET statement_timeout = '10s'")
        since = collection_marks(state, now)
        sample["collection"] = collection(connection, since, now)
        connection.execute("INSERT INTO ops_and_admin.host_sample(sample) VALUES (%s::jsonb)",
                           (json.dumps(sample),))
        connection.execute(
            "DELETE FROM ops_and_admin.host_sample WHERE observed_at < now() - make_interval(days => %s)",
            (RETENTION_DAYS,))
        if inputs_path is not None:
            # Снимок фиксируем до новых запросов: их сбой не должен его откатить.
            connection.commit()
            refresh_alert_inputs(connection, now, inputs_path)
    state["collectionAt"] = now
    state["collectionMarks"] = advance_marks(since, sample["collection"])


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
            "releases=/opt/m-ranked,state=/var/lib/m-ranked,pageCache=/var/cache/nginx")),
        backup_dir=Path(os.environ.get("OPS_SAMPLE_BACKUP_DIR", "/var/backups/m-ranked")),
        backup_request=Path("/var/lib/m-ranked/backup-request/refresh"))
    try:
        store(dsn, sample, state, now, state_dir / ALERT_INPUTS_FILE)
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
