"""Локальное хранилище файлов узла: резервные копии и холодный архив.

Только стандартная библиотека: модуль работает и в агенте любого сервера, где
нет окружения проекта, и в службах Сервера 2.

    <root>/backups/   дампы базы (2770: root и группа хранилища, без остальных)
    <root>/archive/   полные и просмотровые файлы холодного архива (2775)
    <root>/incoming/  недокачанные копии <id>.partial (2770)

Группа хранилища пишет во все три каталога: приёмник переноса на основном
сервере работает не от root и кладёт сюда файлы, присланные агентами.

Файлы неизменяемы: копия появляется под окончательным именем только после
сверки SHA-256, а до того лежит в incoming.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any

DEFAULT_ROOT = Path("/var/lib/m-ranked/store")
# Кусок передачи. Приёмник на основном сервере живёт под потолком памяти
# (MemoryHigh 384 МБ): куски по 8 МБ с копиями ответа и брошенными по таймауту
# соединениями вывели его за потолок 04.10.2026, и встал перенос замеров.
CHUNK_BYTES = 1024 * 1024
KIND_DIRECTORY = {"backup": "backups", "archive_full": "archive", "archive_browse": "archive"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
OBJECT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def object_path(root: Path, kind: str, name: str) -> Path:
    if kind not in KIND_DIRECTORY or not NAME.fullmatch(name):
        raise ValueError("unsafe storage object name")
    return root / KIND_DIRECTORY[kind] / name


def incoming_path(root: Path, object_id: str) -> Path:
    if not OBJECT_ID.fullmatch(object_id):
        raise ValueError("object id must be a UUID")
    return root / "incoming" / f"{object_id}.partial"


def ensure_layout(root: Path, group: int | None = None) -> None:
    for directory, mode in (("backups", 0o2770), ("archive", 0o2775), ("incoming", 0o2770)):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        # Каталоги создаёт агент (root); остальные службы только пользуются
        # ими и менять чужие права не могут — и не должны.
        try:
            if group is not None and path.stat().st_gid != group:
                os.chown(path, -1, group)
            if path.stat().st_mode & 0o7777 != mode:
                os.chmod(path, mode)
        except PermissionError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish(partial: Path, final: Path, kind: str) -> None:
    """Перенести сверенную копию под окончательное имя."""
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
    os.chmod(partial, 0o640 if kind == "backup" else 0o644)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial, final)
    directory = os.open(final.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def inventory(root: Path) -> list[dict[str, Any]]:
    """Окончательные файлы хранилища: имя, вид каталога, размер."""
    items: list[dict[str, Any]] = []
    for directory in ("backups", "archive"):
        path = root / directory
        if not path.is_dir():
            continue
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False) and not entry.name.startswith("."):
                items.append({"name": entry.name, "directory": directory, "size": entry.stat().st_size})
    return sorted(items, key=lambda item: item["name"])


def store_bytes(root: Path) -> int:
    total = 0
    for directory in ("backups", "archive", "incoming"):
        path = root / directory
        if path.is_dir():
            total += sum(entry.stat().st_size for entry in os.scandir(path)
                         if entry.is_file(follow_symlinks=False))
    return total


def host_metrics(root: Path) -> dict[str, Any]:
    """Диск под хранилищем (или корень, если его ещё нет), память, нагрузка."""
    target = root if root.exists() else Path("/")
    usage = shutil.disk_usage(target)
    metrics: dict[str, Any] = {"diskTotalBytes": usage.total, "diskFreeBytes": usage.free,
                               "storeBytes": store_bytes(root) if root.exists() else 0}
    root_usage = shutil.disk_usage("/")
    metrics["rootTotalBytes"], metrics["rootFreeBytes"] = root_usage.total, root_usage.free
    try:
        values: dict[str, int] = {}
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0]) * 1024
        metrics["memoryTotalBytes"] = values.get("MemTotal")
        metrics["memoryAvailableBytes"] = values.get("MemAvailable")
    except OSError:
        pass
    try:
        metrics["load1"] = os.getloadavg()[0]
        metrics["cpus"] = os.cpu_count()
    except OSError:
        pass
    return metrics
