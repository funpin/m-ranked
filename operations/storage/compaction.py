"""Упаковщик истории замеров (миграция 0059).

Замеры старше границы (по умолчанию 48 часов) переезжают из строк
ingest.publication_metric_snapshot в упакованную строку поста. Работа идёт
пачками: каждый пост — отдельная короткая транзакция, между пачками пауза
пропорционально проделанной работе (база остаётся посетителям), прогон
ограничен бюджетом времени — недоделанное продолжит следующий запуск.

После упаковки освобождаются партиции прошлых месяцев, в которых не осталось
горячих строк: удалённые строки держат место до пересоздания партиции.

    MAINTENANCE_DATABASE_URL=... python -m operations.storage.compaction
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable

log = logging.getLogger("history-compaction")

COMPACTABLE = "SELECT publication_id FROM ingest.compactable_publications(%s, %s)"
COMPACT = "SELECT ingest.compact_publication_history(%s, %s) AS moved"
MONTHS = """
SELECT to_date(substring(child.relname FROM 'publication_metric_snapshot_(\\d{4}_\\d{2})$'), 'YYYY_MM') AS month
  FROM pg_inherits link
  JOIN pg_class child ON child.oid = link.inhrelid
 WHERE link.inhparent = 'ingest.publication_metric_snapshot'::regclass
   AND child.relname ~ '^publication_metric_snapshot_\\d{4}_\\d{2}$'
 ORDER BY 1
"""
RELEASE = "SELECT ingest.release_empty_metric_partition(%s) AS released"


@dataclass(frozen=True, slots=True)
class Settings:
    hot: timedelta = timedelta(hours=48)
    batch: int = 100
    budget: timedelta = timedelta(minutes=20)
    pace: float = 0.5


@dataclass(slots=True)
class Result:
    publications: int = 0
    points: int = 0
    released: int = 0
    remaining: bool = False


def released_months(months: list[date], now: datetime) -> list[date]:
    """Месяцы, которые можно пробовать освобождать: не текущий и не прошлый —
    в них ещё идут замеры (окно наблюдения — тридцать суток)."""
    current = now.date().replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    return [month for month in months if month < previous]


def run(connection: Any, settings: Settings, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> Result:
    result = Result()
    started = monotonic()
    boundary = clock() - settings.hot
    while True:
        if monotonic() - started >= settings.budget.total_seconds():
            result.remaining = True
            break
        ids = [row["publication_id"] for row in connection.execute(COMPACTABLE, (boundary, settings.batch)).fetchall()]
        if not ids:
            break
        began = monotonic()
        for publication_id in ids:
            moved = connection.execute(COMPACT, (publication_id, boundary)).fetchone()["moved"]
            result.publications += 1
            result.points += int(moved or 0)
        if settings.pace:
            sleep((monotonic() - began) * settings.pace)
    months = [row["month"] for row in connection.execute(MONTHS).fetchall()]
    for month in released_months(months, clock()):
        try:
            if connection.execute(RELEASE, (month,)).fetchone()["released"]:
                result.released += 1
                log.info("released partition month=%s", month)
        except Exception as error:  # noqa: BLE001 — блокировку не дождались: следующий прогон
            log.warning("partition month=%s not released: %s", month, type(error).__name__)
    return result


def write_metrics(path: str, values: dict[str, float]) -> None:
    """Метрики для node_exporter одним заменяемым файлом."""
    if not path:
        return
    target = Path(path)
    temporary = target.with_name(f".{target.name}.{os.getpid()}")
    temporary.write_text("".join(f"{key} {value}\n" for key, value in values.items()))
    temporary.chmod(0o644)
    os.replace(temporary, target)


def main() -> int:
    import psycopg
    from psycopg.rows import dict_row

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings(
        hot=timedelta(hours=int(os.getenv("HISTORY_HOT_HOURS", "48"))),
        batch=int(os.getenv("HISTORY_COMPACTION_BATCH", "100")),
        budget=timedelta(minutes=int(os.getenv("HISTORY_COMPACTION_MINUTES", "20"))),
        pace=float(os.getenv("HISTORY_COMPACTION_PACE", "0.5")),
    )
    started = time.monotonic()
    with psycopg.connect(os.environ["MAINTENANCE_DATABASE_URL"], autocommit=True, row_factory=dict_row,
                         connect_timeout=10, options="-c statement_timeout=120000") as connection:
        result = run(connection, settings)
    log.info("compaction publications=%s points=%s released=%s remaining=%s",
             result.publications, result.points, result.released, result.remaining)
    write_metrics(os.getenv("HISTORY_COMPACTION_METRICS_FILE", "").strip(), {
        "mranked_history_compaction_last_run_unixtime": time.time(),
        "mranked_history_compaction_seconds": time.monotonic() - started,
        "mranked_history_compaction_publications": result.publications,
        "mranked_history_compaction_points": result.points,
        "mranked_history_compaction_released_partitions": result.released,
        "mranked_history_compaction_remaining": float(result.remaining),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
