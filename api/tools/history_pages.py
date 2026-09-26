"""Готовая выдача истории замеров для постов с законченным сбором.

У поста старше сорока суток сбор закончен, и первая страница его истории
больше не меняется. Живой расчёт стоит около секунды базы (замеры одного поста
разбросаны по страницам таблицы), а роботы открывают каждый пост по разу —
кэш против этого бессилен. Задание считает выдачу тем же запросом и тем же
DTO, что и API, и складывает её в analytics.publication_history_page
(миграция 0043). API берёт её, пока отпечаток снимков совпадает.

Каждый прогон ограничен по времени и идёт вполсилы: после каждого поста
пауза не меньше времени его расчёта, чтобы база оставалась людям. Сначала —
посты без готовой выдачи (свежезамороженные первыми), затем сверка самых
давних готовых: поправка снимка меняет отпечаток, и выдача пересчитывается.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import sys
import time
import zlib

from .. import dto
from ..sql import details

logger = logging.getLogger("history-pages")

# Первая страница любого размера до 2000 плюс признак продолжения.
FETCH_LIMIT = 2001

CANDIDATES = """
SELECT publication.id, publication.published_at
  FROM ingest.visible_publication publication
 WHERE publication.published_at < now() - make_interval(days => %(min_age_days)s)
   AND NOT EXISTS (SELECT 1 FROM analytics.publication_history_page page
                    WHERE page.publication_id = publication.id)
   AND publication.id <> ALL(%(skip)s::uuid[])
 ORDER BY publication.published_at DESC
 LIMIT %(limit)s
"""

OLDEST = """
SELECT page.publication_id AS id, publication.published_at,
       page.snapshot_count, page.max_snapshot_id
  FROM analytics.publication_history_page page
  JOIN ingest.visible_publication publication ON publication.id = page.publication_id
 ORDER BY page.computed_at
 LIMIT %(limit)s
"""

TOUCH = """
UPDATE analytics.publication_history_page SET computed_at = transaction_timestamp()
 WHERE publication_id = %(id)s
"""

UPSERT = """
INSERT INTO analytics.publication_history_page AS page (
    publication_id, published_month, snapshot_count, max_snapshot_id, items_count, payload, computed_at)
VALUES (%(id)s, %(published_month)s, %(snapshot_count)s, %(max_snapshot_id)s, %(items_count)s, %(payload)s,
        transaction_timestamp())
ON CONFLICT (publication_id) DO UPDATE SET
    published_month = excluded.published_month, snapshot_count = excluded.snapshot_count,
    max_snapshot_id = excluded.max_snapshot_id, items_count = excluded.items_count,
    payload = excluded.payload, computed_at = excluded.computed_at
"""


def encode(items: list[dict]) -> bytes:
    """Тот же JSON, что отдаёт API (cached.serve: default=str), сжатый zlib."""
    return zlib.compress(json.dumps(items, ensure_ascii=False, separators=(",", ":"), default=str).encode(), 6)


def month(published_at: datetime) -> object:
    # Как в API: дата публикации в часовом поясе сессии (UTC), первое число.
    return published_at.date().replace(day=1)


def build(connection, publication_id, published_at: datetime) -> dict:
    published_month = month(published_at)
    key = {"publication_id": publication_id, "published_month": published_month}
    # Отпечаток — до расчёта: снимок, пришедший во время расчёта, изменит
    # отпечаток, и API не поверит этой выдаче.
    fingerprint = connection.execute(details.HISTORY_FINGERPRINT, key).fetchone()
    rows = connection.execute(details.HISTORY, {
        **key, "as_of": datetime.now(timezone.utc), "after_snapshot_id": None, "fetch_limit": FETCH_LIMIT,
    }).fetchall()
    items = [dto.history_snapshot(row) for row in rows]
    return {"id": publication_id, "published_month": published_month,
            "snapshot_count": fingerprint["snapshot_count"], "max_snapshot_id": fingerprint["max_snapshot_id"],
            "items_count": len(items), "payload": encode(items)}


def run(connection, *, max_seconds: float, min_age_days: int, recheck: int, pace: float,
        clock=time.monotonic, sleep=time.sleep) -> dict[str, int]:
    started = clock()
    done = {"computed": 0, "rechecked": 0, "refreshed": 0, "failed": 0}

    def left() -> float:
        return max_seconds - (clock() - started)

    failed: list = []

    def compute(row) -> bool:
        began = clock()
        try:
            connection.execute(UPSERT, build(connection, row["id"], row["published_at"]))
        except Exception as error:  # noqa: BLE001 — один пост не должен останавливать прогон
            # Пост пропускается до следующего прогона; иначе выборка
            # кандидатов возвращала бы его снова и снова.
            logger.warning("history page failed publication=%s class=%s", row["id"], type(error).__name__)
            failed.append(row["id"])
            return False
        spent = clock() - began
        # Вполсилы: пауза не меньше времени расчёта, пока позволяет бюджет.
        if left() > spent * pace:
            sleep(spent * pace)
        return True

    while left() > 0:
        batch = connection.execute(CANDIDATES, {"min_age_days": min_age_days, "limit": 50, "skip": failed}).fetchall()
        if not batch:
            break
        for row in batch:
            if left() <= 0:
                done["failed"] = len(failed)
                return done
            if compute(row):
                done["computed"] += 1

    done["failed"] = len(failed)
    if left() <= 0:
        return done
    for row in connection.execute(OLDEST, {"limit": recheck}).fetchall():
        if left() <= 0:
            break
        current = connection.execute(details.HISTORY_FINGERPRINT, {
            "publication_id": row["id"], "published_month": month(row["published_at"])}).fetchone()
        done["rechecked"] += 1
        if (current["snapshot_count"], current["max_snapshot_id"]) == (row["snapshot_count"], row["max_snapshot_id"]):
            connection.execute(TOUCH, {"id": row["id"]})
        elif compute(row):
            done["refreshed"] += 1
    done["failed"] = len(failed)
    return done


def number(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        raise SystemExit(f"{name} must be a number") from None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import psycopg
    from psycopg.rows import dict_row

    dsn = os.environ["MAINTENANCE_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        # Те же условия, что у запросов API (роль api_read): часовой пояс UTC
        # для месяца партиции, без JIT и с той же стоимостью случайного чтения.
        for statement in ("SET timezone = 'UTC'", "SET jit = off", "SET random_page_cost = 1.1",
                          "SET statement_timeout = '30s'", "SET lock_timeout = '1s'"):
            connection.execute(statement)
        done = run(connection,
                   max_seconds=number("HISTORY_PAGES_MAX_SECONDS", 240),
                   min_age_days=int(number("HISTORY_PAGES_MIN_AGE_DAYS", 41)),
                   recheck=int(number("HISTORY_PAGES_RECHECK", 200)),
                   pace=number("HISTORY_PAGES_PACE", 1.0))
    logger.info("history pages computed=%(computed)s rechecked=%(rechecked)s refreshed=%(refreshed)s failed=%(failed)s", done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
