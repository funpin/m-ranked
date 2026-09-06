from __future__ import annotations

import hashlib
from threading import Lock
from typing import Any, Callable

from .model import Platform, nonempty


def lease_name(platform: Platform, partition_key: str) -> str:
    return f"collector:{platform.value}:{nonempty(partition_key, 'partition_key')}"


def advisory_lock_key(value: str) -> int:
    """Map a lease name deterministically into PostgreSQL's signed bigint space."""
    unsigned = int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")
    return unsigned - 2**64 if unsigned >= 2**63 else unsigned


class _MemoryLease:
    def __init__(self, provider: "InMemoryLeaseProvider", key: str):
        self.provider = provider
        self.key = key
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        with self.provider._lock:
            self.provider._held.discard(self.key)
        self._released = True


class InMemoryLeaseProvider:
    """Process-local lease used in tests and single-process development."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._held: set[str] = set()

    def acquire(self, platform: Platform, partition_key: str) -> _MemoryLease | None:
        key = lease_name(platform, partition_key)
        with self._lock:
            if key in self._held:
                return None
            self._held.add(key)
        return _MemoryLease(self, key)


class _PostgresLease:
    def __init__(self, connection: Any, key: str, lock_id: int):
        self.connection = connection
        self.key = key
        self.lock_id = lock_id
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        try:
            self.connection.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
        finally:
            self.connection.close()
            self._released = True


class PostgresAdvisoryLeaseProvider:
    """Connection-scoped per-platform/partition lease without additional DDL."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        if connection_factory is None and not dsn:
            raise ValueError("dsn or connection_factory is required")
        self._factory = connection_factory or self._psycopg_factory(str(dsn))

    @staticmethod
    def _psycopg_factory(dsn: str) -> Callable[[], Any]:
        def connect() -> Any:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - packaging guard
                raise RuntimeError("psycopg is required for PostgreSQL leases") from exc
            return psycopg.connect(dsn, autocommit=True)

        return connect

    def acquire(self, platform: Platform, partition_key: str) -> _PostgresLease | None:
        key = lease_name(platform, partition_key)
        lock_id = advisory_lock_key(key)
        connection = self._factory()
        try:
            connection.execute("SET TIME ZONE 'UTC'")
            row = connection.execute(
                "SELECT pg_try_advisory_lock(%s)", (lock_id,),
            ).fetchone()
            acquired = bool(next(iter(row.values()))) if isinstance(row, dict) else bool(row[0])
            if not acquired:
                connection.close()
                return None
            return _PostgresLease(connection, key, lock_id)
        except BaseException:
            connection.close()
            raise
