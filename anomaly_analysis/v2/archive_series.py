"""Ряды постов месяцев, ушедших в холодный архив (ADR-016).

После удаления партиции замеры месяца лежат в файлах просмотра его поколений
на основном сервере, а в базе остаются только поздние замеры, пришедшие после
архивации. Работник анализа обычно таких постов не трогает: они заморожены.
Ряд нужен, когда администратор просит прогнать анализ месяца заново, —
тогда он собирается из архива и поздних строк базы в тот же вид, что даёт
запрос SERIES хранилища.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import UUID

from operations.cold_archive.browse import BrowseReader
from operations.storage import store

logger = logging.getLogger("anomaly.archive_series")

COLD_FILES = """
SELECT generation.published_month, object.name
  FROM ops_and_admin.cold_archive_generation generation
  JOIN ops_and_admin.storage_object object ON object.id = generation.browse_object_id
 WHERE generation.state = 'cold' AND generation.published_month = ANY(%(months)s::date[])
 ORDER BY generation.published_month, generation.generation
"""
TARGETS = """
SELECT publication.id, publication.primary_account_id, account.platform::text AS platform,
       publication.published_at, publication.is_repost
  FROM ingest.visible_publication publication
  JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
 WHERE publication.id = ANY(%(ids)s::uuid[])
"""
METRICS = ("views", "reactions", "comments", "shares")
# Без миграции 0057 или без права чтения реестра архив просто не используется;
# повторная проверка — не чаще, чем раз в десять минут.
RETRY_SECONDS = 600.0


def archive_row(target: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Элемент выдачи истории (api.dto.history_snapshot) → строка запроса SERIES."""
    if item.get("synthetic"):
        return None
    row: dict[str, Any] = {key: target[key] for key in ("id", "primary_account_id", "platform", "published_at",
                                                        "is_repost")}
    row["observed_at"] = datetime.fromisoformat(item["observedAt"])
    row["interval_uncertain"] = bool(item.get("intervalUncertain", True))
    for metric in METRICS:
        counter = item.get(metric) if isinstance(item.get(metric), dict) else {}
        row[f"{metric}_count"] = counter.get("value")
        row[f"{metric}_quality"] = counter.get("quality")
    # Как в SERIES: разбивка нужна только округлённым реакциям Telegram.
    breakdown = item.get("reactionsBreakdown")
    row["reaction_breakdown"] = (breakdown or {}) if (
        target["platform"] == "telegram" and row["reactions_quality"] in ("rounded", "unknown")) else None
    row["_snapshot_id"] = int(item["snapshotId"])
    return row


def merge_rows(archived: Iterable[Mapping[str, Any]], hot: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Архивные и поздние строки по времени; на одно время — одна строка (как DISTINCT ON)."""
    by_time: dict[datetime, dict[str, Any]] = {}
    for row in archived:
        current = by_time.get(row["observed_at"])
        if current is None or row.get("_snapshot_id", 0) > current.get("_snapshot_id", 0):
            by_time[row["observed_at"]] = dict(row)
    for row in hot:
        # Строка базы новее архива: поздний замер или поправка после выгрузки.
        by_time[row["observed_at"]] = dict(row)
    return [by_time[moment] for moment in sorted(by_time)]


class ArchiveSeriesSource:
    def __init__(self, root: Path | None = None, clock: Any = time.monotonic) -> None:
        self.root = root or Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT)))
        self.reader = BrowseReader()
        self._clock = clock
        self._unavailable_until = float("-inf")

    def cold_files(self, connection: Any, months: Sequence[date]) -> dict[date, list[Path]]:
        if not months or self._clock() < self._unavailable_until:
            return {}
        try:
            rows = connection.execute(COLD_FILES, {"months": list(months)}).fetchall()
        except Exception as error:  # noqa: BLE001 — реестра нет или нет прав: архив не используется
            logger.warning("cold archive registry unavailable class=%s", type(error).__name__)
            self._unavailable_until = self._clock() + RETRY_SECONDS
            return {}
        result: dict[date, list[Path]] = {}
        for row in rows:
            result.setdefault(row["published_month"], []).append(
                store.object_path(self.root, "archive_browse", row["name"]))
        return result

    def rows(self, connection: Any, ids: Sequence[UUID], files: Mapping[date, list[Path]],
             month_of: Mapping[UUID, date]) -> tuple[dict[UUID, list[dict[str, Any]]], set[UUID]]:
        """Архивные строки постов, чей месяц в архиве, и посты, чей архив не прочитать.

        Пост без записи в архиве в ответ не попадает. Пост, чей файл недоступен,
        возвращается во втором множестве: анализировать его по одним поздним
        строкам базы нельзя — вывод был бы по обрывку ряда.
        """
        wanted = [publication for publication in ids if month_of.get(publication) in files]
        if not wanted:
            return {}, set()
        targets = {row["id"]: row for row in connection.execute(TARGETS, {"ids": wanted}).fetchall()}
        result: dict[UUID, list[dict[str, Any]]] = {}
        unreadable: set[UUID] = set()
        for publication, target in targets.items():
            rows: list[dict[str, Any]] = []
            try:
                for path in files[month_of[publication]]:
                    record = self.reader.read(path, str(publication))
                    if record is not None:
                        rows.extend(row for item in record.items if (row := archive_row(target, item)) is not None)
            except (OSError, sqlite3.Error, ValueError) as error:
                logger.warning("cold archive file unreadable month=%s class=%s",
                               month_of[publication], type(error).__name__)
                unreadable.add(publication)
                continue
            if rows:
                result[publication] = rows
        return result, unreadable
