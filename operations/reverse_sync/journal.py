from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Iterator, Sequence
from uuid import UUID

from .model import (
    JournalState,
    STATE_VERSION,
    canonical_json,
    require_nonempty,
    utc_now,
)


JOURNAL_COLUMNS = {
    "journal_meta": {"key", "value"},
    "sync_state": {"singleton", "payload"},
    "baseline_revision": {"revision_id"},
    "drain_revision": {"revision_id"},
    "applied_revision": {"revision_id"},
    "alias_reservation": {
        "entity_type", "target_uuid", "legacy_id", "reserved_at",
    },
    "journal_event": {
        "id", "event_type", "payload_sha256", "occurred_at",
    },
}
ALIAS_ENTITY_TYPES = frozenset({
    "posts",
    "platform_posts",
    "reaction_snapshots",
    "platform_snapshots",
})


class ReverseSyncJournal:
    """Separate durable state so compatibility rows do not pollute legacy data."""

    def __init__(self, path: Path):
        # ``resolve`` follows a final symlink and would make the safety check in
        # ``initialize`` ineffective.  abspath only normalizes the spelling.
        self.path = Path(os.path.abspath(path.expanduser()))

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe_paths(allow_missing=True)
        if not self.path.exists():
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.path, flags, 0o600)
            os.close(descriptor)
        self._assert_safe_paths()
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA synchronous=FULL")
            self._assert_write_pragmas(connection)
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS journal_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS baseline_revision (
                    revision_id INTEGER PRIMARY KEY CHECK(revision_id>0)
                );
                CREATE TABLE IF NOT EXISTS drain_revision (
                    revision_id INTEGER PRIMARY KEY CHECK(revision_id>0)
                );
                CREATE TABLE IF NOT EXISTS applied_revision (
                    revision_id INTEGER PRIMARY KEY CHECK(revision_id>0)
                );
                CREATE TABLE IF NOT EXISTS alias_reservation (
                    entity_type TEXT NOT NULL,
                    target_uuid TEXT NOT NULL,
                    legacy_id INTEGER NOT NULL CHECK(legacy_id>0),
                    reserved_at TEXT NOT NULL,
                    PRIMARY KEY(entity_type, target_uuid),
                    UNIQUE(entity_type, legacy_id)
                );
                CREATE TABLE IF NOT EXISTS journal_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                COMMIT;
                """
            )
            existing = connection.execute(
                "SELECT value FROM journal_meta WHERE key='schema_version'"
            ).fetchone()
            if existing is not None and int(existing[0]) != STATE_VERSION:
                raise RuntimeError("reverse-sync journal schema version is unsupported")
            connection.execute(
                """INSERT INTO journal_meta(key,value) VALUES('schema_version',?)
                   ON CONFLICT(key) DO NOTHING""",
                (str(STATE_VERSION),),
            )
            self._assert_layout(connection)
            self._assert_temporal_integrity(connection)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        self.path.chmod(0o600)
        descriptor = os.open(self.path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._assert_safe_paths()
        if write:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        else:
            uri = f"{self.path.as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            if write:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA synchronous=FULL")
                self._assert_write_pragmas(connection)
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def integrity(self) -> dict[str, Any]:
        if not self.exists:
            return {"exists": False, "quickCheck": None, "schemaVersion": None}
        with self.connect() as connection:
            self._assert_layout(connection)
            self._assert_temporal_integrity(connection)
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            row = connection.execute(
                "SELECT value FROM journal_meta WHERE key='schema_version'"
            ).fetchone()
        if quick != "ok":
            raise RuntimeError("reverse-sync journal quick_check failed")
        if journal_mode.casefold() != "wal":
            raise RuntimeError("reverse-sync journal must use WAL mode")
        version = int(row[0]) if row else None
        if version != STATE_VERSION:
            raise RuntimeError("reverse-sync journal schema version is unsupported")
        # State timestamps live inside JSON rather than typed columns, so load
        # the state as part of the integrity boundary as well.
        self.load_state()
        return {
            "exists": True,
            "quickCheck": quick,
            "schemaVersion": version,
        }

    def load_state(self) -> JournalState | None:
        if not self.exists:
            return None
        with self.connect() as connection:
            self._assert_layout(connection)
            self._assert_temporal_integrity(connection)
            row = connection.execute(
                "SELECT payload FROM sync_state WHERE singleton=1"
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
        if not isinstance(payload, dict):
            raise RuntimeError("reverse-sync journal state is malformed")
        state = JournalState(
            status=str(payload["status"]),
            source_namespace=require_nonempty(
                str(payload["sourceNamespace"]), "source namespace"
            ),
            operator=require_nonempty(str(payload["operator"]), "operator"),
            ticket=require_nonempty(str(payload["ticket"]), "ticket"),
            started_at=_datetime(payload["startedAt"]),
            rollback_deadline=_datetime(payload["rollbackDeadline"]),
            s_final_batch_id=UUID(str(payload["sFinalBatchId"])),
            s_final_source_sha256=str(payload["sFinalSourceSha256"]),
            plan_digest=payload.get("planDigest"),
            drained_at=_optional_datetime(payload.get("drainedAt")),
            verified_at=_optional_datetime(payload.get("verifiedAt")),
            stopped_at=_optional_datetime(payload.get("stoppedAt")),
        )
        if state.status not in {"active", "drained", "verified", "stopped"}:
            raise RuntimeError("reverse-sync journal state is invalid")
        if len(state.s_final_source_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in state.s_final_source_sha256
        ):
            raise RuntimeError("reverse-sync S-final digest is invalid")
        if state.plan_digest is not None and (
            len(state.plan_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in state.plan_digest
            )
        ):
            raise RuntimeError("reverse-sync plan digest is invalid")
        _validate_state(state)
        return state

    def save_state(self, state: JournalState, event_type: str) -> None:
        _validate_state(state)
        event_type = require_nonempty(event_type, "journal event type")
        payload = canonical_json(state.as_dict())
        occurred_at = _utc_now_iso("journal event timestamp")
        from .model import payload_sha256

        with self.connect(write=True) as connection:
            connection.execute(
                """INSERT INTO sync_state(singleton,payload) VALUES(1,?)
                   ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload""",
                (payload,),
            )
            connection.execute(
                """INSERT INTO journal_event(event_type,payload_sha256,occurred_at)
                   VALUES(?,?,?)""",
                (event_type, payload_sha256(state.as_dict()), occurred_at),
            )

    def bind_legacy_target(self, identity_sha256: str) -> None:
        identity = _sha256(identity_sha256, "legacy target identity")
        with self.connect(write=True) as connection:
            connection.execute(
                """INSERT INTO journal_meta(key,value)
                   VALUES('legacy_target_identity_sha256',?)
                   ON CONFLICT(key) DO NOTHING""",
                (identity,),
            )
            row = connection.execute(
                """SELECT value FROM journal_meta
                   WHERE key='legacy_target_identity_sha256'"""
            ).fetchone()
            if row is None or str(row[0]) != identity:
                raise RuntimeError("reverse-sync legacy target binding changed")

    def legacy_target_identity(self) -> str | None:
        if not self.exists:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT value FROM journal_meta
                   WHERE key='legacy_target_identity_sha256'"""
            ).fetchone()
        return None if row is None else _sha256(str(row[0]), "legacy target identity")

    def replace_revisions(self, table: str, revision_ids: Sequence[int]) -> None:
        if table not in {
            "baseline_revision", "drain_revision", "applied_revision",
        }:
            raise ValueError("invalid revision journal table")
        with self.connect(write=True) as connection:
            connection.execute(f"DELETE FROM {table}")
            connection.executemany(
                f"INSERT INTO {table}(revision_id) VALUES(?)",
                [(int(revision_id),) for revision_id in revision_ids],
            )

    def revision_ids(self, table: str) -> tuple[int, ...]:
        if table not in {
            "baseline_revision", "drain_revision", "applied_revision",
        }:
            raise ValueError("invalid revision journal table")
        if not self.exists:
            return ()
        with self.connect() as connection:
            return tuple(
                int(row[0])
                for row in connection.execute(
                    f"SELECT revision_id FROM {table} ORDER BY revision_id"
                )
            )

    def record_alias(self, entity_type: str, target_uuid: UUID, legacy_id: int) -> None:
        if entity_type not in ALIAS_ENTITY_TYPES:
            raise ValueError("invalid reverse-sync alias entity type")
        if int(legacy_id) <= 0:
            raise ValueError("reverse-sync legacy alias must be positive")
        reserved_at = _utc_now_iso("alias reservation timestamp")
        with self.connect(write=True) as connection:
            connection.execute(
                """INSERT INTO alias_reservation(
                       entity_type,target_uuid,legacy_id,reserved_at
                   ) VALUES(?,?,?,?)
                   ON CONFLICT(entity_type,target_uuid) DO NOTHING""",
                (entity_type, str(target_uuid), legacy_id, reserved_at),
            )
            row = connection.execute(
                """SELECT legacy_id,reserved_at FROM alias_reservation
                   WHERE entity_type=? AND target_uuid=?""",
                (entity_type, str(target_uuid)),
            ).fetchone()
            if row is None or int(row[0]) != int(legacy_id):
                raise RuntimeError("reverse-sync alias reservation changed identity")
            _datetime(row["reserved_at"], "alias reservation timestamp")

    def resolve_alias(self, entity_type: str, target_uuid: UUID) -> int | None:
        if entity_type not in ALIAS_ENTITY_TYPES:
            raise ValueError("invalid reverse-sync alias entity type")
        if not self.exists:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """SELECT legacy_id,reserved_at FROM alias_reservation
                   WHERE entity_type=? AND target_uuid=?""",
                (entity_type, str(target_uuid)),
            ).fetchone()
        if row is None:
            return None
        _datetime(row["reserved_at"], "alias reservation timestamp")
        return int(row["legacy_id"])

    def maximum_alias_id(self, entity_type: str) -> int:
        if entity_type not in ALIAS_ENTITY_TYPES:
            raise ValueError("invalid reverse-sync alias entity type")
        if not self.exists:
            return 0
        with self.connect() as connection:
            row = connection.execute(
                """SELECT coalesce(max(legacy_id),0) FROM alias_reservation
                   WHERE entity_type=?""",
                (entity_type,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def record_applied(self, revision_ids: Sequence[int], plan_digest: str) -> None:
        if len(plan_digest) != 64 or any(
            character not in "0123456789abcdef" for character in plan_digest
        ):
            raise ValueError("reverse-sync plan digest must be lowercase SHA-256")
        now = _utc_now_iso("applied checkpoint timestamp")
        with self.connect(write=True) as connection:
            connection.execute("DELETE FROM applied_revision")
            connection.executemany(
                "INSERT INTO applied_revision(revision_id) VALUES(?)",
                [(int(revision_id),) for revision_id in revision_ids],
            )
            connection.executemany(
                """INSERT INTO journal_meta(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (
                    ("last_applied_at", now),
                    ("last_applied_plan_digest", plan_digest),
                ),
            )
            connection.execute(
                """INSERT INTO journal_event(event_type,payload_sha256,occurred_at)
                   VALUES('applied',?,?)""",
                (plan_digest, now),
            )

    def applied_checkpoint(self) -> dict[str, Any]:
        if not self.exists:
            return {"revisionIds": (), "appliedAt": None, "planDigest": None}
        with self.connect() as connection:
            values = {
                str(row["key"]): str(row["value"])
                for row in connection.execute(
                    """SELECT key,value FROM journal_meta
                       WHERE key IN ('last_applied_at','last_applied_plan_digest')"""
                )
            }
            revisions = tuple(
                int(row[0])
                for row in connection.execute(
                    "SELECT revision_id FROM applied_revision ORDER BY revision_id"
                )
            )
        applied_at = values.get("last_applied_at")
        digest = values.get("last_applied_plan_digest")
        if (applied_at is None) != (digest is None):
            raise RuntimeError("reverse-sync applied checkpoint is incomplete")
        if applied_at is not None:
            _datetime(applied_at)
            _sha256(str(digest), "applied plan digest")
        return {
            "revisionIds": revisions,
            "appliedAt": applied_at,
            "planDigest": digest,
        }

    def _assert_safe_paths(self, *, allow_missing: bool = False) -> None:
        if _has_symlink_ancestor(self.path.parent):
            raise ValueError("reverse-sync journal path must not traverse symlinks")
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
        ):
            if candidate.is_symlink():
                raise ValueError("reverse-sync journal path must not be a symlink")
        if not self.path.exists():
            if allow_missing:
                return
            raise ValueError("reverse-sync journal does not exist")
        details = self.path.stat()
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("reverse-sync journal must be a regular file")
        if stat.S_IMODE(details.st_mode) & 0o077:
            raise PermissionError("reverse-sync journal permissions are too broad")

    @staticmethod
    def _assert_layout(connection: sqlite3.Connection) -> None:
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name NOT LIKE 'sqlite_%'"""
            )
        }
        if actual_tables != set(JOURNAL_COLUMNS):
            raise RuntimeError("reverse-sync journal table set is invalid")
        for table, expected_columns in JOURNAL_COLUMNS.items():
            actual_columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if actual_columns != expected_columns:
                raise RuntimeError("reverse-sync journal table layout is invalid")

    @staticmethod
    def _assert_write_pragmas(connection: sqlite3.Connection) -> None:
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        busy_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
        if journal_mode.casefold() != "wal":
            raise RuntimeError("reverse-sync journal must use WAL mode")
        if synchronous != 2:
            raise RuntimeError("reverse-sync journal must use FULL synchronous mode")
        if foreign_keys != 1:
            raise RuntimeError("reverse-sync journal foreign keys must be enabled")
        if busy_timeout < 30_000:
            raise RuntimeError("reverse-sync journal busy timeout is too short")

    @staticmethod
    def _assert_temporal_integrity(connection: sqlite3.Connection) -> None:
        for table, column, field in (
            ("alias_reservation", "reserved_at", "alias reservation timestamp"),
            ("journal_event", "occurred_at", "journal event timestamp"),
        ):
            for row in connection.execute(f"SELECT {column} FROM {table}"):
                _datetime(row[0], field)
        row = connection.execute(
            "SELECT value FROM journal_meta WHERE key='last_applied_at'"
        ).fetchone()
        if row is not None:
            _datetime(row[0], "applied checkpoint timestamp")


def _datetime(value: Any, field: str = "journal datetime") -> datetime:
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an ISO-8601 datetime") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if result.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")
    return result.astimezone(timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _datetime(value)


def _utc_now_iso(field: str) -> str:
    return _state_datetime(utc_now(), field).isoformat()


def _sha256(value: str, field: str) -> str:
    normalized = str(value)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise RuntimeError(f"reverse-sync {field} is invalid")
    return normalized


def _has_symlink_ancestor(path: Path) -> bool:
    candidate = path
    while candidate != candidate.parent:
        if candidate.is_symlink():
            return True
        candidate = candidate.parent
    return candidate.is_symlink()


def _validate_state(state: JournalState) -> None:
    if state.status not in {"active", "drained", "verified", "stopped"}:
        raise RuntimeError("reverse-sync journal state is invalid")
    require_nonempty(state.source_namespace, "source namespace")
    require_nonempty(state.operator, "operator")
    require_nonempty(state.ticket, "ticket")
    _sha256(state.s_final_source_sha256, "S-final digest")
    started_at = _state_datetime(state.started_at, "state started_at")
    rollback_deadline = _state_datetime(
        state.rollback_deadline, "state rollback_deadline"
    )
    if rollback_deadline <= started_at:
        raise RuntimeError("reverse-sync rollback deadline is invalid")
    timeline = (state.drained_at, state.verified_at, state.stopped_at)
    expected_presence = {
        "active": (False, False, False),
        "drained": (True, False, False),
        "verified": (True, True, False),
        "stopped": (True, True, True),
    }[state.status]
    if tuple(item is not None for item in timeline) != expected_presence:
        raise RuntimeError("reverse-sync state timestamps are incoherent")
    ordered = [
        started_at,
        *(
            _state_datetime(item, f"state {field}")
            for field, item in zip(
                ("drained_at", "verified_at", "stopped_at"), timeline
            )
            if item is not None
        ),
    ]
    if any(later < earlier for earlier, later in zip(ordered, ordered[1:])):
        raise RuntimeError("reverse-sync state timestamps are out of order")
    if state.status == "active":
        if state.plan_digest is not None:
            raise RuntimeError("active reverse-sync state has a fixed plan")
    elif state.plan_digest is None:
        raise RuntimeError("fixed reverse-sync state lacks a plan digest")
    if state.plan_digest is not None:
        _sha256(state.plan_digest, "plan digest")


def _state_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime")
    return _datetime(value, field)
