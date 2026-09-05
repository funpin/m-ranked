from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from typing import Any, Iterator, Mapping, Sequence
from uuid import UUID

from app.analytics import delta_by_reaction
from app.telegram_identity import parse_telegram_external_id
from migration.bridge.normalize import access_mode
from migration.reverse_sync_format import (
    ReversePublicationEnvelope,
    ReverseSnapshotEnvelope,
    add_reverse_publication_envelope,
    parse_reverse_publication_envelope,
    parse_reverse_snapshot_envelope,
)

from .model import SyncPlan, canonical_json, canonical_value, payload_sha256


LEGACY_SCHEMA_VERSION = 15
SUPPORTED_QUALITIES = frozenset({
    "unknown",
    "rounded",
    "estimated",
    "exact",
    "degraded",
    "suspected_reset",
})
TERMINAL_RUN_STATUSES = frozenset({
    "succeeded", "partial", "failed", "skipped", "cancelled",
})
REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
    "institutions": frozenset({"id", "name", "short_name", "created_at"}),
    "platform_accounts": frozenset({
        "id", "institution_id", "platform", "external_key", "native_id",
        "username", "title", "url", "enabled", "access_mode", "data_quality",
        "subscriber_count", "subscriber_count_display", "subscriber_measured_at",
        "last_checked_at", "last_error", "added_at",
    }),
    "channels": frozenset({
        "id", "telegram_id", "username", "title", "enabled", "added_at",
        "last_seen_message_id", "last_checked_at", "last_error",
        "subscriber_count", "subscriber_count_display", "subscriber_measured_at",
        "institution_id", "platform_account_id",
    }),
    "posts": frozenset({
        "id", "channel_id", "logical_key", "telegram_message_id",
        "telegram_grouped_id", "published_at", "discovered_at",
        "first_observation_age_seconds", "history_complete",
        "history_forced_incomplete", "baseline_from_publication", "post_type",
        "ambiguous_album_reactions", "is_repost", "deleted_at",
        "missing_check_count", "missing_last_checked_at", "missing_reason",
        "created_at",
    }),
    "post_messages": frozenset({"post_id", "telegram_message_id"}),
    "reaction_snapshots": frozenset({
        "id", "post_id", "measured_at", "measurement_bucket", "age_seconds",
        "total_reactions", "reactions_json", "raw_state_json", "delta_total",
        "delta_by_reaction_json", "delta_seconds", "rate_per_hour",
        "interval_uncertain", "spike", "comments_count", "delta_comments",
        "views_count", "delta_views", "synthetic", "created_at",
    }),
    "platform_posts": frozenset({
        "id", "platform_account_id", "external_id", "published_at",
        "discovered_at", "post_type", "url", "deleted_at",
        "missing_check_count", "missing_last_checked_at", "missing_reason",
        "raw_json", "history_complete", "history_forced_incomplete",
        "source_external_id", "is_joint", "additional_author_count", "is_repost",
        "created_at",
    }),
    "platform_snapshots": frozenset({
        "id", "platform_post_id", "measured_at", "measurement_bucket",
        "age_seconds", "views_count", "reactions_count", "comments_count",
        "shares_count", "raw_json", "created_at",
    }),
    "app_state": frozenset({"key", "value"}),
    "schema_migrations": frozenset({"version", "applied_at"}),
}


class LegacySqliteTarget:
    """Strict compatibility writer for the frozen schema-v15 legacy database."""

    def __init__(
        self,
        path: Path,
        source_namespace: str,
        *,
        min_free_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.path = Path(os.path.abspath(path.expanduser()))
        self.source_namespace = str(source_namespace).strip()
        self.min_free_bytes = int(min_free_bytes)
        if not self.source_namespace:
            raise ValueError("source namespace must not be blank")
        if self.min_free_bytes < 0:
            raise ValueError("minimum free bytes must not be negative")

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._assert_safe_paths()
        if write:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        else:
            connection = sqlite3.connect(
                f"{self.path.as_uri()}?mode=ro", uri=True, timeout=5,
            )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            if write:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write and connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def preflight(self) -> dict[str, Any]:
        self._assert_safe_paths()
        try:
            details = self.path.stat()
        except FileNotFoundError as error:
            raise ValueError("legacy SQLite database does not exist") from error
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("legacy SQLite path must be a regular file")
        if not os.access(self.path, os.R_OK | os.W_OK):
            raise PermissionError("legacy SQLite database must be readable and writable")
        required_free = max(self.min_free_bytes, details.st_size * 2)
        available = shutil.disk_usage(self.path.parent).free
        if available < required_free:
            raise RuntimeError("legacy SQLite durability capacity gate failed")
        with self.connect() as connection:
            version = self._schema_version(connection)
            if version != LEGACY_SCHEMA_VERSION:
                raise RuntimeError(
                    f"legacy SQLite schema must be version {LEGACY_SCHEMA_VERSION}"
                )
            for table, required in REQUIRED_COLUMNS.items():
                actual = {
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                missing = required - actual
                if missing:
                    raise RuntimeError(
                        f"legacy SQLite table {table} lacks required columns"
                    )
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            violations = tuple(connection.execute("PRAGMA foreign_key_check"))
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        if quick_check != "ok":
            raise RuntimeError("legacy SQLite quick_check failed")
        if violations:
            raise RuntimeError("legacy SQLite foreign-key check failed")
        if journal_mode.casefold() != "wal":
            raise RuntimeError("legacy SQLite database must use WAL mode")
        return {
            "schemaVersion": version,
            "quickCheck": quick_check,
            "foreignKeyViolations": 0,
            "journalMode": journal_mode.casefold(),
            "sizeBytes": details.st_size,
            "freeBytes": available,
            "identitySha256": self.identity(),
        }

    def identity(self) -> str:
        """Bind a journal to one file instance and its immutable baseline rows."""

        self._assert_safe_paths()
        try:
            details = self.path.stat()
        except FileNotFoundError as error:
            raise ValueError("legacy SQLite database does not exist") from error
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("legacy SQLite path must be a regular file")
        with self.connect() as connection:
            schema_version = self._schema_version(connection)
            migrations = [
                {"version": int(row["version"]), "appliedAt": row["applied_at"]}
                for row in connection.execute(
                    "SELECT version,applied_at FROM schema_migrations ORDER BY version"
                )
            ]
            institutions = [
                {
                    "id": int(row["id"]),
                    "name": str(row["name"]),
                    "shortName": row["short_name"],
                    "createdAt": row["created_at"],
                }
                for row in connection.execute(
                    """SELECT id,name,short_name,created_at
                       FROM institutions ORDER BY id"""
                )
            ]
            schema = [
                {"type": str(row["type"]), "name": str(row["name"]), "sql": row["sql"]}
                for row in connection.execute(
                    """SELECT type,name,sql FROM sqlite_master
                       WHERE name NOT LIKE 'sqlite_%'
                       ORDER BY type,name"""
                )
            ]
        return payload_sha256({
            "absolutePath": str(self.path),
            "device": int(details.st_dev),
            "inode": int(details.st_ino),
            "schemaVersion": schema_version,
            "schemaMigrations": migrations,
            "institutions": institutions,
            "schema": schema,
        })

    def _assert_safe_paths(self) -> None:
        if _has_symlink_ancestor(self.path.parent):
            raise ValueError("legacy SQLite path must not traverse symlinks")
        for candidate in (
            self.path,
            Path(f"{self.path}-wal"),
            Path(f"{self.path}-shm"),
            Path(f"{self.path}-journal"),
            self.path.with_name(f".{self.path.name}.reverse-sync.lock"),
        ):
            if candidate.is_symlink():
                raise ValueError("legacy SQLite paths must not be symlinks")

    def maximum_legacy_ids(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "posts": int(
                    connection.execute("SELECT coalesce(max(id),0) FROM posts").fetchone()[0]
                ),
                "platform_posts": int(
                    connection.execute(
                        "SELECT coalesce(max(id),0) FROM platform_posts"
                    ).fetchone()[0]
                ),
                "reaction_snapshots": int(
                    connection.execute(
                        "SELECT coalesce(max(id),0) FROM reaction_snapshots"
                    ).fetchone()[0]
                ),
                "platform_snapshots": int(
                    connection.execute(
                        "SELECT coalesce(max(id),0) FROM platform_snapshots"
                    ).fetchone()[0]
                ),
            }

    def apply(
        self,
        plan: SyncPlan,
        aliases: Mapping[UUID, tuple[str, int]],
    ) -> dict[str, int]:
        affected_telegram_posts: set[int] = set()
        with self.connect(write=True) as connection:
            self._assert_schema(connection)
            for account in plan.accounts:
                self._apply_account(connection, account)
            for publication in plan.publications:
                target_id = UUID(str(publication["id"]))
                alias = aliases.get(target_id)
                if alias is None:
                    raise RuntimeError("publication is missing a reserved legacy alias")
                if publication["platform"] == "telegram":
                    if alias[0] != "posts":
                        raise RuntimeError("Telegram publication has the wrong alias type")
                    affected_telegram_posts.add(
                        self._apply_telegram_publication(
                            connection, publication, int(alias[1])
                        )
                    )
                else:
                    if alias[0] != "platform_posts":
                        raise RuntimeError("platform publication has the wrong alias type")
                    self._apply_platform_publication(
                        connection, publication, int(alias[1])
                    )
            for snapshot in plan.snapshots:
                publication_id = UUID(str(snapshot["publication_id"]))
                alias = aliases.get(publication_id)
                if alias is None:
                    raise RuntimeError("snapshot publication is missing a legacy alias")
                if snapshot["platform"] == "telegram":
                    if alias[0] != "posts":
                        raise RuntimeError("Telegram snapshot has the wrong alias type")
                    self._apply_telegram_snapshot(connection, snapshot, int(alias[1]))
                    affected_telegram_posts.add(int(alias[1]))
                else:
                    if alias[0] != "platform_posts":
                        raise RuntimeError("platform snapshot has the wrong alias type")
                    self._apply_platform_snapshot(connection, snapshot, int(alias[1]))
            for post_id in sorted(affected_telegram_posts):
                self._recalculate_telegram_deltas(connection, post_id)
            self._apply_collection_state(connection, plan.collection_runs)
            violations = tuple(connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError("reverse-sync introduced a foreign-key violation")
            self._verify_connection(connection, plan, aliases)
        return plan.counts()

    def verify(
        self,
        plan: SyncPlan,
        aliases: Mapping[UUID, tuple[str, int]],
    ) -> dict[str, Any]:
        with self.connect() as connection:
            self._assert_schema(connection)
            self._verify_connection(connection, plan, aliases)
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            violations = tuple(connection.execute("PRAGMA foreign_key_check"))
        if quick != "ok" or violations:
            raise RuntimeError("legacy SQLite integrity verification failed")
        return {
            "quickCheck": quick,
            "foreignKeyViolations": 0,
            "counts": plan.counts(),
            "canonicalPlanSha256": plan.digest,
        }

    def durability_barrier(self) -> dict[str, int]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA synchronous=FULL")
            busy, log_frames, checkpointed = connection.execute(
                "PRAGMA wal_checkpoint(FULL)"
            ).fetchone()
        finally:
            connection.close()
        if int(busy) != 0 or int(checkpointed) != int(log_frames):
            raise RuntimeError("legacy SQLite WAL checkpoint did not fully drain")
        for candidate in (self.path, self.path.with_name(f"{self.path.name}-wal")):
            if candidate.exists():
                descriptor = os.open(candidate, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"walFrames": int(log_frames), "checkpointedFrames": int(checkpointed)}

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _assert_schema(self, connection: sqlite3.Connection) -> None:
        if self._schema_version(connection) != LEGACY_SCHEMA_VERSION:
            raise RuntimeError("legacy SQLite schema changed after preflight")

    def _apply_account(
        self, connection: sqlite3.Connection, account: Mapping[str, Any]
    ) -> None:
        platform = str(account["platform"])
        institution_legacy_id = _positive(account.get("institution_legacy_id"), "institution alias")
        account_legacy_id = _positive(account.get("account_legacy_id"), "account alias")
        institution = connection.execute(
            "SELECT * FROM institutions WHERE id=?", (institution_legacy_id,)
        ).fetchone()
        legacy_account = connection.execute(
            "SELECT * FROM platform_accounts WHERE id=?", (account_legacy_id,)
        ).fetchone()
        if institution is None or legacy_account is None:
            raise RuntimeError("S-final account alias does not resolve in legacy SQLite")
        if (
            str(institution["name"]).strip() != str(account["institution_name"]).strip()
            or _optional_text(institution["short_name"])
            != _optional_text(account.get("institution_short_name"))
        ):
            raise RuntimeError("institution metadata changed during rollback window")
        if (
            int(legacy_account["institution_id"]) != institution_legacy_id
            or str(legacy_account["platform"]) != platform
            or bool(legacy_account["enabled"]) != bool(account["enabled"])
            or access_mode(platform, legacy_account["access_mode"])
            != str(account["access_mode"])
        ):
            raise RuntimeError("administrative account fields changed during rollback window")
        self._assert_canonical_account_identity(legacy_account, account)
        quality = account.get("subscriber_quality")
        if quality is not None and str(quality) not in SUPPORTED_QUALITIES:
            raise RuntimeError("account observation quality is not representable")
        values: dict[str, Any] = {}
        for target_key, legacy_key in (
            ("native_external_id", "native_id"),
            ("current_username", "username"),
            ("current_title", "title"),
            ("current_url", "url"),
        ):
            if account.get(target_key) is not None:
                values[legacy_key] = str(account[target_key])
        if account.get("has_snapshot"):
            values.update({
                "subscriber_count": account.get("subscriber_count"),
                "subscriber_count_display": _subscriber_display(
                    account.get("subscriber_count"), account.get("subscriber_display")
                ),
                "subscriber_measured_at": _timestamp(account["subscriber_observed_at"]),
                "data_quality": str(quality),
            })
        checked_at = account.get("result_completed_at") or account.get("result_started_at")
        if checked_at is not None:
            values["last_checked_at"] = _timestamp(checked_at)
            values["last_error"] = _result_error(account)
        self._update_columns(connection, "platform_accounts", account_legacy_id, values)

        if platform != "telegram":
            return
        channel_legacy_id = _positive(account.get("channel_legacy_id"), "channel alias")
        channel = connection.execute(
            "SELECT * FROM channels WHERE id=?", (channel_legacy_id,)
        ).fetchone()
        if channel is None:
            raise RuntimeError("S-final channel alias does not resolve in legacy SQLite")
        if (
            int(channel["platform_account_id"]) != account_legacy_id
            or int(channel["institution_id"]) != institution_legacy_id
            or bool(channel["enabled"]) != bool(account["enabled"])
        ):
            raise RuntimeError("administrative Telegram channel fields changed")
        channel_values: dict[str, Any] = {}
        if account.get("native_external_id") is not None:
            channel_values["telegram_id"] = _signed_integer(
                account["native_external_id"], "Telegram native identity"
            )
        if account.get("current_username") is not None:
            username = str(account["current_username"]).lstrip("@").strip()
            if not username:
                raise RuntimeError("Telegram username cannot be blank")
            conflict = connection.execute(
                "SELECT id FROM channels WHERE username=? COLLATE NOCASE AND id<>?",
                (username, channel_legacy_id),
            ).fetchone()
            if conflict is not None:
                raise RuntimeError("Telegram username conflicts in legacy SQLite")
            channel_values["username"] = username
        if account.get("current_title") is not None:
            channel_values["title"] = str(account["current_title"])
        if account.get("has_snapshot"):
            channel_values.update({
                "subscriber_count": account.get("subscriber_count"),
                "subscriber_count_display": _subscriber_display(
                    account.get("subscriber_count"), account.get("subscriber_display")
                ),
                "subscriber_measured_at": _timestamp(account["subscriber_observed_at"]),
            })
        if checked_at is not None:
            channel_values["last_checked_at"] = _timestamp(checked_at)
            channel_values["last_error"] = _result_error(account)
        cursor = account.get("collector_cursor")
        if cursor not in (None, ""):
            channel_values["last_seen_message_id"] = max(
                int(channel["last_seen_message_id"]),
                _positive(cursor, "Telegram collector cursor"),
            )
        self._update_columns(connection, "channels", channel_legacy_id, channel_values)

    @staticmethod
    def _assert_canonical_account_identity(
        legacy: sqlite3.Row, account: Mapping[str, Any]
    ) -> None:
        platform = str(account["platform"])
        canonical = str(account["canonical_external_id"])
        if platform == "telegram" and account.get("channel_legacy_id") is not None:
            expected = str(legacy["native_id"] or legacy["external_key"]).strip()
        else:
            expected = str(legacy["native_id"] or legacy["external_key"]).strip()
        if canonical != expected:
            raise RuntimeError("canonical account identity changed during rollback window")

    def _apply_telegram_publication(
        self,
        connection: sqlite3.Connection,
        publication: Mapping[str, Any],
        legacy_id: int,
    ) -> int:
        channel_id = _positive(publication.get("channel_legacy_id"), "channel alias")
        identities = _identities(publication)
        primary = _primary_identity(identities)
        try:
            prefix, primary_value = parse_telegram_external_id(primary["external_id"])
        except ValueError as error:
            raise RuntimeError("Telegram primary identity is not canonical") from error
        message_ids: set[int] = set()
        for identity in identities:
            external_id = str(identity["external_id"])
            try:
                identity_prefix, value = parse_telegram_external_id(external_id)
            except ValueError:
                if identity["role"] == "source":
                    continue
                raise RuntimeError("Telegram identity is not canonical")
            role = str(identity["role"])
            if identity_prefix == "m":
                if role not in {"primary", "album_member"}:
                    raise RuntimeError("Telegram message identity has an invalid role")
                message_ids.add(value)
            elif role != "primary":
                raise RuntimeError("Telegram group identity must be primary")
        if not message_ids:
            raise RuntimeError("Telegram publication has no message identity")
        if prefix == "g":
            if publication.get("content_group_id") is None:
                raise RuntimeError("Telegram album lacks a content group")
            grouped_id: int | None = primary_value
            if any(
                identity["role"] == "primary"
                and str(identity["external_id"]).startswith("m:")
                for identity in identities
            ):
                raise RuntimeError("Telegram album has a message primary identity")
        else:
            if publication.get("content_group_id") is not None or message_ids != {primary_value}:
                raise RuntimeError("non-album Telegram identity set is not representable")
            grouped_id = None
        flags = publication.get("quality_flags") or {}
        if not isinstance(flags, Mapping):
            raise RuntimeError("publication quality_flags must be an object")
        allowed = {"ambiguous_reactions", "ambiguous_album_reactions"}
        unsupported = {
            str(key): value
            for key, value in flags.items()
            if key not in allowed
        }
        if unsupported:
            raise RuntimeError("Telegram publication has unsupported quality flags")
        ambiguous_values = [bool(flags[key]) for key in allowed if key in flags]
        if len(set(ambiguous_values)) > 1:
            raise RuntimeError("Telegram ambiguity flags disagree")
        ambiguous = ambiguous_values[0] if ambiguous_values else False
        history_complete, forced = _legacy_history(publication)
        first_age = _nonnegative(
            publication.get("first_observation_age_seconds"), "first observation age"
        )
        deletion = _deletion_values(publication)
        expected = {
            "channel_id": channel_id,
            "logical_key": str(primary["external_id"]),
            "telegram_message_id": min(message_ids),
            "telegram_grouped_id": grouped_id,
            "published_at": _timestamp(publication["published_at"]),
            "discovered_at": _timestamp(publication["discovered_at"]),
            "first_observation_age_seconds": first_age,
            "history_complete": history_complete,
            "history_forced_incomplete": forced,
            "baseline_from_publication": int(bool(publication["synthetic_baseline_allowed"])),
            "post_type": _nonempty(publication.get("publication_type"), "publication type"),
            "ambiguous_album_reactions": int(ambiguous),
            "is_repost": int(bool(publication["is_repost"])),
            **deletion,
            "created_at": _timestamp(publication["created_at"]),
        }
        self._upsert_row(connection, "posts", legacy_id, expected)
        existing_messages = {
            int(row[0])
            for row in connection.execute(
                "SELECT telegram_message_id FROM post_messages WHERE post_id=?",
                (legacy_id,),
            )
        }
        if not existing_messages.issubset(message_ids):
            raise RuntimeError("target Telegram identities lost a legacy album member")
        connection.executemany(
            "INSERT OR IGNORE INTO post_messages(post_id,telegram_message_id) VALUES(?,?)",
            [(legacy_id, message_id) for message_id in sorted(message_ids)],
        )
        return legacy_id

    def _apply_platform_publication(
        self,
        connection: sqlite3.Connection,
        publication: Mapping[str, Any],
        legacy_id: int,
    ) -> None:
        if publication.get("content_group_id") is not None:
            raise RuntimeError("non-Telegram content group is not representable")
        account_id = _positive(publication.get("account_legacy_id"), "account alias")
        identities = _identities(publication)
        primary = _primary_identity(identities)
        flags = publication.get("quality_flags") or {}
        if not isinstance(flags, Mapping):
            raise RuntimeError("publication quality_flags must be an object")
        platform = str(publication["platform"])
        joint = bool(flags.get("joint_post") or flags.get("legacy_is_joint"))
        additional_authors = int(
            flags.get(
                "additional_author_count",
                flags.get("legacy_additional_author_count", 0),
            )
            or 0
        )
        if additional_authors < 0 or (platform != "vk" and (joint or additional_authors)):
            raise RuntimeError("joint-author metadata is not representable")
        history_complete, forced = _legacy_history(publication)
        deletion = _deletion_values(publication)
        current = connection.execute(
            "SELECT raw_json FROM platform_posts WHERE id=?", (legacy_id,)
        ).fetchone()
        envelope = ReversePublicationEnvelope(
            legacy_table="platform_posts",
            publication_id=UUID(str(publication["id"])),
            quality_flags=dict(flags),
            identities=tuple(
                {
                    "external_id": str(identity["external_id"]),
                    "source_external_id": identity.get("source_external_id"),
                    "role": str(identity["role"]),
                    "public_url": identity.get("public_url"),
                }
                for identity in identities
            ),
        )
        raw_json = add_reverse_publication_envelope(
            current["raw_json"] if current is not None else None,
            envelope,
        )
        expected = {
            "platform_account_id": account_id,
            "external_id": str(primary["external_id"]),
            "published_at": _timestamp(publication["published_at"]),
            "discovered_at": _timestamp(publication["discovered_at"]),
            "post_type": _nonempty(publication.get("publication_type"), "publication type"),
            "url": _optional_https(primary.get("public_url")),
            **deletion,
            "raw_json": raw_json,
            "history_complete": history_complete,
            "history_forced_incomplete": forced,
            "source_external_id": _optional_text(primary.get("source_external_id")),
            "is_joint": int(joint),
            "additional_author_count": additional_authors,
            "is_repost": int(bool(publication["is_repost"])),
            "created_at": _timestamp(publication["created_at"]),
        }
        self._upsert_row(connection, "platform_posts", legacy_id, expected)

    def _apply_telegram_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        post_id: int,
    ) -> None:
        self._validate_snapshot(snapshot, telegram=True)
        breakdown = snapshot.get("reaction_breakdown") or {}
        if not isinstance(breakdown, Mapping):
            raise RuntimeError("Telegram reaction breakdown must be an object")
        normalized_breakdown = {
            _nonempty(key, "reaction key"): _nonnegative(value, "reaction count")
            for key, value in breakdown.items()
        }
        envelope = self._snapshot_envelope(snapshot, "reaction_snapshots")
        legacy_row_id = self._snapshot_legacy_id(snapshot, "reaction_snapshots")
        expected = {
            "post_id": post_id,
            "measured_at": _timestamp(snapshot["observed_at"]),
            "measurement_bucket": int(snapshot["sampling_bucket"]),
            "age_seconds": _nonnegative(snapshot["age_seconds"], "snapshot age"),
            "total_reactions": _nonnegative(
                snapshot["reactions_count"], "Telegram reactions"
            ),
            "reactions_json": canonical_json(normalized_breakdown),
            "raw_state_json": envelope.as_json(),
            "delta_total": None,
            "delta_by_reaction_json": None,
            "delta_seconds": None,
            "rate_per_hour": None,
            "interval_uncertain": int(bool(snapshot["interval_uncertain"])),
            "spike": 0,
            "comments_count": _nullable_nonnegative(
                snapshot.get("comments_count"), "comments"
            ),
            "delta_comments": None,
            "views_count": _nullable_nonnegative(snapshot.get("views_count"), "views"),
            "delta_views": None,
            "synthetic": int(bool(snapshot["synthetic"])),
            "created_at": _timestamp(snapshot["created_at"]),
        }
        self._insert_snapshot_row(
            connection, "reaction_snapshots", legacy_row_id,
            "post_id", post_id, expected,
        )

    def _apply_platform_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
        platform_post_id: int,
    ) -> None:
        self._validate_snapshot(snapshot, telegram=False)
        envelope = self._snapshot_envelope(snapshot, "platform_snapshots")
        legacy_row_id = self._snapshot_legacy_id(snapshot, "platform_snapshots")
        expected = {
            "platform_post_id": platform_post_id,
            "measured_at": _timestamp(snapshot["observed_at"]),
            "measurement_bucket": int(snapshot["sampling_bucket"]),
            "age_seconds": _nonnegative(snapshot["age_seconds"], "snapshot age"),
            "views_count": _nullable_nonnegative(snapshot.get("views_count"), "views"),
            "reactions_count": _nullable_nonnegative(
                snapshot.get("reactions_count"), "reactions"
            ),
            "comments_count": _nullable_nonnegative(
                snapshot.get("comments_count"), "comments"
            ),
            "shares_count": _nullable_nonnegative(snapshot.get("shares_count"), "shares"),
            "raw_json": envelope.as_json(),
            "created_at": _timestamp(snapshot["created_at"]),
        }
        self._insert_snapshot_row(
            connection, "platform_snapshots", legacy_row_id,
            "platform_post_id", platform_post_id, expected,
        )

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, Any], *, telegram: bool) -> None:
        quality = str(snapshot["quality"])
        if quality not in SUPPORTED_QUALITIES:
            raise RuntimeError("snapshot quality is not representable")
        if int(snapshot["metric_semantics_version"]) != 1:
            raise RuntimeError("snapshot metric semantics version is unsupported")
        if int(snapshot["capability_version"]) != 1:
            raise RuntimeError("snapshot capability version is unsupported")
        source_fingerprint = str(snapshot.get("source_fingerprint") or "").strip()
        if not source_fingerprint:
            raise RuntimeError("snapshot source fingerprint is missing")
        bucket = int(snapshot["sampling_bucket"])
        synthetic = bool(snapshot["synthetic"])
        if (bucket < 0) != synthetic:
            raise RuntimeError("snapshot bucket/synthetic semantics are inconsistent")
        if telegram:
            if snapshot.get("reactions_count") is None:
                raise RuntimeError("Telegram reaction count cannot be NULL")
            if snapshot.get("shares_count") is not None:
                raise RuntimeError("Telegram shares are not representable")
        elif synthetic or bool(snapshot["interval_uncertain"]):
            raise RuntimeError("non-Telegram synthetic/uncertain snapshot is unsupported")

    @staticmethod
    def _snapshot_envelope(
        snapshot: Mapping[str, Any], legacy_table: str
    ) -> ReverseSnapshotEnvelope:
        return ReverseSnapshotEnvelope(
            legacy_table=legacy_table,
            publication_id=UUID(str(snapshot["publication_id"])),
            published_month=datetime.fromisoformat(
                f"{snapshot['published_month']}T00:00:00+00:00"
            ).date(),
            snapshot_id=_positive(snapshot["id"], "target snapshot id"),
            collected_at=_datetime(snapshot["collected_at"]),
            quality=str(snapshot["quality"]),
            interval_uncertain=bool(snapshot["interval_uncertain"]),
            synthetic=bool(snapshot["synthetic"]),
            metric_semantics_version=int(snapshot["metric_semantics_version"]),
            capability_version=int(snapshot["capability_version"]),
            source_fingerprint=str(snapshot["source_fingerprint"]),
            created_at=_datetime(snapshot["created_at"]),
        )

    def _snapshot_legacy_id(
        self, snapshot: Mapping[str, Any], legacy_table: str
    ) -> int:
        del legacy_table
        return _positive(
            snapshot.get("legacy_id"),
            "reserved legacy snapshot identity",
        )

    @staticmethod
    def _insert_snapshot_row(
        connection: sqlite3.Connection,
        table: str,
        legacy_row_id: int,
        owner_column: str,
        owner_id: int,
        expected: Mapping[str, Any],
    ) -> None:
        conflict = connection.execute(
            f"SELECT * FROM {table} WHERE {owner_column}=? AND measurement_bucket=?",
            (owner_id, expected["measurement_bucket"]),
        ).fetchone()
        if conflict is not None:
            comparable = dict(expected)
            if table == "reaction_snapshots":
                for derived in (
                    "delta_total", "delta_by_reaction_json", "delta_seconds",
                    "rate_per_hour", "delta_comments", "delta_views",
                ):
                    comparable.pop(derived)
            _assert_row_values(conflict, comparable, f"{table} sampling bucket")
            if int(conflict["id"]) != legacy_row_id:
                raise RuntimeError("snapshot bucket already has a different legacy identity")
            return
        identity_conflict = connection.execute(
            f"SELECT 1 FROM {table} WHERE id=?", (legacy_row_id,)
        ).fetchone()
        if identity_conflict is not None:
            raise RuntimeError("deterministic reverse snapshot identity collided")
        columns = ("id", *expected.keys())
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
            (legacy_row_id, *expected.values()),
        )

    @staticmethod
    def _recalculate_telegram_deltas(
        connection: sqlite3.Connection, post_id: int
    ) -> None:
        rows = list(connection.execute(
            "SELECT * FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at,id",
            (post_id,),
        ))
        previous: sqlite3.Row | None = None
        for row in rows:
            if previous is None:
                values = (None, None, None, None, None, None)
            else:
                current_reactions = json.loads(str(row["reactions_json"]))
                previous_reactions = json.loads(str(previous["reactions_json"]))
                delta_total = int(row["total_reactions"]) - int(previous["total_reactions"])
                delta_seconds = max(
                    1,
                    int(
                        (_datetime(row["measured_at"]) - _datetime(previous["measured_at"])).total_seconds()
                    ),
                )
                values = (
                    delta_total,
                    canonical_json(delta_by_reaction(current_reactions, previous_reactions)),
                    delta_seconds,
                    delta_total * 3600 / delta_seconds,
                    _nullable_delta(row["comments_count"], previous["comments_count"]),
                    _nullable_delta(row["views_count"], previous["views_count"]),
                )
            connection.execute(
                """UPDATE reaction_snapshots
                      SET delta_total=?, delta_by_reaction_json=?, delta_seconds=?,
                          rate_per_hour=?, delta_comments=?, delta_views=?
                    WHERE id=?""",
                (*values, int(row["id"])),
            )
            previous = row

    @staticmethod
    def _apply_collection_state(
        connection: sqlite3.Connection,
        runs: Sequence[Mapping[str, Any]],
    ) -> None:
        latest: dict[str, Mapping[str, Any]] = {}
        for run in runs:
            status = str(run["status"])
            if status not in TERMINAL_RUN_STATUSES:
                continue
            platform = str(run["platform"])
            previous = latest.get(platform)
            if previous is None or (
                str(run["started_at"]), str(run["id"])
            ) > (str(previous["started_at"]), str(previous["id"])):
                latest[platform] = run
        for platform, run in latest.items():
            started = _datetime(run["started_at"])
            completed = _datetime(run["completed_at"] or run["started_at"])
            prefix = "" if platform == "telegram" else f"{platform}_"
            account_key = "channel_count" if platform == "telegram" else "account_count"
            state = {
                f"{prefix}poll_last_started_at": started.isoformat(),
                f"{prefix}poll_last_completed_at": completed.isoformat(),
                f"{prefix}poll_last_duration_seconds": f"{max(0.0, (completed-started).total_seconds()):.3f}",
                f"{prefix}poll_last_error_count": str(int(run["error_count"])),
                f"{prefix}poll_last_{account_key}": str(int(run["account_count"])),
            }
            if platform == "telegram":
                state["last_poll"] = completed.isoformat()
            connection.executemany(
                """INSERT INTO app_state(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                sorted(state.items()),
            )

    def _verify_connection(
        self,
        connection: sqlite3.Connection,
        plan: SyncPlan,
        aliases: Mapping[UUID, tuple[str, int]],
    ) -> None:
        for account in plan.accounts:
            self._verify_account(connection, account)
        for publication in plan.publications:
            publication_id = UUID(str(publication["id"]))
            alias = aliases[publication_id]
            if publication["platform"] == "telegram":
                self._verify_telegram_publication(
                    connection, publication, int(alias[1])
                )
            else:
                self._verify_platform_publication(
                    connection, publication, int(alias[1])
                )
        for snapshot in plan.snapshots:
            table = (
                "reaction_snapshots"
                if snapshot["platform"] == "telegram"
                else "platform_snapshots"
            )
            legacy_id = self._snapshot_legacy_id(snapshot, table)
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id=?", (legacy_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("legacy snapshot verification failed")
            envelope_field = "raw_state_json" if table == "reaction_snapshots" else "raw_json"
            envelope = parse_reverse_snapshot_envelope(row[envelope_field])
            if envelope != self._snapshot_envelope(snapshot, table):
                raise RuntimeError("legacy snapshot envelope verification failed")
            expected = {
                "measured_at": _timestamp(snapshot["observed_at"]),
                "measurement_bucket": int(snapshot["sampling_bucket"]),
                "age_seconds": int(snapshot["age_seconds"]),
                "views_count": snapshot.get("views_count"),
                "comments_count": snapshot.get("comments_count"),
                "created_at": _timestamp(snapshot["created_at"]),
            }
            if table == "reaction_snapshots":
                expected.update({
                    "post_id": int(aliases[UUID(str(snapshot["publication_id"]))][1]),
                    "total_reactions": snapshot.get("reactions_count"),
                    "reactions_json": canonical_json(
                        snapshot.get("reaction_breakdown") or {}
                    ),
                    "interval_uncertain": int(bool(snapshot["interval_uncertain"])),
                    "synthetic": int(bool(snapshot["synthetic"])),
                })
            else:
                expected.update({
                    "platform_post_id": int(
                        aliases[UUID(str(snapshot["publication_id"]))][1]
                    ),
                    "reactions_count": snapshot.get("reactions_count"),
                    "shares_count": snapshot.get("shares_count"),
                })
            _assert_row_values(row, expected, "snapshot verification")
        duplicate_checks = (
            "SELECT count(*) FROM (SELECT channel_id,logical_key FROM posts GROUP BY 1,2 HAVING count(*)>1)",
            "SELECT count(*) FROM (SELECT platform_account_id,external_id FROM platform_posts GROUP BY 1,2 HAVING count(*)>1)",
            "SELECT count(*) FROM (SELECT post_id,measurement_bucket FROM reaction_snapshots GROUP BY 1,2 HAVING count(*)>1)",
            "SELECT count(*) FROM (SELECT platform_post_id,measurement_bucket FROM platform_snapshots GROUP BY 1,2 HAVING count(*)>1)",
        )
        if any(int(connection.execute(sql).fetchone()[0]) for sql in duplicate_checks):
            raise RuntimeError("legacy SQLite contains duplicate reverse-sync keys")

    @staticmethod
    def _verify_telegram_publication(
        connection: sqlite3.Connection,
        publication: Mapping[str, Any],
        legacy_id: int,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM posts WHERE id=?", (legacy_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("legacy Telegram publication verification failed")
        identities = _identities(publication)
        primary = _primary_identity(identities)
        prefix, primary_value = parse_telegram_external_id(str(primary["external_id"]))
        message_ids = {
            parse_telegram_external_id(str(identity["external_id"]))[1]
            for identity in identities
            if str(identity["external_id"]).startswith("m:")
        }
        flags = publication.get("quality_flags") or {}
        ambiguous = bool(
            flags.get("ambiguous_reactions")
            or flags.get("ambiguous_album_reactions")
        )
        complete, forced = _legacy_history(publication)
        expected = {
            "channel_id": int(publication["channel_legacy_id"]),
            "logical_key": str(primary["external_id"]),
            "telegram_message_id": min(message_ids),
            "telegram_grouped_id": primary_value if prefix == "g" else None,
            "published_at": _timestamp(publication["published_at"]),
            "discovered_at": _timestamp(publication["discovered_at"]),
            "first_observation_age_seconds": int(
                publication["first_observation_age_seconds"]
            ),
            "history_complete": complete,
            "history_forced_incomplete": forced,
            "baseline_from_publication": int(
                bool(publication["synthetic_baseline_allowed"])
            ),
            "post_type": str(publication["publication_type"]),
            "ambiguous_album_reactions": int(ambiguous),
            "is_repost": int(bool(publication["is_repost"])),
            **_deletion_values(publication),
            "created_at": _timestamp(publication["created_at"]),
        }
        _assert_row_values(row, expected, "Telegram publication verification")
        actual_messages = {
            int(item[0])
            for item in connection.execute(
                "SELECT telegram_message_id FROM post_messages WHERE post_id=?",
                (legacy_id,),
            )
        }
        if actual_messages != message_ids:
            raise RuntimeError("Telegram album member verification failed")

    @staticmethod
    def _verify_platform_publication(
        connection: sqlite3.Connection,
        publication: Mapping[str, Any],
        legacy_id: int,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM platform_posts WHERE id=?", (legacy_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("legacy platform publication verification failed")
        identities = _identities(publication)
        primary = _primary_identity(identities)
        flags = publication.get("quality_flags") or {}
        joint = bool(flags.get("joint_post") or flags.get("legacy_is_joint"))
        authors = int(
            flags.get(
                "additional_author_count",
                flags.get("legacy_additional_author_count", 0),
            ) or 0
        )
        complete, forced = _legacy_history(publication)
        expected = {
            "platform_account_id": int(publication["account_legacy_id"]),
            "external_id": str(primary["external_id"]),
            "published_at": _timestamp(publication["published_at"]),
            "discovered_at": _timestamp(publication["discovered_at"]),
            "post_type": str(publication["publication_type"]),
            "url": _optional_https(primary.get("public_url")),
            **_deletion_values(publication),
            "history_complete": complete,
            "history_forced_incomplete": forced,
            "source_external_id": _optional_text(primary.get("source_external_id")),
            "is_joint": int(joint),
            "additional_author_count": authors,
            "is_repost": int(bool(publication["is_repost"])),
            "created_at": _timestamp(publication["created_at"]),
        }
        _assert_row_values(row, expected, "platform publication verification")
        envelope = parse_reverse_publication_envelope(row["raw_json"])
        wanted = ReversePublicationEnvelope(
            legacy_table="platform_posts",
            publication_id=UUID(str(publication["id"])),
            quality_flags=dict(flags),
            identities=tuple({
                "external_id": str(identity["external_id"]),
                "source_external_id": identity.get("source_external_id"),
                "role": str(identity["role"]),
                "public_url": identity.get("public_url"),
            } for identity in identities),
        )
        if envelope != wanted:
            raise RuntimeError("platform publication envelope verification failed")

    @staticmethod
    def _verify_account(
        connection: sqlite3.Connection, account: Mapping[str, Any]
    ) -> None:
        legacy_id = _positive(account.get("account_legacy_id"), "account alias")
        row = connection.execute(
            "SELECT * FROM platform_accounts WHERE id=?", (legacy_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("legacy account verification failed")
        expected: dict[str, Any] = {}
        for source, target in (
            ("native_external_id", "native_id"),
            ("current_username", "username"),
            ("current_title", "title"),
            ("current_url", "url"),
        ):
            if account.get(source) is not None:
                expected[target] = str(account[source])
        if account.get("has_snapshot"):
            expected.update({
                "subscriber_count": account.get("subscriber_count"),
                "subscriber_count_display": _subscriber_display(
                    account.get("subscriber_count"), account.get("subscriber_display")
                ),
                "subscriber_measured_at": _timestamp(account["subscriber_observed_at"]),
                "data_quality": str(account["subscriber_quality"]),
            })
        checked = account.get("result_completed_at") or account.get("result_started_at")
        if checked is not None:
            expected["last_checked_at"] = _timestamp(checked)
            expected["last_error"] = _result_error(account)
        _assert_row_values(row, expected, "platform account")
        if account["platform"] == "telegram":
            channel_id = int(account["channel_legacy_id"])
            channel = connection.execute(
                "SELECT * FROM channels WHERE id=?", (channel_id,)
            ).fetchone()
            if channel is None:
                raise RuntimeError("legacy Telegram account verification failed")
            channel_expected: dict[str, Any] = {}
            if account.get("native_external_id") is not None:
                channel_expected["telegram_id"] = int(account["native_external_id"])
            if account.get("current_username") is not None:
                channel_expected["username"] = str(account["current_username"]).lstrip("@")
            if account.get("current_title") is not None:
                channel_expected["title"] = str(account["current_title"])
            if account.get("has_snapshot"):
                channel_expected.update({
                    "subscriber_count": account.get("subscriber_count"),
                    "subscriber_count_display": _subscriber_display(
                        account.get("subscriber_count"), account.get("subscriber_display")
                    ),
                    "subscriber_measured_at": _timestamp(
                        account["subscriber_observed_at"]
                    ),
                })
            if checked is not None:
                channel_expected["last_checked_at"] = _timestamp(checked)
                channel_expected["last_error"] = _result_error(account)
            if account.get("collector_cursor") not in (None, ""):
                if int(channel["last_seen_message_id"]) < int(account["collector_cursor"]):
                    raise RuntimeError("Telegram cursor verification failed")
            _assert_row_values(channel, channel_expected, "Telegram account")

    @staticmethod
    def _update_columns(
        connection: sqlite3.Connection,
        table: str,
        row_id: int,
        values: Mapping[str, Any],
    ) -> None:
        if not values:
            return
        assignments = ",".join(f"{column}=?" for column in values)
        cursor = connection.execute(
            f"UPDATE {table} SET {assignments} WHERE id=?",
            (*values.values(), row_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"legacy {table} row disappeared")

    @staticmethod
    def _upsert_row(
        connection: sqlite3.Connection,
        table: str,
        row_id: int,
        values: Mapping[str, Any],
    ) -> None:
        existing = connection.execute(
            f"SELECT id FROM {table} WHERE id=?", (row_id,)
        ).fetchone()
        if existing is None:
            columns = ("id", *values.keys())
            placeholders = ",".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                (row_id, *values.values()),
            )
        else:
            LegacySqliteTarget._update_columns(connection, table, row_id, values)
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id=?", (row_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"legacy {table} upsert failed")
        _assert_row_values(row, values, table)


def _identities(publication: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = publication.get("identities")
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("publication identities are missing")
    identities = tuple(item for item in raw if isinstance(item, Mapping))
    if len(identities) != len(raw):
        raise RuntimeError("publication identity is malformed")
    for identity in identities:
        _nonempty(identity.get("external_id"), "publication external identity")
        if str(identity.get("role")) not in {
            "primary", "album_member", "joint_author", "source", "repost_source",
        }:
            raise RuntimeError("publication identity role is unsupported")
        _optional_https(identity.get("public_url"))
    return identities


def _primary_identity(
    identities: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    primary = [identity for identity in identities if identity["role"] == "primary"]
    if len(primary) != 1:
        raise RuntimeError("publication must have exactly one primary identity")
    return primary[0]


def _legacy_history(publication: Mapping[str, Any]) -> tuple[int, int]:
    value = str(publication["history_completeness"])
    if value not in {"complete", "incomplete", "forced_incomplete"}:
        raise RuntimeError("publication history completeness is unsupported")
    complete = int(value == "complete")
    forced = int(value == "forced_incomplete")
    if bool(publication["synthetic_baseline_allowed"]) and not complete:
        raise RuntimeError("synthetic baseline requires complete history")
    return complete, forced


def _deletion_values(publication: Mapping[str, Any]) -> dict[str, Any]:
    outcome = publication.get("deletion_outcome")
    deleted_at = (
        _timestamp(publication["deleted_at"])
        if publication.get("deleted_at") is not None else None
    )
    if outcome is None:
        return {
            "deleted_at": deleted_at,
            "missing_check_count": 0,
            "missing_last_checked_at": None,
            "missing_reason": None,
        }
    outcome = str(outcome)
    if outcome not in {"present", "missing", "confirmed_deleted"}:
        raise RuntimeError("deletion observation is not representable")
    if outcome == "present":
        if deleted_at is not None:
            raise RuntimeError("present publication cannot remain deleted")
        return {
            "deleted_at": None,
            "missing_check_count": 0,
            "missing_last_checked_at": None,
            "missing_reason": None,
        }
    count = _nonnegative(publication.get("consecutive_missing"), "missing count")
    observed = _timestamp(publication["deletion_observed_at"])
    reason = _nonempty(publication.get("deletion_reason_code"), "deletion reason")
    if outcome == "confirmed_deleted" and deleted_at is None:
        deleted_at = observed
    if outcome == "missing" and deleted_at is not None:
        raise RuntimeError("unconfirmed missing publication is already deleted")
    return {
        "deleted_at": deleted_at,
        "missing_check_count": count,
        "missing_last_checked_at": observed,
        "missing_reason": reason,
    }


def _result_error(account: Mapping[str, Any]) -> str | None:
    status = str(account.get("result_status") or "")
    if status == "succeeded":
        return None
    code = _optional_text(account.get("sanitized_error_code"))
    return code or (f"target:{status}" if status else None)


def _subscriber_display(count: Any, display: Any) -> str | None:
    if display is not None:
        return str(display)
    if count is None:
        return None
    return f"{int(count):,}".replace(",", " ")


def _timestamp(value: Any) -> str:
    return _datetime(value).isoformat()


def _datetime(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("reverse-sync timestamp is invalid") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise RuntimeError("reverse-sync timestamp must include an offset")
    return result


def _nonempty(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RuntimeError(f"{field} must not be blank")
    return normalized


def _positive(value: Any, field: str) -> int:
    result = _signed_integer(value, field)
    if result <= 0:
        raise RuntimeError(f"{field} must be positive")
    return result


def _nonnegative(value: Any, field: str) -> int:
    result = _signed_integer(value, field)
    if result < 0:
        raise RuntimeError(f"{field} must not be negative")
    return result


def _nullable_nonnegative(value: Any, field: str) -> int | None:
    return None if value is None else _nonnegative(value, field)


def _signed_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{field} must be an integer") from error
    if str(value).strip() != str(result):
        raise RuntimeError(f"{field} must be a canonical integer")
    return result


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_https(value: Any) -> str | None:
    normalized = _optional_text(value)
    if normalized is not None and not normalized.startswith("https://"):
        raise RuntimeError("public URL must use https")
    return normalized


def _nullable_delta(current: Any, previous: Any) -> int | None:
    if current is None or previous is None:
        return None
    return int(current) - int(previous)


def _assert_row_values(
    row: sqlite3.Row,
    expected: Mapping[str, Any],
    context: str,
) -> None:
    actual = {key: canonical_value(row[key]) for key in expected}
    wanted = {key: canonical_value(value) for key, value in expected.items()}
    if actual != wanted:
        raise RuntimeError(f"legacy {context} differs from reverse-sync payload")


def _has_symlink_ancestor(path: Path) -> bool:
    candidate = path
    while candidate != candidate.parent:
        if candidate.is_symlink():
            return True
        candidate = candidate.parent
    return candidate.is_symlink()
