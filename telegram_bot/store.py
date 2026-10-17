"""Хранилище бота: настройки, получатели, учёт отправленного, задержанные тревоги.

PostgresStore работает в таблицах bot_* схемы ops_and_admin (миграция 0087) и
читает одну чужую таблицу, host_sample. В проде он логинится ролью telegram_bot,
так что любой запрос вне этого списка упрётся в права. MemoryStore повторяет
контракт для тестов остальных модулей бота без базы.
"""
from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# Ключи настроек.
OUR_INSTITUTION = "our_institution"

ANNOUNCED_KEEP = timedelta(days=60)
SNAPSHOT_KEEP = timedelta(days=30)
STATEMENT_TIMEOUT = "5s"
CONNECT_TIMEOUT = 10

T = TypeVar("T")


@dataclass
class Recipient:
    chat_id: int
    kind: Literal["person", "chat"]
    title: str
    is_admin: bool = False
    alerts: bool = False
    digest: bool = False
    spike: bool = False
    anomaly: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ("person", "chat"):
            raise ValueError(f"Неизвестный вид получателя: {self.kind!r}")
        if self.kind == "chat" and (self.alerts or self.is_admin):
            raise ValueError("Тревоги и права администратора — только человеку, не чату")


class Store(Protocol):
    async def get_setting(self, key: str) -> Any: ...
    async def set_setting(self, key: str, value: Any, by: int | None) -> None: ...
    async def recipients(self) -> list[Recipient]: ...
    async def upsert_recipient(self, r: Recipient, by: int | None) -> None: ...
    async def remove_recipient(self, chat_id: int) -> None: ...
    async def migrate_chat(self, old: int, new: int) -> None: ...
    async def mark_announced(self, kind: str, publication_id: str, level: int) -> bool: ...
    async def has_announced_any(self, kind: str) -> bool: ...
    async def set_mute(self, key: str, until: float, by: int) -> None: ...
    async def muted_until(self, key: str) -> float | None: ...
    async def hold_alert(self, event: dict) -> None: ...
    async def take_held(self) -> list[dict]: ...
    async def save_week_snapshot(self, day: date, stats: dict) -> None: ...
    async def week_snapshot(self, day: date) -> dict | None: ...
    async def job_last_run(self, name: str) -> float | None: ...
    async def set_job_run(self, name: str, at: float) -> None: ...
    async def prune(self, now: float) -> None: ...
    async def status_rows(self, seconds: int) -> list[dict]: ...


class MemoryStore:
    """Хранилище в памяти для тестов; host_samples подкладывает тест."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}
        self._recipients: dict[int, Recipient] = {}
        self._announced: dict[tuple[str, str], tuple[int, float]] = {}
        self._mutes: dict[str, float] = {}
        self._held: list[dict] = []
        self._snapshots: dict[date, dict] = {}
        self._jobs: dict[str, float] = {}
        self.host_samples: list[dict] = []

    async def get_setting(self, key: str) -> Any:
        return copy.deepcopy(self._settings.get(key))

    async def set_setting(self, key: str, value: Any, by: int | None) -> None:
        self._settings[key] = copy.deepcopy(value)

    async def recipients(self) -> list[Recipient]:
        return [replace(r) for _, r in sorted(self._recipients.items())]

    async def upsert_recipient(self, r: Recipient, by: int | None) -> None:
        self._recipients[r.chat_id] = replace(r)

    async def remove_recipient(self, chat_id: int) -> None:
        self._recipients.pop(chat_id, None)

    async def migrate_chat(self, old: int, new: int) -> None:
        if old == new:
            return
        moved = self._recipients.pop(old, None)
        if moved is not None and new not in self._recipients:
            self._recipients[new] = replace(moved, chat_id=new)

    async def mark_announced(self, kind: str, publication_id: str, level: int) -> bool:
        key = (kind, str(publication_id))
        known = self._announced.get(key)
        if known is not None and known[0] >= level:
            return False
        self._announced[key] = (level, time.time())
        return True

    async def has_announced_any(self, kind: str) -> bool:
        return any(announced_kind == kind for announced_kind, _ in self._announced)

    async def set_mute(self, key: str, until: float, by: int) -> None:
        self._mutes[key] = until

    async def muted_until(self, key: str) -> float | None:
        until = self._mutes.get(key)
        return until if until is not None and until > time.time() else None

    async def hold_alert(self, event: dict) -> None:
        self._held.append(copy.deepcopy(event))

    async def take_held(self) -> list[dict]:
        held, self._held = self._held, []
        return held

    async def save_week_snapshot(self, day: date, stats: dict) -> None:
        self._snapshots[day] = copy.deepcopy(stats)

    async def week_snapshot(self, day: date) -> dict | None:
        return copy.deepcopy(self._snapshots.get(day))

    async def job_last_run(self, name: str) -> float | None:
        return self._jobs.get(name)

    async def set_job_run(self, name: str, at: float) -> None:
        self._jobs[name] = at

    async def prune(self, now: float) -> None:
        announced_before = now - ANNOUNCED_KEEP.total_seconds()
        self._announced = {key: value for key, value in self._announced.items()
                           if value[1] >= announced_before}
        oldest_day = datetime.fromtimestamp(now, UTC).date() - SNAPSHOT_KEEP
        self._snapshots = {day: stats for day, stats in self._snapshots.items() if day >= oldest_day}
        self._mutes = {key: until for key, until in self._mutes.items() if until >= now}

    async def status_rows(self, seconds: int) -> list[dict]:
        since = datetime.now(UTC) - timedelta(seconds=seconds)
        rows = [row for row in self.host_samples if row["observed_at"] >= since]
        return [copy.deepcopy(row) for row in sorted(rows, key=lambda row: row["observed_at"])]


class PostgresStore:
    """Одно соединение psycopg, автокоммит; при обрыве — одно переподключение."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: psycopg.AsyncConnection | None = None
        # Одно соединение — один запрос за раз.
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        async with self._lock:
            await self._drop()

    async def __aenter__(self) -> PostgresStore:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001 - соединение уже сломано, закрываем что можем
                pass

    async def _connect(self) -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(
            self._dsn, autocommit=True, row_factory=dict_row, connect_timeout=CONNECT_TIMEOUT)
        try:
            await conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        except BaseException:
            await conn.close()
            raise
        return conn

    async def _with_connection(self, work: Callable[[psycopg.AsyncConnection], Awaitable[T]],
                               retry: bool = True) -> T:
        """retry=False для неидемпотентных запросов (take_held, mark_announced): при обрыве
        соединение сбрасывается и следующий вызов подключится заново, но сам запрос не
        повторяется — он мог уже выполниться, и повтор потерял бы или удвоил результат."""
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = await self._connect()
                    return await work(self._conn)
                except psycopg.errors.QueryCanceled:
                    # Запрос упёрся в statement_timeout: повтор лишь удвоит ожидание.
                    raise
                except (psycopg.OperationalError, psycopg.InterfaceError):
                    await self._drop()
                    if attempt == 2 or not retry:
                        raise
                except asyncio.CancelledError:
                    # Отменённый посреди запроса вызов оставляет соединение в неизвестном состоянии.
                    await self._drop()
                    raise
            raise AssertionError("недостижимо")  # pragma: no cover

    async def _rows(self, sql: str, params: dict | None = None, *, retry: bool = True) -> list[dict]:
        async def work(conn: psycopg.AsyncConnection) -> list[dict]:
            cursor = await conn.execute(sql, params)
            return await cursor.fetchall() if cursor.description else []
        return await self._with_connection(work, retry)

    async def _value(self, sql: str, params: dict | None = None) -> Any:
        rows = await self._rows(sql, params)
        return next(iter(rows[0].values())) if rows else None

    async def get_setting(self, key: str) -> Any:
        return await self._value(
            "SELECT value FROM ops_and_admin.bot_setting WHERE key = %(key)s", {"key": key})

    async def set_setting(self, key: str, value: Any, by: int | None) -> None:
        await self._rows(
            "INSERT INTO ops_and_admin.bot_setting(key, value, updated_at, updated_by) "
            "VALUES (%(key)s, %(value)s, now(), %(by)s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
            "updated_at = EXCLUDED.updated_at, updated_by = EXCLUDED.updated_by",
            {"key": key, "value": Jsonb(value), "by": by})

    async def recipients(self) -> list[Recipient]:
        rows = await self._rows(
            "SELECT chat_id, kind, title, is_admin, alerts, digest, spike, anomaly "
            "FROM ops_and_admin.bot_recipient ORDER BY chat_id")
        return [Recipient(**row) for row in rows]

    async def upsert_recipient(self, r: Recipient, by: int | None) -> None:
        await self._rows(
            "INSERT INTO ops_and_admin.bot_recipient"
            "(chat_id, kind, title, is_admin, alerts, digest, spike, anomaly, added_by) "
            "VALUES (%(chat_id)s, %(kind)s, %(title)s, %(is_admin)s, %(alerts)s, %(digest)s, "
            "%(spike)s, %(anomaly)s, %(by)s) "
            "ON CONFLICT (chat_id) DO UPDATE SET kind = EXCLUDED.kind, title = EXCLUDED.title, "
            "is_admin = EXCLUDED.is_admin, alerts = EXCLUDED.alerts, digest = EXCLUDED.digest, "
            "spike = EXCLUDED.spike, anomaly = EXCLUDED.anomaly",
            {"chat_id": r.chat_id, "kind": r.kind, "title": r.title, "is_admin": r.is_admin,
             "alerts": r.alerts, "digest": r.digest, "spike": r.spike, "anomaly": r.anomaly,
             "by": by})

    async def remove_recipient(self, chat_id: int) -> None:
        await self._rows("DELETE FROM ops_and_admin.bot_recipient WHERE chat_id = %(id)s",
                         {"id": chat_id})

    async def migrate_chat(self, old: int, new: int) -> None:
        if old == new:
            return

        async def work(conn: psycopg.AsyncConnection) -> None:
            async with conn.transaction():
                # Флаги переезжают вместе со строкой; если новый чат уже есть — старая запись просто уходит.
                await conn.execute(
                    "UPDATE ops_and_admin.bot_recipient SET chat_id = %(new)s WHERE chat_id = %(old)s "
                    "AND NOT EXISTS (SELECT 1 FROM ops_and_admin.bot_recipient WHERE chat_id = %(new)s)",
                    {"old": old, "new": new})
                await conn.execute("DELETE FROM ops_and_admin.bot_recipient WHERE chat_id = %(old)s",
                                   {"old": old})
        await self._with_connection(work)

    async def mark_announced(self, kind: str, publication_id: str, level: int) -> bool:
        rows = await self._rows(
            "INSERT INTO ops_and_admin.bot_announced(kind, publication_id, level) "
            "VALUES (%(kind)s, %(pid)s::uuid, %(level)s) "
            "ON CONFLICT (kind, publication_id) DO UPDATE "
            "SET level = EXCLUDED.level, announced_at = now() "
            "WHERE bot_announced.level < EXCLUDED.level RETURNING 1",
            {"kind": kind, "pid": str(publication_id), "level": level}, retry=False)
        return bool(rows)

    async def has_announced_any(self, kind: str) -> bool:
        return bool(await self._value(
            "SELECT EXISTS (SELECT 1 FROM ops_and_admin.bot_announced WHERE kind = %(kind)s)",
            {"kind": kind}))

    async def set_mute(self, key: str, until: float, by: int) -> None:
        await self._rows(
            "INSERT INTO ops_and_admin.bot_alert_mute(key, until, muted_by) "
            "VALUES (%(key)s, to_timestamp(%(until)s), %(by)s) "
            "ON CONFLICT (key) DO UPDATE SET until = EXCLUDED.until, muted_by = EXCLUDED.muted_by",
            {"key": key, "until": until, "by": by})

    async def muted_until(self, key: str) -> float | None:
        value = await self._value(
            "SELECT extract(epoch FROM until) FROM ops_and_admin.bot_alert_mute "
            "WHERE key = %(key)s AND until > now()", {"key": key})
        return None if value is None else float(value)

    async def hold_alert(self, event: dict) -> None:
        await self._rows("INSERT INTO ops_and_admin.bot_held_alert(event) VALUES (%(event)s)",
                         {"event": Jsonb(event)})

    async def take_held(self) -> list[dict]:
        # Один оператор: забрать и удалить разом, чтобы тревога не ушла дважды и не потерялась.
        rows = await self._rows(
            "WITH taken AS (DELETE FROM ops_and_admin.bot_held_alert RETURNING id, event) "
            "SELECT event FROM taken ORDER BY id", retry=False)
        return [row["event"] for row in rows]

    async def save_week_snapshot(self, day: date, stats: dict) -> None:
        await self._rows(
            "INSERT INTO ops_and_admin.bot_week_snapshot(day, stats) VALUES (%(day)s, %(stats)s) "
            "ON CONFLICT (day) DO UPDATE SET stats = EXCLUDED.stats",
            {"day": day, "stats": Jsonb(stats)})

    async def week_snapshot(self, day: date) -> dict | None:
        return await self._value(
            "SELECT stats FROM ops_and_admin.bot_week_snapshot WHERE day = %(day)s", {"day": day})

    async def job_last_run(self, name: str) -> float | None:
        value = await self._value(
            "SELECT extract(epoch FROM last_run_at) FROM ops_and_admin.bot_job WHERE name = %(name)s",
            {"name": name})
        return None if value is None else float(value)

    async def set_job_run(self, name: str, at: float) -> None:
        await self._rows(
            "INSERT INTO ops_and_admin.bot_job(name, last_run_at) VALUES (%(name)s, to_timestamp(%(at)s)) "
            "ON CONFLICT (name) DO UPDATE SET last_run_at = EXCLUDED.last_run_at",
            {"name": name, "at": at})

    async def prune(self, now: float) -> None:
        params = {"now": now, "announced": ANNOUNCED_KEEP.days, "snapshots": SNAPSHOT_KEEP.days}

        async def work(conn: psycopg.AsyncConnection) -> None:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM ops_and_admin.bot_announced "
                    "WHERE announced_at < to_timestamp(%(now)s) - make_interval(days => %(announced)s)", params)
                await conn.execute(
                    "DELETE FROM ops_and_admin.bot_week_snapshot "
                    "WHERE day < (to_timestamp(%(now)s) AT TIME ZONE 'UTC')::date - %(snapshots)s", params)
                await conn.execute(
                    "DELETE FROM ops_and_admin.bot_alert_mute WHERE until < to_timestamp(%(now)s)", params)
        await self._with_connection(work)

    async def status_rows(self, seconds: int) -> list[dict]:
        # Как в api/routes/system.py; крупный ключ sizes боту не нужен.
        return await self._rows(
            "SELECT observed_at, sample - 'sizes' AS sample FROM ops_and_admin.host_sample "
            "WHERE observed_at >= now() - make_interval(secs => %(seconds)s) ORDER BY observed_at",
            {"seconds": float(seconds)})
