"""Файл просмотра холодного архива: готовая выдача истории каждого поста месяца.

Полный архив месяца (Parquet v3, parquet.py) хранит каждую строку замера с
каноническим отпечатком и нужен для восстановления. Открывать из него один пост
долго: строки упорядочены по номеру замера, и пришлось бы читать весь месяц.
Поэтому рядом с ним пишется файл просмотра — SQLite с одной строкой на пост:
выдача истории (те же элементы api.dto.history_snapshot, что отдаёт API, от
новых к старым) и покрытие сборщика на момент архивации, каждое сжато xz.
Поиск идёт по первичному ключу и занимает миллисекунды, а модуль sqlite3 есть в
стандартной библиотеке — API читает файл без новых зависимостей.

Файл неизменяем: пишется во временный путь, проверяется, получает SHA-256 и
только потом переименовывается на место.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import lzma
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

FORMAT = "mranked-browse"
FORMAT_VERSION = 1
# xz с пресетом 6: выдача из сотен одинаково устроенных элементов сжимается в
# десятки раз, а распаковка одного поста — доли миллисекунды на тысячу точек.
XZ_PRESET = 6

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE publication (
    publication_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    items_count INTEGER NOT NULL,
    snapshot_count INTEGER NOT NULL,
    max_snapshot_id INTEGER NOT NULL,
    items BLOB NOT NULL,
    coverage BLOB
) WITHOUT ROWID;
"""


@dataclass(frozen=True, slots=True)
class BrowseRecord:
    publication_id: str
    account_id: str
    published_at: datetime
    items: list[dict[str, Any]]
    coverage: dict[str, Any] | None
    snapshot_count: int
    max_snapshot_id: int


@dataclass(frozen=True, slots=True)
class BrowseSummary:
    path: Path
    sha256: str
    size_bytes: int
    publications: int
    snapshots: int


def _pack(value: Any) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    return lzma.compress(raw, preset=XZ_PRESET)


def _unpack(value: bytes) -> Any:
    return json.loads(lzma.decompress(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path: Path, month: str, records: Iterable[BrowseRecord]) -> BrowseSummary:
    """Записать файл месяца атомарно. Существующий файл не перезаписывается."""
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    publications = snapshots = 0
    try:
        connection.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=16384;" + SCHEMA)
        for record in records:
            connection.execute(
                "INSERT INTO publication VALUES (?,?,?,?,?,?,?,?)",
                (record.publication_id, record.account_id, record.published_at.isoformat(),
                 len(record.items), record.snapshot_count, record.max_snapshot_id,
                 _pack(record.items), _pack(record.coverage) if record.coverage is not None else None))
            publications += 1
            snapshots += record.snapshot_count
        connection.executemany("INSERT INTO meta VALUES (?,?)", [
            ("format", FORMAT), ("version", str(FORMAT_VERSION)), ("month", month),
            ("publications", str(publications)), ("snapshots", str(snapshots)),
        ])
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    verify(temporary, month)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return BrowseSummary(path, sha256_file(path), path.stat().st_size, publications, snapshots)


def _open(path: Path) -> sqlite3.Connection:
    # immutable=1: файл архива не меняется, SQLite не берёт блокировок и не
    # ищет журнал — чтение работает и с файловой системы только для чтения.
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)


def verify(path: Path, month: str) -> tuple[int, int]:
    """Проверить формат, месяц, счётчики и распаковку каждого поста."""
    connection = _open(path)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("browse archive integrity check failed")
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        if meta.get("format") != FORMAT or meta.get("version") != str(FORMAT_VERSION) or meta.get("month") != month:
            raise ValueError("browse archive metadata mismatch")
        publications = snapshots = 0
        for items_count, snapshot_count, items, coverage in connection.execute(
                "SELECT items_count, snapshot_count, items, coverage FROM publication"):
            if len(_unpack(items)) != items_count:
                raise ValueError("browse archive item count mismatch")
            if coverage is not None:
                _unpack(coverage)
            publications += 1
            snapshots += snapshot_count
        if (str(publications), str(snapshots)) != (meta.get("publications"), meta.get("snapshots")):
            raise ValueError("browse archive totals mismatch")
        return publications, snapshots
    finally:
        connection.close()


class BrowseReader:
    """Чтение одного поста; соединения к файлам держатся открытыми."""

    def __init__(self) -> None:
        self._connections: dict[Path, sqlite3.Connection] = {}
        # Одно соединение на файл делят потоки API: чтение идёт под замком.
        self._lock = threading.Lock()

    def _connection(self, path: Path) -> sqlite3.Connection:
        connection = self._connections.get(path)
        if connection is None:
            connection = self._connections[path] = _open(path)
        return connection

    def read(self, path: Path, publication_id: str) -> BrowseRecord | None:
        with self._lock:
            row = self._connection(path).execute(
                "SELECT publication_id, account_id, published_at, snapshot_count, max_snapshot_id, items, coverage "
                "FROM publication WHERE publication_id=?", (publication_id,)).fetchone()
        if row is None:
            return None
        return BrowseRecord(row[0], row[1], datetime.fromisoformat(row[2]), _unpack(row[5]),
                            _unpack(row[6]) if row[6] is not None else None, row[3], row[4])

    def iterate(self, path: Path, account_ids: set[str] | None = None) -> Iterator[BrowseRecord]:
        for row in _open(path).execute(
                "SELECT publication_id, account_id, published_at, snapshot_count, max_snapshot_id, items, coverage "
                "FROM publication ORDER BY publication_id"):
            if account_ids is None or row[1] in account_ids:
                yield BrowseRecord(row[0], row[1], datetime.fromisoformat(row[2]), _unpack(row[5]),
                                   _unpack(row[6]) if row[6] is not None else None, row[3], row[4])

    def forget(self, path: Path) -> None:
        connection = self._connections.pop(path, None)
        if connection is not None:
            connection.close()
