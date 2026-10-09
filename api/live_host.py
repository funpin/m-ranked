"""Живой мониторинг Сервера 2: снимок /proc раз в несколько секунд в памяти API.

Минутные снимки ops-sample (миграция 0052) остаются историей за сутки и
неделю, а для «прямо сейчас» и масштабов 1 и 3 часа их мало. Чаще запускать
таймер дорого: каждый запуск — новый процесс Python, вызовы systemctl и строка
в базе. Здесь же процесс API уже жив, и шаг — чтение пяти маленьких файлов
/proc (десятки микросекунд), без записи куда-либо.

Точки лежат в кольцевом буфере: три часа по пять секунд — 2 160 точек, около
300 КБ. Перезапуск API буфер обнуляет; панель тогда достраивает часы по
минутным снимкам из базы. При нескольких воркерах каждый ведёт свой буфер:
читают они одни и те же счётчики машины, так что ответы совпадают с
точностью до момента снимка.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Виртуальные и петлевые интерфейсы трафика машины не несут.
VIRTUAL_NET = ("lo", "docker", "veth", "br-", "virbr", "wg", "tun", "tap")
# Целые диски, без разделов и псевдоустройств: иначе байты считаются дважды.
WHOLE_DISK = re.compile(r"^(?:[sv]d[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
SECTOR_BYTES = 512


def cpu_counters(text: str) -> tuple[int, int] | None:
    """(всего тактов, простой) из первой строки /proc/stat; iowait — тоже простой."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            values = [int(value) for value in line.split()[1:9]]
            if len(values) < 5:
                return None
            return sum(values), values[3] + values[4]
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


class HostMonitor:
    """Кольцевой буфер точек: загрузка CPU и RAM, load average, сеть и диск.

    Скорости и проценты считаются по разности соседних чтений, поэтому первая
    точка появляется через один шаг после старта.
    """

    def __init__(self, *, interval: float = 5.0, horizon: float = 3 * 3600, proc: Path = Path("/proc"),
                 disk: Path = Path("/"), clock: Any = time.time) -> None:
        self.interval = interval
        self.points: deque[dict[str, Any]] = deque(maxlen=max(1, int(horizon // interval)))
        self._proc, self._disk, self._clock = proc, disk, clock
        self._previous: dict[str, Any] | None = None
        self._task: asyncio.Task[None] | None = None
        self.cores = os.cpu_count() or 1
        self.memory_total: int | None = None
        self.disk_total: int | None = None
        self.disk_free: int | None = None

    def _read(self, name: str) -> str:
        return (self._proc / name).read_text()

    def sample(self) -> dict[str, Any] | None:
        """Одно чтение /proc; возвращает точку, если есть с чем сравнить."""
        now = self._clock()
        current: dict[str, Any] = {"at": now}
        try:
            current["cpu"] = cpu_counters(self._read("stat"))
            mem = memory(self._read("meminfo"))
            load = [float(value) for value in self._read("loadavg").split()[:3]]
        except (OSError, ValueError):
            return None
        for name, reader, key in (("self/net/dev", net_bytes, "net"), ("diskstats", disk_bytes, "disk")):
            try:
                current[key] = reader(self._read(name))
            except (OSError, ValueError):
                current[key] = None
        try:
            usage = shutil.disk_usage(self._disk)
            self.disk_total, self.disk_free = usage.total, usage.free
        except OSError:
            pass
        self.memory_total = mem.get("total")
        previous, self._previous = self._previous, current
        if previous is None:
            return None
        seconds = now - previous["at"]
        if seconds <= 0:
            return None

        def rate(key: str, index: int) -> float | None:
            before, after = previous.get(key), current.get(key)
            if before is None or after is None or after[index] < before[index]:
                return None
            return round((after[index] - before[index]) / seconds, 1)

        cpu = None
        if previous["cpu"] and current["cpu"]:
            total = current["cpu"][0] - previous["cpu"][0]
            idle = current["cpu"][1] - previous["cpu"][1]
            if total > 0 and idle >= 0:
                cpu = round(max(0.0, min(100.0, 100.0 * (1 - idle / total))), 1)
        total_memory, available = mem.get("total"), mem.get("available")
        swap_total, swap_free = mem.get("swapTotal"), mem.get("swapFree")
        point = {
            "at": round(now, 3),
            "cpu": cpu,
            "memory": round(100.0 * (total_memory - available) / total_memory, 1)
            if total_memory and available is not None else None,
            "memoryUsedBytes": total_memory - available if total_memory and available is not None else None,
            "swapUsedBytes": swap_total - swap_free if swap_total is not None and swap_free is not None else None,
            "load": load[0] if load else None,
            "netRxBytesPerSecond": rate("net", 0),
            "netTxBytesPerSecond": rate("net", 1),
            "diskReadBytesPerSecond": rate("disk", 0),
            "diskWriteBytesPerSecond": rate("disk", 1),
        }
        self.points.append(point)
        return point

    def since(self, moment: float | None) -> list[dict[str, Any]]:
        if moment is None:
            return list(self.points)
        return [point for point in self.points if point["at"] > moment]

    async def _run(self) -> None:
        while True:
            try:
                self.sample()
            except Exception:  # noqa: BLE001 — мониторинг не должен ронять API
                logger.exception("живой снимок сервера не снят")
            await asyncio.sleep(self.interval)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="host-monitor")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
