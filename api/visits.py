"""Уникальные посетители сайта без cookie (миграция 0053).

Маячок страницы попадает сюда; запрос отвечает сразу, ничего не записывая.
Посетители копятся в памяти процесса и раз в полминуты одной пачкой уходят в
базу: на каждый просмотр приходится доля одной вставки, а «сейчас на сайте»
отстаёт не больше чем на полминуты.

Посетитель — BLAKE2b(суточная соль ‖ адрес ‖ браузер). Соль общая для процессов
API и удаляется вместе с итогом суток, адрес не записывается никуда.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import secrets
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MOSCOW = ZoneInfo("Europe/Moscow")
FLUSH_SECONDS = 30.0
ROLLUP_SECONDS = 3600.0
# Итог закрытых суток подводится не раньше 00:05: к этому времени процессы
# успевают сбросить последние сигналы прошедших суток.
ROLLUP_GRACE = timedelta(minutes=5)
ONLINE_WINDOW = timedelta(minutes=5)
# Предел памяти на случай потока поддельных маячков: больше посетителей между
# сбросами не держим, лишние просто не считаются.
MAX_PENDING = 50_000
# Роботы с исполнением скриптов и предпросмотр ссылок — не посетители.
ROBOT = re.compile(
    r"bot|crawl|spider|slurp|preview|headless|lighthouse|pagespeed|python|curl|wget|"
    r"httpclient|okhttp|axios|node-fetch|go-http|java/|monitor|uptime|phantom|selenium|playwright",
    re.IGNORECASE)

SALT_INSERT = """
INSERT INTO ops_and_admin.visit_salt(day, salt) VALUES (%(day)s, %(salt)s)
ON CONFLICT (day) DO NOTHING
"""
SALT_SELECT = "SELECT salt FROM ops_and_admin.visit_salt WHERE day=%(day)s"
UPSERT = """
INSERT INTO ops_and_admin.site_visitor(day, visitor, first_seen, last_seen, views)
SELECT * FROM unnest(%(days)s::date[], %(visitors)s::bytea[], %(first)s::timestamptz[],
                     %(last)s::timestamptz[], %(views)s::integer[])
ON CONFLICT (day, visitor) DO UPDATE SET
  first_seen=least(site_visitor.first_seen, excluded.first_seen),
  last_seen=greatest(site_visitor.last_seen, excluded.last_seen),
  views=site_visitor.views + excluded.views
"""
# DELETE … RETURNING забирает строку ровно один раз: два процесса, подводящие
# итог одновременно, не посчитают посетителя дважды.
ROLLUP = """
WITH closed AS (
  DELETE FROM ops_and_admin.site_visitor WHERE day < %(today)s RETURNING day, views
)
INSERT INTO ops_and_admin.site_visit_daily(day, visitors, views)
SELECT day, count(*), sum(views) FROM closed GROUP BY day
ON CONFLICT (day) DO UPDATE SET
  visitors=site_visit_daily.visitors + excluded.visitors,
  views=site_visit_daily.views + excluded.views
"""
SALT_PURGE = "DELETE FROM ops_and_admin.visit_salt WHERE day < %(today)s"


def moscow_day(now: float) -> date:
    return datetime.fromtimestamp(now, MOSCOW).date()


def is_robot(agent: str) -> bool:
    return not agent or len(agent) < 20 or bool(ROBOT.search(agent))


def visitor_id(salt: bytes, address: str, agent: str) -> bytes:
    return hashlib.blake2b(salt + address.encode() + b"\0" + agent.encode(),
                           digest_size=16).digest()


class VisitCounter:
    def __init__(self, database: Any, clock: Callable[[], float] = time.time) -> None:
        self._database = database
        self._clock = clock
        self._salts: dict[date, bytes] = {}
        # (сутки, посетитель) → [первый сигнал, последний сигнал, просмотры]
        self._pending: dict[tuple[date, bytes], list[Any]] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._rolled_at = 0.0

    async def _salt(self, day: date) -> bytes:
        salt = self._salts.get(day)
        if salt is None:
            await self._database.admin_execute(SALT_INSERT, {"day": day, "salt": secrets.token_bytes(32)})
            row = await self._database.admin_fetch_one(SALT_SELECT, {"day": day})
            salt = bytes(row["salt"])
            # Соль прошедших суток процессу больше не нужна.
            self._salts = {day: salt}
        return salt

    async def record(self, address: str, agent: str, view: bool) -> bool:
        """Учесть сигнал страницы. False — сигнал не считается посетителем."""
        if is_robot(agent):
            return False
        now = self._clock()
        day = moscow_day(now)
        visitor = visitor_id(await self._salt(day), address, agent)
        moment = datetime.fromtimestamp(now, timezone.utc)
        async with self._lock:
            entry = self._pending.get((day, visitor))
            if entry is None:
                if len(self._pending) >= MAX_PENDING:
                    return False
                self._pending[(day, visitor)] = [moment, moment, int(view)]
            else:
                entry[1] = moment
                entry[2] += int(view)
        return True

    async def flush(self) -> int:
        async with self._lock:
            pending, self._pending = self._pending, {}
        if not pending:
            return 0
        rows = [(day, visitor, *values) for (day, visitor), values in pending.items()]
        try:
            await self._database.admin_execute(UPSERT, {
                "days": [row[0] for row in rows], "visitors": [row[1] for row in rows],
                "first": [row[2] for row in rows], "last": [row[3] for row in rows],
                "views": [row[4] for row in rows]})
        except Exception:
            # База недоступна: вернуть сигналы в буфер и попробовать в следующий раз.
            async with self._lock:
                for key, values in pending.items():
                    current = self._pending.get(key)
                    if current is None:
                        self._pending[key] = values
                    else:
                        current[0] = min(current[0], values[0])
                        current[2] += values[2]
            raise
        return len(rows)

    async def rollup(self) -> None:
        now = self._clock()
        local = datetime.fromtimestamp(now, MOSCOW)
        if local - local.replace(hour=0, minute=0, second=0, microsecond=0) < ROLLUP_GRACE:
            return
        today = local.date()
        await self._database.admin_execute(ROLLUP, {"today": today})
        await self._database.admin_execute(SALT_PURGE, {"today": today})
        self._rolled_at = now

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            try:
                await self.flush()
                if self._clock() - self._rolled_at >= ROLLUP_SECONDS:
                    await self.rollup()
            except Exception as error:  # noqa: BLE001 — счёт посещений не должен ронять API
                logger.warning("посещения не сохранены: %s", type(error).__name__)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(Exception):
            await self.flush()
