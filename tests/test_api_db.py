from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api import db


def test_admin_pool_checks_connection_before_checkout(monkeypatch) -> None:
    created: list[dict[str, object]] = []

    class FakePool:
        check_connection = object()

        def __init__(self, _dsn: str, **kwargs: object) -> None:
            created.append(kwargs)

        async def open(self, *, wait: bool, timeout: int) -> None:
            assert wait is True and timeout == 30

    monkeypatch.setattr(db, "AsyncConnectionPool", FakePool)
    database = db.Database(SimpleNamespace(statement_timeout_ms=15_000))

    asyncio.run(database._pool("read", 2, 8))
    asyncio.run(database._pool("admin", 1, 4, check_connection=True))

    assert created[0]["check"] is None
    assert created[1]["check"] is FakePool.check_connection
