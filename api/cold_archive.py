"""Чтение истории поста из холодного архива (ADR-016).

Замеры месяца, ушедшего в архив, лежат в файлах просмотра его поколений
(operations/cold_archive/browse.py) на основном сервере: готовая выдача
истории каждого поста, поиск по ключу — миллисекунды. Поздние замеры, пришедшие
после удаления партиции, остаются в базе до следующего поколения; выдача
сливает всё вместе, от новых к старым.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
import time
from typing import Any

from operations.cold_archive.browse import BrowseReader
from operations.storage import store

GENERATIONS = """
SELECT generation.generation, object.name
  FROM ops_and_admin.cold_archive_generation generation
  JOIN ops_and_admin.storage_object object ON object.id = generation.browse_object_id
 WHERE generation.published_month = %(month)s AND generation.state = 'cold'
 ORDER BY generation.generation
"""
CACHE_SECONDS = 60.0
DELTAS = (("views", "deltaViews"), ("reactions", "deltaReactions"),
          ("comments", "deltaComments"), ("shares", "deltaShares"))


@dataclass(frozen=True, slots=True)
class ArchivedHistory:
    items: list[dict[str, Any]]
    coverage: dict[str, Any] | None
    generations: int


def _value(item: dict[str, Any], metric: str) -> Any:
    counter = item.get(metric)
    return counter.get("value") if isinstance(counter, dict) else None


def merge(parts: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Слить выдачи (каждая от новых к старым) и досчитать приросты на стыках.

    Внутри поколения прирост посчитан запросом API; у первого замера поколения
    его нет — предыдущий замер лежит в другом файле.
    """
    seen: set[str] = set()
    items = []
    for part in parts:
        for item in part:
            if item["snapshotId"] not in seen:
                seen.add(item["snapshotId"])
                items.append(dict(item))
    items.sort(key=lambda item: (item["observedAt"], int(item["snapshotId"])), reverse=True)
    for newer, older in zip(items, items[1:]):
        for metric, field in DELTAS:
            if newer.get(field) is None:
                current, previous = _value(newer, metric), _value(older, metric)
                if current is not None and previous is not None:
                    newer[field] = current - previous
    return items


class ColdArchiveReader:
    def __init__(self, root: Path | None = None, clock: Any = time.monotonic) -> None:
        self.root = root or Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT)))
        self.reader = BrowseReader()
        self._clock = clock
        self._months: dict[date, tuple[float, list[Path]]] = {}

    async def files(self, db: Any, month: date) -> list[Path]:
        cached = self._months.get(month)
        if cached and self._clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        rows = await db.fetch_all(GENERATIONS, {"month": month})
        paths = [store.object_path(self.root, "archive_browse", row["name"]) for row in rows]
        self._months[month] = (self._clock(), paths)
        return paths

    async def history(self, db: Any, month: date, publication_id: str) -> ArchivedHistory | None:
        paths = await self.files(db, month)
        if not paths:
            return None

        def read() -> ArchivedHistory:
            parts, coverage = [], None
            for path in paths:
                record = self.reader.read(path, publication_id)
                if record is not None:
                    parts.append(record.items)
                    coverage = record.coverage or coverage
            return ArchivedHistory(merge(parts), coverage, len(paths))

        return await asyncio.to_thread(read)
