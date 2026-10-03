#!/usr/bin/env python3
"""mranked-doctor — подробная диагностика Сервера 2 одним вызовом.

Только читает: состояние служб и таймеров с выдержками журнала, проверки
здоровья API и веба, диск и резервные копии, метрики конвейера, ошибки и
медленные ответы nginx, состояние базы и свежие ошибки в журналах служб.
Запускается на сервере от root (установлен как /usr/local/sbin/mranked-doctor);
оператор и агент вызывают его по SSH:

    ssh <сервер 2> mranked-doctor            # текст
    ssh <сервер 2> mranked-doctor --json     # для разбора программой
    ssh <сервер 2> mranked-doctor --section units,backups

Код выхода: 0 — проблем нет, 1 — есть проблемы (список в конце вывода).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT = "m-ranked-target-*"
ACCESS_LOG = Path(os.environ.get("DOCTOR_ACCESS_LOG", "/var/log/nginx/m-ranked-access.log"))
METRICS_DIR = Path(os.environ.get("DOCTOR_METRICS_DIR", "/var/lib/node_exporter/textfile_collector"))
BACKUP_DIR = Path(os.environ.get("DOCTOR_BACKUP_DIR", "/var/backups/m-ranked"))
DB_CONTAINER = os.environ.get("DOCTOR_DB_CONTAINER", "mranked-target-postgres-1")
API = os.environ.get("DOCTOR_API", "http://127.0.0.1:18080")
WEB = os.environ.get("DOCTOR_WEB", "http://127.0.0.1:3000")
LINE = re.compile(r'^\S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) (\d+) ([\d.]+) (\w+) (\S+)')


def sh(*command: str, timeout: int = 30) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def show(unit: str, *properties: str) -> dict[str, str]:
    output = sh("systemctl", "show", "-p", ",".join(properties), unit)
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def journal(unit: str, lines: int = 8, since: str | None = None, priority: str | None = None) -> list[str]:
    command = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "cat"]
    if since:
        command += ["--since", since]
    if priority:
        command += ["-p", priority]
    return [line[:300] for line in sh(*command).splitlines() if line.strip()]


def units() -> dict[str, Any]:
    rows = []
    for line in sh("systemctl", "list-units", "--all", "--plain", "--no-legend", PROJECT,
                   "nginx.service", "docker.service").splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[1] != "not-found":
            rows.append({"unit": parts[0], "active": parts[2], "sub": parts[3]})
    failed = []
    for row in rows:
        if row["active"] == "failed":
            info = show(row["unit"], "Result", "ExecMainStatus", "InactiveEnterTimestamp")
            failed.append({**row, **info, "log": journal(row["unit"], 10)})
    # Временные юниты systemd-run (кандидаты выкатки, предпросмотры) — не
    # службы сайта, но их «failed» шумит в systemctl и тревогах.
    transient = [line.split()[0] for line in sh("systemctl", "list-units", "--failed", "--plain",
                                                 "--no-legend", "m-ranked-*").splitlines()
                 if line.split() and not line.split()[0].startswith("m-ranked-target-")]
    restarts = {}
    for row in rows:
        if row["unit"].endswith(".service") and row["active"] == "active":
            count = show(row["unit"], "NRestarts").get("NRestarts", "0")
            if count.isdecimal() and int(count):
                restarts[row["unit"]] = int(count)
    return {"total": len(rows), "active": sum(row["active"] == "active" for row in rows),
            "failed": failed, "transientFailed": transient, "restarts": restarts}


def timers() -> list[dict[str, Any]]:
    result = []
    for line in sh("systemctl", "list-timers", "--all", "--plain", "--no-legend", PROJECT).splitlines():
        parts = line.split()
        if not parts:
            continue
        timer = next((part for part in parts if part.endswith(".timer")), None)
        service = next((part for part in parts if part.endswith(".service")), None)
        if not timer or not service:
            continue
        info = show(service, "Result", "ExecMainStatus", "ActiveState")
        result.append({"timer": timer, "service": service, "active": show(timer, "ActiveState").get("ActiveState"),
                       "lastResult": info.get("Result"), "lastExit": info.get("ExecMainStatus"),
                       "next": " ".join(parts[:4]) if parts[0] not in ("-", "n/a") else None})
    return result


def http(url: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 — только localhost
            body = response.read(4096)
            return {"status": response.status, "ms": round((time.monotonic() - started) * 1000),
                    "body": body.decode("utf-8", "replace")[:300]}
    except Exception as error:  # noqa: BLE001
        status = getattr(error, "code", None)
        return {"status": status, "ms": round((time.monotonic() - started) * 1000), "error": type(error).__name__}


def health() -> dict[str, Any]:
    return {"apiLive": http(f"{API}/api/v1/health/live"), "apiReady": http(f"{API}/api/v1/health/ready"),
            "freshness": http(f"{API}/api/v1/health/freshness"), "web": http(f"{WEB}/methodology")}


def metrics() -> dict[str, float]:
    values: dict[str, float] = {}
    for path in METRICS_DIR.glob("*.prom"):
        try:
            for line in path.read_text().splitlines():
                if line and not line.startswith("#") and " " in line:
                    name, _, value = line.rpartition(" ")
                    try:
                        values[name] = float(value)
                    except ValueError:
                        pass
        except OSError:
            continue
    return values


def pipeline(now: float) -> dict[str, Any]:
    values = metrics()

    def age(prefix: str) -> float | None:
        found = [value for name, value in values.items() if name.split("{")[0] == prefix]
        return round((now - max(found)) / 60, 1) if found else None

    lag = next((value for name, value in values.items() if name == "mranked_anomaly_queue_lag_seconds"), None)
    return {"ingestMinutesAgo": age("mranked_transfer_ingest_last_accepted_unixtime"),
            "analysisLagMinutes": round(lag / 60, 1) if lag is not None else None,
            "analysisBacklog": values.get("mranked_anomaly_due_backlog"),
            "backupHoursAgo": (round(a / 60, 1) if (a := age("mranked_backup_last_success_unixtime")) is not None else None),
            "normsHoursAgo": (round(a / 60, 1) if (a := age("mranked_anomaly_norm_last_run_unixtime")) is not None else None),
            "tailHoursAgo": (round(a / 60, 1) if (a := age("mranked_anomaly_tail_last_run_unixtime")) is not None else None)}


def storage() -> dict[str, Any]:
    usage = shutil.disk_usage("/")
    files = []
    for path in sorted(BACKUP_DIR.glob("mranked-*.dump"), reverse=True):
        stat = path.stat()
        files.append({"name": path.name, "gb": round(stat.st_size / 1e9, 2),
                      "hoursAgo": round((time.time() - stat.st_mtime) / 3600, 1),
                      "verified": path.with_suffix(".restore-verified.json").is_file()})
    partial = [path.name for path in BACKUP_DIR.glob("mranked-*.dump.partial")]
    env = {}
    try:
        for line in Path("/etc/m-ranked/dump-backup.env").read_text().splitlines():
            if "=" in line and not line.startswith("#") and "PASS" not in line.upper():
                key, _, value = line.partition("=")
                env[key] = value
    except OSError:
        pass
    peak, reserve = int(env.get("BACKUP_MAX_DUMP_BYTES", 7e9)), int(env.get("BACKUP_RESERVE_BYTES", 11e9))
    return {"diskFreeGb": round(usage.free / 1e9, 1), "diskTotalGb": round(usage.total / 1e9, 1),
            "backups": files, "partial": partial,
            "backupAdmission": {"needGb": round((peak + reserve) / 1e9, 1), "allowed": usage.free >= peak + reserve},
            "loadavg": os.getloadavg(), "memAvailableGb": round(_meminfo("MemAvailable") / 1e6, 2)}


def _meminfo(key: str) -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return 0


def traffic(hours: float = 1.0) -> dict[str, Any]:
    cutoff = time.time() - hours * 3600
    errors: Counter[str] = Counter()
    slow = []
    total = 0
    try:
        with ACCESS_LOG.open(errors="replace") as stream:
            for line in stream:
                match = LINE.match(line)
                if not match:
                    continue
                try:
                    at = time.mktime(time.strptime(match[1], "%d/%b/%Y:%H:%M:%S %z"))
                except ValueError:
                    continue
                if at < cutoff:
                    continue
                total += 1
                path = re.sub(r"/[0-9a-f-]{8,}|/\d+", "/:id", match[3].split("?")[0])
                if match[4].startswith("5"):
                    errors[f"{match[4]} {path}"] += 1
                if float(match[6]) >= 2:
                    slow.append(f"{float(match[6]):.1f}s {match[4]} {path}")
    except OSError:
        pass
    return {"requests": total, "errors5xx": errors.most_common(10), "slow": Counter(slow).most_common(10)}


def database() -> dict[str, Any]:
    user = sh("docker", "exec", DB_CONTAINER, "printenv", "POSTGRES_USER").strip()
    if not user:
        return {"error": "container unavailable"}
    query = (
        "SELECT json_build_object('sizeGb', round(pg_database_size(current_database())/1e9,2),"
        "'connections',(SELECT count(*) FROM pg_stat_activity),"
        "'active',(SELECT count(*) FROM pg_stat_activity WHERE state='active'),"
        "'longestSeconds',(SELECT coalesce(max(extract(epoch FROM now()-query_start)),0)::int FROM pg_stat_activity WHERE state='active' AND pid<>pg_backend_pid()),"
        "'waitingLocks',(SELECT count(*) FROM pg_locks WHERE NOT granted),"
        "'deadTuplesTop',(SELECT json_agg(t) FROM (SELECT schemaname||'.'||relname AS rel, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 3) t))")
    output = sh("docker", "exec", DB_CONTAINER, "psql", "-U", user, "-d", "mranked", "-XAt", "-c", query)
    try:
        return json.loads(output.strip())
    except ValueError:
        return {"error": output.strip()[:200]}


def recent_errors(since: str = "-1h") -> dict[str, list[str]]:
    result = {}
    for line in sh("systemctl", "list-units", "--all", "--plain", "--no-legend", "--type=service", PROJECT).splitlines():
        unit = line.split()[0] if line.split() else ""
        if not unit:
            continue
        lines = journal(unit, 5, since=since, priority="err")
        if lines:
            result[unit] = lines
    return result


SECTIONS = {"units": units, "timers": timers, "health": health, "pipeline": None, "storage": storage,
            "traffic": traffic, "database": database, "errors": recent_errors}


def problems(report: dict[str, Any]) -> list[str]:
    found = []
    for item in report.get("units", {}).get("failed", []):
        found.append(f"служба {item['unit']} упала (Result={item.get('Result')}, код {item.get('ExecMainStatus')})")
    for unit in report.get("units", {}).get("transientFailed", []):
        found.append(f"временный юнит {unit} в состоянии failed (systemctl reset-failed {unit})")
    for name, check in (report.get("health") or {}).items():
        if check.get("status") != 200:
            found.append(f"проверка {name}: {check.get('status') or check.get('error')}")
    pipe = report.get("pipeline") or {}
    if (pipe.get("ingestMinutesAgo") or 0) > 20:
        found.append(f"пакеты с Сервера 1 не приходят {pipe['ingestMinutesAgo']} мин")
    if (pipe.get("analysisLagMinutes") or 0) > 180:
        found.append(f"анализ отстаёт на {pipe['analysisLagMinutes']} мин")
    if pipe.get("backupHoursAgo") is None or pipe["backupHoursAgo"] > 36:
        found.append(f"резервной копии нет {pipe.get('backupHoursAgo')} ч")
    store = report.get("storage") or {}
    if store and store["diskFreeGb"] < 6:
        found.append(f"мало места: {store['diskFreeGb']} ГБ")
    if store and len(store.get("backups", [])) > 2:
        found.append(f"копий на диске {len(store['backups'])}, должно быть не больше двух")
    db = report.get("database") or {}
    if db.get("waitingLocks"):
        found.append(f"ожидающих блокировок в базе: {db['waitingLocks']}")
    for item, count in (report.get("traffic") or {}).get("errors5xx", []):
        if count >= 10:
            found.append(f"5xx за час: {item} ×{count}")
    return found


def text(report: dict[str, Any]) -> str:
    out = [f"mranked-doctor · {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"]
    for name, value in report.items():
        if name == "problems":
            continue
        out.append(f"\n== {name}")
        out.append(json.dumps(value, ensure_ascii=False, indent=1, default=str))
    out.append("\n== problems")
    out.extend(f"- {line}" for line in report["problems"]) if report["problems"] else out.append("нет")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--section", default=",".join(SECTIONS))
    args = parser.parse_args()
    wanted = [name.strip() for name in args.section.split(",") if name.strip() in SECTIONS]
    report: dict[str, Any] = {}
    for name in wanted:
        report[name] = pipeline(time.time()) if name == "pipeline" else SECTIONS[name]()  # type: ignore[misc]
    report["problems"] = problems(report)
    print(json.dumps(report, ensure_ascii=False, default=str) if args.json else text(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
