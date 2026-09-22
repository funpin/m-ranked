"""Серверные сессии админки и одноразовость TOTP — состояние живёт в базе.

Хранится только SHA-256 от случайного токена в 256 бит: равномерный секрет
такой длины не подбирают перебором прообраза, поэтому соль и KDF здесь ничего
не добавили бы, а чтение таблицы всё равно не даёт входа.

Код второго фактора тратится ровно один раз и ровно при создании сессии.
Учёт кодов и сессий лежит в базе, а не в памяти процесса: иначе перезапуск
или второй воркер обнуляли бы и защиту от повтора, и отзыв доступа.
"""
from __future__ import annotations

import hashlib
import math
import os
import time
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

SESSION_TOKEN_BYTES = 32
SESSION_COOKIE = "__Host-mranked-admin"
PURGE_INTERVAL_SECONDS = 3600

_CONSUME_CODE_AND_OPEN = """
WITH code AS (
    INSERT INTO ops_and_admin.admin_totp_use AS use (subject, totp_counter, consumed_at)
         VALUES (%(subject)s, %(counter)s, %(now)s)
    ON CONFLICT (subject, totp_counter) DO UPDATE SET consumed_at = %(now)s
          WHERE use.consumed_at IS NULL AND use.failures < %(attempts)s
      RETURNING subject
)
INSERT INTO ops_and_admin.admin_session
            (token_digest, subject, roles, auth_strength, source_digest,
             idle_expires_at, absolute_expires_at)
     SELECT %(digest)s, %(subject)s, %(roles)s, 'password_totp', %(source)s,
            %(now)s::timestamptz + %(idle)s * interval '1 second',
            %(now)s::timestamptz + %(absolute)s * interval '1 second'
       FROM code
  RETURNING id, subject, roles, idle_expires_at, absolute_expires_at
"""

# Стенд без второго фактора: тратить нечего, поэтому учёт кодов не трогается.
_OPEN_WITHOUT_CODE = """
INSERT INTO ops_and_admin.admin_session
            (token_digest, subject, roles, auth_strength, source_digest,
             idle_expires_at, absolute_expires_at)
     VALUES (%(digest)s, %(subject)s, %(roles)s, 'password_only', %(source)s,
             %(now)s::timestamptz + %(idle)s * interval '1 second',
             %(now)s::timestamptz + %(absolute)s * interval '1 second')
  RETURNING id, subject, roles, idle_expires_at, absolute_expires_at
"""

_RECORD_CODE_FAILURE = """
INSERT INTO ops_and_admin.admin_totp_use AS use (subject, totp_counter, failures)
     VALUES (%(subject)s, %(counter)s, 1)
ON CONFLICT (subject, totp_counter)
  DO UPDATE SET failures = least(use.failures + 1, 1000)
"""

# Просроченная, отозванная или незнакомая сессия одинаково не возвращает строку,
# поэтому все три случая неотличимы и для вызывающего, и для клиента.
_TOUCH = """
UPDATE ops_and_admin.admin_session
   SET last_seen_at = %(now)s,
       idle_expires_at = least(%(now)s::timestamptz + %(idle)s * interval '1 second',
                               absolute_expires_at)
 WHERE token_digest = %(digest)s AND revoked_at IS NULL
   AND idle_expires_at > %(now)s AND absolute_expires_at > %(now)s
 RETURNING id, subject, roles, idle_expires_at, absolute_expires_at
"""

_REVOKE_ONE = """
UPDATE ops_and_admin.admin_session SET revoked_at = %(now)s, revoked_reason = %(reason)s
 WHERE id = %(id)s AND revoked_at IS NULL RETURNING id
"""

_REVOKE_SUBJECT = """
UPDATE ops_and_admin.admin_session SET revoked_at = %(now)s, revoked_reason = %(reason)s
 WHERE subject = %(subject)s AND revoked_at IS NULL RETURNING id
"""

_READ_FAILURES = """
SELECT failures, window_started_at, last_failure_at
  FROM ops_and_admin.admin_login_failure WHERE source_digest = %(source)s
"""

_RECORD_FAILURE = """
INSERT INTO ops_and_admin.admin_login_failure AS row
            (source_digest, failures, window_started_at, last_failure_at)
     VALUES (%(source)s, 1, %(now)s, %(now)s)
ON CONFLICT (source_digest) DO UPDATE
   SET failures = CASE WHEN row.window_started_at > %(horizon)s
                       THEN least(row.failures + 1, 1000000) ELSE 1 END,
       window_started_at = CASE WHEN row.window_started_at > %(horizon)s
                                THEN row.window_started_at ELSE %(now)s END,
       last_failure_at = %(now)s
"""

_CLEAR_FAILURES = "DELETE FROM ops_and_admin.admin_login_failure WHERE source_digest = %(source)s"

# Уборка считает срок по часам самой базы: подменённые часы приложения не
# должны уметь стереть ещё живой учёт кодов или сессию.
_PURGE = """
WITH dead_sessions AS (
    DELETE FROM ops_and_admin.admin_session
          WHERE absolute_expires_at < transaction_timestamp() - interval '1 day'
             OR (revoked_at IS NOT NULL
                 AND revoked_at < transaction_timestamp() - interval '1 day')
), dead_codes AS (
    DELETE FROM ops_and_admin.admin_totp_use
          WHERE created_at < transaction_timestamp() - interval '1 hour'
)
DELETE FROM ops_and_admin.admin_login_failure
      WHERE last_failure_at < transaction_timestamp() - interval '1 day'
"""


def _bounded(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} должен быть в диапазоне {low}..{high}, получено {value}")
    return value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionPolicy:
    """Границы жизни сессии и перебора. Значения проверяются при старте."""

    idle_seconds: int = 1800
    absolute_seconds: int = 28800
    code_attempts: int = 5
    address_failures: int = 25
    address_window_seconds: int = 900
    address_base_seconds: int = 30
    address_max_seconds: int = 900

    @classmethod
    def from_environment(cls) -> "SessionPolicy":
        policy = cls(
            idle_seconds=_bounded("ADMIN_SESSION_IDLE_SECONDS", 1800, 300, 3600),
            absolute_seconds=_bounded("ADMIN_SESSION_ABSOLUTE_SECONDS", 28800, 900, 28800),
            code_attempts=_bounded("ADMIN_TOTP_ATTEMPTS", 5, 1, 20),
            address_failures=_bounded("ADMIN_LOGIN_ADDRESS_FAILURES", 25, 5, 1000),
        )
        if policy.idle_seconds > policy.absolute_seconds:
            raise ValueError("ADMIN_SESSION_IDLE_SECONDS не может превышать абсолютный срок")
        return policy


@dataclass(frozen=True)
class SessionRecord:
    id: uuid.UUID
    subject: str
    roles: frozenset[str]
    idle_expires_at: datetime
    absolute_expires_at: datetime


def _record(row: dict[str, Any]) -> SessionRecord:
    return SessionRecord(row["id"], row["subject"], frozenset(row["roles"]),
                         row["idle_expires_at"], row["absolute_expires_at"])


class SessionStore:
    def __init__(self, database: Any, policy: SessionPolicy,
                 clock: Callable[[], float] = time.time) -> None:
        self.database = database
        self.policy = policy
        # Часы вынесены наружу: тест сдвигает их вместо ожидания в реальном
        # времени, и проверки сроков перестают зависеть от секундомера.
        self.clock = clock
        self._purged = 0.0

    def _now(self, now: datetime | None) -> datetime:
        return now or datetime.fromtimestamp(self.clock(), timezone.utc)

    async def open(self, subject: str, roles: frozenset[str], counter: int | None,
                   source: str, now: datetime | None = None) -> tuple[str, SessionRecord] | None:
        """Потратить код и открыть сессию одним оператором.

        Из двух одновременных входов с одним кодом строку получит ровно один:
        второй увидит уже потраченный код и не создаст сессию. Счётчик None
        означает стенд без второго фактора — там тратить нечего.
        """
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        moment = self._now(now)
        values = {
            "subject": subject, "counter": counter, "now": moment,
            "attempts": self.policy.code_attempts, "digest": digest(token),
            "roles": sorted(roles), "source": digest(source),
            "idle": self.policy.idle_seconds, "absolute": self.policy.absolute_seconds,
        }
        statement = _CONSUME_CODE_AND_OPEN if counter is not None else _OPEN_WITHOUT_CODE
        row = await self.database.admin_fetch_one(statement, values)
        return (token, _record(row)) if row else None

    async def record_code_failure(self, subject: str, counter: int) -> None:
        await self.database.admin_execute(_RECORD_CODE_FAILURE,
                                          {"subject": subject, "counter": counter})

    async def resolve(self, token: str, now: datetime | None = None) -> SessionRecord | None:
        if not token or len(token) > 512:
            return None
        row = await self.database.admin_fetch_one(_TOUCH, {
            "digest": digest(token), "now": self._now(now),
            "idle": self.policy.idle_seconds,
        })
        return _record(row) if row else None

    async def revoke(self, session_id: uuid.UUID, reason: str,
                     now: datetime | None = None) -> bool:
        row = await self.database.admin_fetch_one(
            _REVOKE_ONE, {"id": session_id, "reason": reason, "now": self._now(now)})
        return row is not None

    async def revoke_subject(self, subject: str, reason: str,
                             now: datetime | None = None) -> int:
        rows = await self.database.admin_fetch_all(
            _REVOKE_SUBJECT, {"subject": subject, "reason": reason, "now": self._now(now)})
        return len(rows)

    async def retry_after(self, source: str, now: datetime | None = None) -> int:
        """Замедление считается по адресу источника, не по учётной записи."""
        moment = self._now(now)
        row = await self.database.admin_fetch_one(_READ_FAILURES, {"source": digest(source)})
        if row is None:
            return 0
        window = (moment-row["window_started_at"]).total_seconds()
        if window > self.policy.address_window_seconds:
            return 0
        excess = row["failures"]-self.policy.address_failures
        if excess < 0:
            return 0
        delay = min(self.policy.address_max_seconds,
                    self.policy.address_base_seconds*2**excess)
        remaining = (row["last_failure_at"]-moment).total_seconds()+delay
        return max(0, math.ceil(remaining))

    async def record_failure(self, source: str, now: datetime | None = None) -> None:
        moment = self._now(now)
        await self.database.admin_execute(_RECORD_FAILURE, {
            "source": digest(source), "now": moment,
            "horizon": moment-timedelta(seconds=self.policy.address_window_seconds),
        })

    async def clear_failures(self, source: str) -> None:
        await self.database.admin_execute(_CLEAR_FAILURES, {"source": digest(source)})

    async def purge(self, now: datetime | None = None) -> None:
        await self.database.admin_execute(_PURGE)

    async def maybe_purge(self, now: datetime | None = None) -> None:
        """Уборка редких строк идёт по ходу входа, отдельного задания не заводим."""
        moment = time.monotonic()
        if moment-self._purged < PURGE_INTERVAL_SECONDS:
            return
        self._purged = moment
        await self.purge(now)
