"""Durable cross-process phase arbitration for collector cycles.

The provider workers remain separate fault domains.  A short checkpoint write
announces that a logical slot is due, while a connection-scoped PostgreSQL
advisory lock protects the complete collect/normalise/persist/finalise phase.
No account transaction is kept open while provider I/O is in progress.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from threading import Lock
import time
from typing import Any, Callable, Protocol
from uuid import UUID, uuid5

from .lease import advisory_lock_key
from .model import CHECKPOINT_NAMESPACE, PARTITION_NAMESPACE, Platform, utc


PHASE_CHECKPOINT_KEY = "collector.phase.v1"
GLOBAL_PHASE_LEASE_NAME = "collector:global-phase:v1"
_PLATFORM_ORDER = {platform: index for index, platform in enumerate(Platform)}


@dataclass(frozen=True, slots=True)
class PhasePolicy:
    platform: Platform
    interval_seconds: int
    offset_seconds: int
    cycle_deadline_seconds: int

    def __post_init__(self) -> None:
        if self.interval_seconds < 1:
            raise ValueError("phase interval must be positive")
        if not 0 <= self.offset_seconds < self.interval_seconds:
            raise ValueError("phase offset must be within its interval")
        if self.cycle_deadline_seconds < 1:
            raise ValueError("cycle deadline must be positive")


@dataclass(frozen=True, slots=True)
class PhaseRequest:
    platform: Platform
    partition_key: str
    collector_version: str
    scheduled_at: datetime
    due_at: datetime
    requested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_at", utc(self.scheduled_at, "scheduled_at"))
        object.__setattr__(self, "due_at", utc(self.due_at, "due_at"))
        object.__setattr__(self, "requested_at", utc(self.requested_at, "requested_at"))
        if not self.partition_key.strip():
            raise ValueError("partition_key must not be blank")
        if not self.collector_version.strip():
            raise ValueError("collector_version must not be blank")

    @property
    def scope_id(self) -> UUID:
        return uuid5(
            PARTITION_NAMESPACE,
            f"{self.platform.value}|{self.partition_key}",
        )


@dataclass(frozen=True, slots=True)
class PhaseAcquisition:
    lease: "PhaseLease | None"
    wait_seconds: float
    attempts: int
    cancelled: bool = False
    superseded: bool = False


@dataclass(frozen=True, slots=True)
class SimulatedPhase:
    platform: Platform
    scheduled_at: datetime
    started_at: datetime
    completed_at: datetime
    coalesced_slots: int


class PhaseLease(Protocol):
    key: str

    def finish(self, status: str, completed_at: datetime) -> None:
        ...

    def release(self) -> None:
        ...

    def alive(self) -> bool:
        ...


class PhaseArbiter(Protocol):
    def request(self, request: PhaseRequest) -> bool:
        ...

    def try_acquire(
        self, request: PhaseRequest, *, stale_after_seconds: int,
    ) -> PhaseLease | None:
        ...


def scheduled_slot(
    now: datetime, interval_seconds: int, offset_seconds: int = 0,
) -> datetime:
    """Return the most recent UTC slot anchored to the Unix epoch."""
    instant = utc(now, "now")
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if not 0 <= offset_seconds < interval_seconds:
        raise ValueError("offset_seconds must be within its interval")
    epoch = int(instant.timestamp())
    anchored = epoch - ((epoch - offset_seconds) % interval_seconds)
    return datetime.fromtimestamp(anchored, tz=timezone.utc)


def due_slot(
    now: datetime,
    policy: PhasePolicy,
    last_completed_at: datetime | None,
) -> tuple[datetime | None, int, datetime]:
    """Coalesce missed periods into one logical slot.

    Returns ``(due, coalesced_count, next_due)``.  A completed slot is never
    replayed merely because a process restarted inside the same period.
    """
    current = scheduled_slot(now, policy.interval_seconds, policy.offset_seconds)
    if last_completed_at is None:
        return current, 0, current + timedelta(seconds=policy.interval_seconds)
    completed = utc(last_completed_at, "last_completed_at")
    if current <= completed:
        return None, 0, completed + timedelta(seconds=policy.interval_seconds)
    missed = max(
        0,
        int((current - completed).total_seconds()) // policy.interval_seconds - 1,
    )
    return current, missed, current + timedelta(seconds=policy.interval_seconds)


def simulate_phases(
    policies: dict[Platform, PhasePolicy],
    durations: dict[Platform, int],
    *,
    start: datetime,
    hours: int = 24,
) -> tuple[SimulatedPhase, ...]:
    """Run the production coalescing policy against a deterministic fake clock."""
    if set(policies) != set(Platform) or set(durations) != set(Platform):
        raise ValueError("simulation requires every platform")
    if hours < 1 or any(value < 1 for value in durations.values()):
        raise ValueError("simulation hours and durations must be positive")
    cursor = utc(start, "start")
    horizon = cursor + timedelta(hours=hours)
    completed: dict[Platform, datetime | None] = {
        platform: None for platform in Platform
    }
    pending: dict[Platform, tuple[datetime, datetime, int, datetime] | None] = {
        platform: None for platform in Platform
    }
    result: list[SimulatedPhase] = []
    while cursor < horizon:
        choices: list[tuple[datetime, int, Platform, datetime, int, datetime]] = []
        next_times: list[datetime] = []
        for platform, policy in policies.items():
            queued = pending[platform]
            if queued is None:
                due, coalesced, next_due = due_slot(
                    cursor, policy, completed[platform],
                )
                next_times.append(next_due)
                if due is None:
                    continue
                due_since = (
                    completed[platform] + timedelta(seconds=policy.interval_seconds)
                    if completed[platform] is not None else due
                )
                queued = (due_since, due, coalesced, next_due)
                pending[platform] = queued
            due_since, due, coalesced, next_due = queued
            choices.append((
                due_since, _PLATFORM_ORDER[platform], platform, due,
                coalesced, next_due,
            ))
        if not choices:
            cursor = min(next_times)
            continue
        _due_since, _order, platform, scheduled, coalesced, _next_due = min(choices)
        finished = cursor + timedelta(seconds=durations[platform])
        result.append(SimulatedPhase(
            platform, scheduled, cursor, finished, coalesced,
        ))
        completed[platform] = scheduled
        pending[platform] = None
        cursor = finished
    return tuple(result)


class PhaseScheduler:
    def __init__(
        self,
        arbiter: PhaseArbiter,
        *,
        max_wait_seconds: float,
        retry_seconds: float,
        request_stale_seconds: int,
    ) -> None:
        if max_wait_seconds <= 0 or retry_seconds <= 0 or request_stale_seconds <= 0:
            raise ValueError("phase wait, retry and stale values must be positive")
        self.arbiter = arbiter
        self.max_wait_seconds = float(max_wait_seconds)
        self.retry_seconds = float(retry_seconds)
        self.request_stale_seconds = int(request_stale_seconds)

    async def acquire(
        self,
        request: PhaseRequest,
        stop: asyncio.Event | None = None,
    ) -> PhaseAcquisition:
        began = time.monotonic()
        attempts = 0
        while True:
            if stop is not None and stop.is_set():
                return PhaseAcquisition(None, time.monotonic() - began, attempts, True)
            attempts += 1
            heartbeat = PhaseRequest(
                request.platform,
                request.partition_key,
                request.collector_version,
                request.scheduled_at,
                request.due_at,
                datetime.now(timezone.utc),
            )
            accepted = await asyncio.to_thread(self.arbiter.request, heartbeat)
            if not accepted:
                return PhaseAcquisition(
                    None, time.monotonic() - began, attempts,
                    superseded=True,
                )
            # Give simultaneously restarted workers one bounded announcement
            # window before choosing the earliest due request.  Without this,
            # whichever process reaches PostgreSQL first wins even when another
            # already-due platform has an earlier logical slot.
            if attempts == 1:
                delay = min(self.retry_seconds, self.max_wait_seconds)
                if stop is None:
                    await asyncio.sleep(delay)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=delay)
                        return PhaseAcquisition(
                            None, time.monotonic() - began, attempts, True,
                        )
                    except TimeoutError:
                        pass
            lease = await asyncio.to_thread(
                self.arbiter.try_acquire,
                heartbeat,
                stale_after_seconds=self.request_stale_seconds,
            )
            if lease is not None:
                return PhaseAcquisition(lease, time.monotonic() - began, attempts)
            elapsed = time.monotonic() - began
            if elapsed >= self.max_wait_seconds:
                return PhaseAcquisition(None, elapsed, attempts)
            delay = min(self.retry_seconds, self.max_wait_seconds - elapsed)
            if stop is None:
                await asyncio.sleep(delay)
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                continue


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row_value(row: Any, name: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[name]
    return row[index]


class _PostgresPhaseLease:
    def __init__(
        self,
        connection: Any,
        request: PhaseRequest,
        lock_id: int,
    ) -> None:
        self.connection = connection
        self.request = request
        self.lock_id = lock_id
        self.key = GLOBAL_PHASE_LEASE_NAME
        self._released = False

    def alive(self) -> bool:
        if self._released:
            return False
        try:
            row = self.connection.execute(
                """SELECT EXISTS (
                       SELECT 1
                         FROM pg_locks
                        WHERE locktype='advisory'
                          AND classid=((%s::bigint >> 32) & 4294967295)::oid
                          AND objid=(%s::bigint & 4294967295)::oid
                          AND objsubid=1
                          AND pid=pg_backend_pid()
                          AND granted
                   )""",
                (self.lock_id, self.lock_id),
            ).fetchone()
            return bool(
                next(iter(row.values())) if isinstance(row, dict) else row[0]
            )
        except BaseException:
            return False

    def finish(self, status: str, completed_at: datetime) -> None:
        if self._released:
            return
        completed = utc(completed_at, "completed_at")
        value = {
            "state": "completed",
            "status": str(status),
            "completed_at": completed.isoformat(),
            "last_completed_scheduled_at": self.request.scheduled_at.isoformat(),
        }
        self.connection.execute(
            """UPDATE ops_and_admin.operational_checkpoint
                  SET value=value || %s::jsonb,
                      source_observed_at=%s,
                      updated_at=transaction_timestamp()
                WHERE checkpoint_key=%s AND scope_type='platform'
                  AND scope_id=%s AND platform=%s""",
            (
                _json(value), self.request.scheduled_at, PHASE_CHECKPOINT_KEY,
                self.request.scope_id, self.request.platform.value,
            ),
        )

    def release(self) -> None:
        if self._released:
            return
        try:
            self.connection.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
        finally:
            self.connection.close()
            self._released = True


class PostgresPhaseArbiter:
    """Fair, durable request queue plus a session-scoped global phase lock."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        if connection_factory is None and not dsn:
            raise ValueError("dsn or connection_factory is required")
        self._factory = connection_factory or self._psycopg_factory(str(dsn))
        self._lock_id = advisory_lock_key(GLOBAL_PHASE_LEASE_NAME)
        self._connection: Any | None = None
        self._lease_connection: Any | None = None
        self._connection_lock = Lock()

    @staticmethod
    def _psycopg_factory(dsn: str) -> Callable[[], Any]:
        def connect() -> Any:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - packaging guard
                raise RuntimeError("psycopg is required for phase arbitration") from exc
            return psycopg.connect(dsn, autocommit=True, connect_timeout=5)

        return connect

    def _open_connection(self) -> Any:
        connection = self._factory()
        try:
            connection.execute("SET TIME ZONE 'UTC'")
            connection.execute("SET statement_timeout='5s'")
            connection.execute("SET lock_timeout='1s'")
            return connection
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _is_connection_error(error: BaseException, connection: Any | None) -> bool:
        if isinstance(error, (ConnectionError, OSError)):
            return True
        if connection is not None and bool(getattr(connection, "closed", False)):
            return True
        try:
            import psycopg
        except ImportError:  # pragma: no cover - optional dependency guard
            return False
        return isinstance(error, (psycopg.InterfaceError, psycopg.OperationalError))

    @staticmethod
    def _close_connection(connection: Any | None) -> None:
        if connection is None:
            return
        try:
            connection.close()
        except BaseException:
            pass

    def _run_reusing(self, operation: Callable[[Any], Any]) -> Any:
        with self._connection_lock:
            for attempt in range(2):
                connection = self._connection
                try:
                    if connection is None or bool(getattr(connection, "closed", False)):
                        connection = self._open_connection()
                        self._connection = connection
                    return operation(connection)
                except BaseException as error:
                    connection_error = self._is_connection_error(error, connection)
                    if connection_error:
                        self._close_connection(connection)
                        self._connection = None
                    if not connection_error or attempt:
                        raise
        raise AssertionError("unreachable")

    def close(self) -> None:
        with self._connection_lock:
            connection = self._connection
            lease_connection = self._lease_connection
            self._connection = None
            self._lease_connection = None
            self._close_connection(connection)
            self._close_connection(lease_connection)

    @staticmethod
    def _contender(connection: Any, cutoff: datetime) -> Any:
        return connection.execute(
            """SELECT platform::text, scope_id,
                      value->>'partition_key' AS partition_key,
                      (value->>'scheduled_at')::timestamptz AS scheduled_at,
                      (value->>'due_at')::timestamptz AS due_at
                 FROM ops_and_admin.operational_checkpoint
                WHERE checkpoint_key=%s AND scope_type='platform'
                  AND value->>'state'='requested'
                  AND updated_at >= %s
                ORDER BY (value->>'due_at')::timestamptz,
                         CASE platform
                           WHEN 'telegram' THEN 0
                           WHEN 'vk' THEN 1
                           WHEN 'max' THEN 2
                           WHEN 'rutube' THEN 3
                           ELSE 99
                         END,
                         value->>'partition_key'
                LIMIT 1""",
            (PHASE_CHECKPOINT_KEY, cutoff),
        ).fetchone()

    @staticmethod
    def _is_selected(contender: Any, request: PhaseRequest) -> bool:
        return contender is not None and (
            str(_row_value(contender, "platform", 0)) == request.platform.value
            and _row_value(contender, "scope_id", 1) == request.scope_id
            and str(_row_value(contender, "partition_key", 2))
            == request.partition_key
            and utc(_row_value(contender, "scheduled_at", 3), "scheduled_at")
            == request.scheduled_at
            and utc(_row_value(contender, "due_at", 4), "due_at")
            == request.due_at
        )

    def request(self, request: PhaseRequest) -> bool:
        value = {
            "state": "requested",
            "partition_key": request.partition_key,
            "collector_version": request.collector_version,
            "scheduled_at": request.scheduled_at.isoformat(),
            "due_at": request.due_at.isoformat(),
            "requested_at": request.requested_at.isoformat(),
        }
        checkpoint_id = uuid5(
            CHECKPOINT_NAMESPACE,
            f"{PHASE_CHECKPOINT_KEY}|platform|{request.scope_id}",
        )

        def write(connection: Any) -> bool:
            row = connection.execute(
                """INSERT INTO ops_and_admin.operational_checkpoint(
                       id, checkpoint_key, scope_type, scope_id, platform, value,
                       source_observed_at
                   ) VALUES (%s,%s,'platform',%s,%s,%s::jsonb,%s)
                   ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
                   DO UPDATE SET
                       value=ops_and_admin.operational_checkpoint.value || excluded.value,
                       source_observed_at=excluded.source_observed_at,
                       updated_at=transaction_timestamp()
                   WHERE (
                       ops_and_admin.operational_checkpoint.value
                           ->>'last_completed_scheduled_at' IS NULL
                       OR (
                           ops_and_admin.operational_checkpoint.value
                               ->>'last_completed_scheduled_at'
                       )::timestamptz < excluded.source_observed_at
                   )
                   RETURNING id""",
                (
                    checkpoint_id, PHASE_CHECKPOINT_KEY, request.scope_id,
                    request.platform.value, _json(value), request.scheduled_at,
                ),
            ).fetchone()
            return row is not None

        return bool(self._run_reusing(write))

    def try_acquire(
        self, request: PhaseRequest, *, stale_after_seconds: int,
    ) -> _PostgresPhaseLease | None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be positive")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        contender = self._run_reusing(
            lambda connection: self._contender(connection, cutoff)
        )
        if not self._is_selected(contender, request):
            return None

        for attempt in range(2):
            connection = self._lease_connection
            try:
                if connection is None or bool(getattr(connection, "closed", False)):
                    connection = self._open_connection()
                    self._lease_connection = connection
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(%s)", (self._lock_id,),
                ).fetchone()
                acquired = bool(
                    next(iter(row.values())) if isinstance(row, dict) else row[0]
                )
                if not acquired:
                    return None
                contender = self._contender(connection, cutoff)
                if not self._is_selected(contender, request):
                    connection.execute(
                        "SELECT pg_advisory_unlock(%s)", (self._lock_id,),
                    )
                    return None
                active = {
                    "state": "active",
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                }
                connection.execute(
                    """UPDATE ops_and_admin.operational_checkpoint
                          SET value=value || %s::jsonb,
                              updated_at=transaction_timestamp()
                        WHERE checkpoint_key=%s AND scope_type='platform'
                          AND scope_id=%s AND platform=%s""",
                    (
                        _json(active), PHASE_CHECKPOINT_KEY, request.scope_id,
                        request.platform.value,
                    ),
                )
                self._lease_connection = None
                return _PostgresPhaseLease(connection, request, self._lock_id)
            except BaseException as error:
                self._close_connection(connection)
                self._lease_connection = None
                if not self._is_connection_error(error, connection) or attempt:
                    raise
        raise AssertionError("unreachable")


class _MemoryPhaseLease:
    def __init__(
        self, arbiter: "InMemoryPhaseArbiter", request: PhaseRequest,
    ) -> None:
        self.arbiter = arbiter
        self.request = request
        self.key = GLOBAL_PHASE_LEASE_NAME
        self._released = False

    def alive(self) -> bool:
        return not self._released and self.arbiter.active == self.request

    def finish(self, status: str, completed_at: datetime) -> None:
        completed = utc(completed_at, "completed_at")
        with self.arbiter._lock:
            self.arbiter.completed.append((self.request, status, completed))
            self.arbiter.last_completed[
                (self.request.platform, self.request.partition_key)
            ] = self.request.scheduled_at

    def release(self) -> None:
        if self._released:
            return
        with self.arbiter._lock:
            if self.arbiter.active == self.request:
                self.arbiter.active = None
        self._released = True


class InMemoryPhaseArbiter:
    """Deterministic phase arbiter for fake-clock and concurrency tests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.requests: dict[tuple[Platform, str], PhaseRequest] = {}
        self.active: PhaseRequest | None = None
        self.completed: list[tuple[PhaseRequest, str, datetime]] = []
        self.last_completed: dict[tuple[Platform, str], datetime] = {}

    def request(self, request: PhaseRequest) -> bool:
        with self._lock:
            key = (request.platform, request.partition_key)
            completed = self.last_completed.get(key)
            if completed is not None and request.scheduled_at <= completed:
                return False
            self.requests[(request.platform, request.partition_key)] = request
            return True

    def try_acquire(
        self, request: PhaseRequest, *, stale_after_seconds: int,
    ) -> _MemoryPhaseLease | None:
        cutoff = request.requested_at - timedelta(seconds=stale_after_seconds)
        with self._lock:
            if self.active is not None:
                return None
            contenders = [
                item for item in self.requests.values()
                if item.requested_at >= cutoff
            ]
            if not contenders:
                return None
            selected = min(
                contenders,
                key=lambda item: (
                    item.due_at,
                    _PLATFORM_ORDER[item.platform],
                    item.partition_key,
                ),
            )
            if selected != request:
                return None
            self.requests.pop((request.platform, request.partition_key), None)
            self.active = request
            return _MemoryPhaseLease(self, request)
