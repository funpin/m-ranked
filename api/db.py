"""Пулы соединений. Чтение и запись разведены по ролям базы."""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._read: AsyncConnectionPool | None = None
        self._admin: AsyncConnectionPool | None = None

    async def open(self) -> None:
        s = self._settings
        self._read = await self._pool(s.read_dsn, s.read_pool_min, s.read_pool_max)
        if s.admin_dsn:
            # Командам админки хватает пары соединений: это редкий путь.
            self._admin = await self._pool(s.admin_dsn, 1, 4)

    async def _pool(self, dsn: str, minimum: int, maximum: int) -> AsyncConnectionPool:
        pool = AsyncConnectionPool(
            dsn, min_size=minimum, max_size=maximum, open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=self._configure,
        )
        await pool.open(wait=True, timeout=30)
        return pool

    async def _configure(self, connection: Any) -> None:
        # Ни один публичный запрос не имеет права висеть дольше бюджета ответа.
        await connection.execute(
            f"SET statement_timeout = {self._settings.statement_timeout_ms}")
        await connection.execute("SET idle_in_transaction_session_timeout = 30000")

    async def close(self) -> None:
        for pool in (self._read, self._admin):
            if pool is not None:
                await pool.close()

    @contextlib.asynccontextmanager
    async def read(self) -> AsyncIterator[Any]:
        assert self._read is not None, "пул чтения не открыт"
        async with self._read.connection() as connection:
            yield connection

    @contextlib.asynccontextmanager
    async def admin(self) -> AsyncIterator[Any]:
        if self._admin is None:
            from .errors import ApiProblem
            raise ApiProblem(503, "Service Unavailable", "административная база не настроена")
        async with self._admin.connection() as connection:
            yield connection

    async def fetch_all(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None
                        ) -> list[dict[str, Any]]:
        async with self.read() as connection:
            cursor = await connection.execute(sql, params)
            return await cursor.fetchall()

    async def fetch_one(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None
                        ) -> dict[str, Any] | None:
        async with self.read() as connection:
            cursor = await connection.execute(sql, params)
            return await cursor.fetchone()

    async def fetch_value(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None) -> Any:
        row = await self.fetch_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()))

    async def admin_fetch_one(self, sql: str,
                              params: Sequence[Any] | dict[str, Any] | None = None
                              ) -> dict[str, Any] | None:
        async with self.admin() as connection:
            cursor = await connection.execute(sql, params)
            return await cursor.fetchone()

    async def admin_fetch_all(self, sql: str,
                              params: Sequence[Any] | dict[str, Any] | None = None
                              ) -> list[dict[str, Any]]:
        async with self.admin() as connection:
            cursor = await connection.execute(sql, params)
            return await cursor.fetchall()

    async def stream(self, sql: str, params: Sequence[Any] | dict[str, Any] | None = None,
                     batch_size: int = 500) -> AsyncIterator[dict[str, Any]]:
        """Читает большой результат серверным курсором в одном repeatable-read снимке."""
        async with self.read() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                async with connection.cursor(name="mranked_export") as cursor:
                    await cursor.execute(sql, params)
                    while rows := await cursor.fetchmany(batch_size):
                        for row in rows:
                            yield row
