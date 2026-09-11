"""Пометка outbox-событий доставленными после транзакционного NOTIFY."""
from __future__ import annotations

import asyncio
import logging

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

MARK_BATCH = """
WITH candidate AS (
  SELECT id FROM ops_and_admin.outbox_event
  WHERE published_at IS NULL AND terminal_at IS NULL
    AND available_at<=transaction_timestamp()
  ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 500
), marked AS (
  UPDATE ops_and_admin.outbox_event event
  SET publish_attempts=event.publish_attempts+1,
      published_at=transaction_timestamp(),available_at=transaction_timestamp(),
      last_error_code=NULL
  FROM candidate WHERE event.id=candidate.id RETURNING event.id
)
SELECT count(*)::integer AS count FROM marked
"""


class OutboxMarker:
    """Завершает durable envelope; сам сброс кэша делает INSERT-trigger NOTIFY.

    Пропущенный NOTIFY безопасен: при переподключении listener очищает LRU, а
    обычный TTL ограничивает жизнь уже выданного представления.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self._run(), name="outbox-delivery-marker")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self.dsn, autocommit=False, row_factory=dict_row) as connection:
                    await connection.execute("SET statement_timeout='15s'")
                    backoff = 1.0
                    while True:
                        async with connection.transaction():
                            row = await (await connection.execute(MARK_BATCH)).fetchone()
                        count = row["count"]
                        if count == 0:
                            await asyncio.sleep(2)
                        elif count < 500:
                            await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("пометка outbox недоступна, повтор через %.0f с", backoff,
                               exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff*2, 30.0)
