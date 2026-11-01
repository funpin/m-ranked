"""Ресурсы машины и процессы проекта: общий разбор для живого буфера API,
агента основного сервера и агентов других узлов.

Только стандартная библиотека: агент сборщика работает на системном Python.
Всё здесь — чтение маленьких файлов /proc и textfile-метрик и один вызов
systemctl show, без записи и без обращений к базе.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Виртуальные и петлевые интерфейсы трафика машины не несут.
VIRTUAL_NET = ("lo", "docker", "veth", "br-", "virbr", "wg", "tun", "tap")
# Целые диски, без разделов и псевдоустройств: иначе байты считаются дважды.
WHOLE_DISK = re.compile(r"^(?:[sv]d[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
SECTOR_BYTES = 512
PLATFORMS = ("telegram", "vk", "max", "rutube")
RELEASE = re.compile(r"v20\d{2}\.\d{1,2}\.\d{1,3}")
# Службы и таймеры проекта; кандидаты выкатки (systemd-run) сюда не попадают.
UNIT_PATTERNS = ("m-ranked-target-*",)
PROJECT_PREFIX = "m-ranked-target-"
SHOW_PROPERTIES = ("Id,ActiveState,SubState,Result,ActiveEnterTimestamp,ExecMainStartTimestamp,"
                   "ExecMainExitTimestamp,NRestarts,LastTriggerUSec,NextElapseUSecRealtime,Unit")
MAX_TASKS = 80


def cpu_counters(text: str) -> tuple[int, int] | None:
    """(всего тактов, простой) из первой строки /proc/stat; iowait — тоже простой."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            values = [int(value) for value in line.split()[1:9]]
            if len(values) < 5:
                return None
            return sum(values), values[3] + values[4]
    return None


def boot_at(text: str) -> float | None:
    """Время загрузки машины (btime из /proc/stat)."""
    for line in text.splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    return None


def memory(text: str) -> dict[str, int]:
    wanted = {"MemTotal": "total", "MemAvailable": "available", "SwapTotal": "swapTotal", "SwapFree": "swapFree"}
    result: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name in wanted and rest.split():
            result[wanted[name]] = int(rest.split()[0]) * 1024
    return result


def net_bytes(text: str) -> tuple[int, int]:
    """Суммарно принято и отправлено физическими интерфейсами."""
    received = sent = 0
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        fields = rest.split()
        if not name or name.startswith(VIRTUAL_NET) or len(fields) < 9:
            continue
        received += int(fields[0])
        sent += int(fields[8])
    return received, sent


def _whole_disk(name: str) -> bool:
    return WHOLE_DISK.match(name) is not None


def disk_bytes(text: str) -> tuple[int, int]:
    """Прочитано и записано целыми дисками, в байтах."""
    read = written = 0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10 or not _whole_disk(fields[2]):
            continue
        read += int(fields[5]) * SECTOR_BYTES
        written += int(fields[9]) * SECTOR_BYTES
    return read, written


def counters(proc: Path = Path("/proc"), clock: Any = None) -> dict[str, Any]:
    """Счётчики для разности между двумя чтениями; нечитаемое — None."""
    current: dict[str, Any] = {"at": (clock or time.time)()}
    for name, reader, key in (("stat", cpu_counters, "cpu"), ("self/net/dev", net_bytes, "net"),
                              ("diskstats", disk_bytes, "disk")):
        try:
            value = reader((proc / name).read_text())
            current[key] = list(value) if value is not None else None
        except (OSError, ValueError):
            current[key] = None
    return current


def rates(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, float | None]:
    """Загрузка CPU, %, и скорости сети и диска, байт/с, между двумя чтениями.
    Перезагрузка обнуляет счётчики — такую пару не считаем."""
    empty = {"cpuPercent": None, "netRxBytesPerSecond": None, "netTxBytesPerSecond": None,
             "diskReadBytesPerSecond": None, "diskWriteBytesPerSecond": None}
    if not previous or not isinstance(previous.get("at"), (int, float)):
        return empty
    seconds = current["at"] - previous["at"]
    if seconds <= 0:
        return empty

    def rate(key: str, index: int) -> float | None:
        before, after = previous.get(key), current.get(key)
        if not before or not after or after[index] < before[index]:
            return None
        return round((after[index] - before[index]) / seconds, 1)

    cpu = None
    if previous.get("cpu") and current.get("cpu"):
        total = current["cpu"][0] - previous["cpu"][0]
        idle = current["cpu"][1] - previous["cpu"][1]
        if total > 0 and idle >= 0:
            cpu = round(max(0.0, min(100.0, 100.0 * (1 - idle / total))), 1)
    return {"cpuPercent": cpu, "netRxBytesPerSecond": rate("net", 0), "netTxBytesPerSecond": rate("net", 1),
            "diskReadBytesPerSecond": rate("disk", 0), "diskWriteBytesPerSecond": rate("disk", 1)}


def release(current: Path = Path("/opt/m-ranked/current")) -> str | None:
    """Версия выпуска, на который указывает current: v2026.11.0."""
    try:
        found = RELEASE.search(os.readlink(current))
    except OSError:
        return None
    return found.group(0) if found else None


def _stamp(value: str) -> float | None:
    """Время systemctl show --timestamp=unix: «@1730000000»; пусто или 0 — нет."""
    value = value.strip()
    if value.startswith("@"):
        value = value[1:]
    try:
        moment = float(value)
    except ValueError:
        return None
    return moment if moment > 0 else None


def _short(unit: str) -> str:
    name = unit.removeprefix(PROJECT_PREFIX)
    for suffix in (".service", ".timer"):
        name = name.removesuffix(suffix)
    return name


def tasks(run: Any = subprocess.run, patterns: tuple[str, ...] = UNIT_PATTERNS) -> list[dict[str, Any]]:
    """Службы и задания по расписанию: состояние, с какого момента, перезапуски;
    у таймера — последний и следующий запуск и итог его службы.

    Два вызова systemctl на всё: список юнитов и свойства всех сразу."""
    try:
        listing = run(["systemctl", "list-units", "--all", "--plain", "--no-legend", *patterns],
                      capture_output=True, text=True, check=False, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] != "not-found" and parts[0].endswith((".service", ".timer")):
            names.append(parts[0])
    if not names:
        return []
    try:
        shown = run(["systemctl", "show", "--timestamp=unix", "-p", SHOW_PROPERTIES, *names[:MAX_TASKS * 2]],
                    capture_output=True, text=True, check=False, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    units: dict[str, dict[str, str]] = {}
    for block in shown.split("\n\n"):
        values = dict(line.partition("=")[::2] for line in block.splitlines() if "=" in line)
        if values.get("Id"):
            units[values["Id"]] = values
    triggered = {values.get("Unit") for unit, values in units.items() if unit.endswith(".timer")}
    result = []
    for unit, values in units.items():
        if unit.endswith(".service") and unit in triggered:
            continue  # покажется строкой своего таймера
        service = units.get(values.get("Unit", "")) if unit.endswith(".timer") else values
        service = service or {}
        restarts = service.get("NRestarts", "")
        entry = {
            "id": unit,
            "unit": _short(unit),
            "scheduled": unit.endswith(".timer"),
            "active": service.get("ActiveState") or values.get("ActiveState", ""),
            "sub": service.get("SubState") or values.get("SubState", ""),
            "result": service.get("Result") or None,
            "since": _stamp(service.get("ActiveEnterTimestamp", "")),
            "startedAt": _stamp(service.get("ExecMainStartTimestamp", "")),
            "exitedAt": _stamp(service.get("ExecMainExitTimestamp", "")),
            "restarts": int(restarts) if restarts.isdecimal() else None,
        }
        if entry["scheduled"]:
            entry["lastAt"] = _stamp(values.get("LastTriggerUSec", ""))
            entry["nextAt"] = _stamp(values.get("NextElapseUSecRealtime", ""))
            entry["timerActive"] = values.get("ActiveState", "")
        result.append(entry)
    result.sort(key=lambda item: (item["scheduled"], item["unit"]))
    return result[:MAX_TASKS]


def textfile(directory: Path, prefixes: tuple[str, ...]) -> dict[str, float]:
    """Значения textfile-метрик с заданными префиксами имени."""
    values: dict[str, float] = {}
    try:
        paths = sorted(directory.glob("*.prom"))
    except OSError:
        return values
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.startswith(prefixes):
                continue
            name, _, value = line.rpartition(" ")
            try:
                number = float(value)
            except ValueError:
                continue
            if math.isfinite(number):
                values[name] = number
    return values


LABEL = re.compile(r'(\w+)="([^"]*)"')
COLLECTOR_PREFIXES = ("mranked_collector_last_success_unixtime", "mranked_collector_cycle_duration_seconds",
                      "mranked_collector_schedule_lag_seconds", "mranked_collector_shutdowns_total",
                      "mranked_collector_provider_errors_total", "mranked_transfer_sender_")


def collector_processes(values: dict[str, float]) -> dict[str, Any]:
    """Сборщики по площадкам и отправитель переноса из textfile-метрик."""
    fields = {"mranked_collector_last_success_unixtime": "lastSuccessAt",
              "mranked_collector_cycle_duration_seconds": "cycleSeconds",
              "mranked_collector_schedule_lag_seconds": "scheduleLagSeconds"}
    sums = {"mranked_collector_shutdowns_total": "shutdowns", "mranked_collector_provider_errors_total": "providerErrors"}
    platforms: dict[str, dict[str, float]] = {}
    transfer: dict[str, float] = {}
    for name, value in values.items():
        base, _, labels = name.partition("{")
        platform = dict(LABEL.findall(labels)).get("platform")
        if base in fields and platform in PLATFORMS:
            platforms.setdefault(platform, {})[fields[base]] = value
        elif base in sums and platform in PLATFORMS:
            entry = platforms.setdefault(platform, {})
            entry[sums[base]] = entry.get(sums[base], 0) + value
        elif base in ("mranked_transfer_sender_backlog", "mranked_transfer_sender_delivered_total",
                      "mranked_transfer_sender_failures_total"):
            transfer[{"mranked_transfer_sender_backlog": "backlog", "mranked_transfer_sender_delivered_total": "delivered",
                      "mranked_transfer_sender_failures_total": "failures"}[base]] = value
    return {"collectors": platforms, "transfer": transfer or None}
