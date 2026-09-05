from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .model import SourceInventory, TableInventory, canonical_json


LEGACY_TABLES: tuple[str, ...] = (
    "schema_migrations",
    "app_state",
    "institutions",
    "platform_accounts",
    "channels",
    "platform_posts",
    "posts",
    "post_messages",
    "platform_snapshots",
    "reaction_snapshots",
)

TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "schema_migrations": ("applied_at",),
    "institutions": ("created_at", "m_rating_measured_at"),
    "platform_accounts": (
        "added_at",
        "subscriber_measured_at",
        "last_checked_at",
    ),
    "channels": ("added_at", "subscriber_measured_at", "last_checked_at"),
    "platform_posts": (
        "published_at",
        "discovered_at",
        "deleted_at",
        "missing_last_checked_at",
        "created_at",
    ),
    "posts": (
        "published_at",
        "discovered_at",
        "deleted_at",
        "missing_last_checked_at",
        "created_at",
    ),
    "platform_snapshots": ("measured_at", "created_at"),
    "reaction_snapshots": ("measured_at", "created_at"),
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def create_online_backup(source: Path, destination: Path) -> dict[str, Any]:
    """Create and verify a consistent backup without copying a live WAL file."""

    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("source and destination must differ")
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    source_uri = f"{source.as_uri()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True, timeout=30) as source_conn:
        with sqlite3.connect(destination) as destination_conn:
            source_conn.backup(destination_conn, pages=1_000)
    destination.chmod(0o600)
    with sqlite3.connect(f"{destination.as_uri()}?mode=ro", uri=True) as verify:
        quick_check = str(verify.execute("PRAGMA quick_check").fetchone()[0])
        fk_violations = len(list(verify.execute("PRAGMA foreign_key_check")))
    if quick_check != "ok" or fk_violations:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"backup verification failed: quick_check={quick_check}, "
            f"foreign_key_violations={fk_violations}"
        )
    return {
        "source": str(source),
        "destination": str(destination),
        "size_bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "quick_check": quick_check,
        "foreign_key_violations": fk_violations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class LegacySource:
    """Strict read-only view of one consistent SQLite backup."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        wal_path = self.path.with_name(f"{self.path.name}-wal")
        if wal_path.exists() and wal_path.stat().st_size > 0:
            raise RuntimeError(
                "source has a non-empty SQLite WAL; create a consistent backup "
                "with the backup command before importing"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro&immutable=1", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def table_names(self) -> set[str]:
        with self.connect() as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

    def columns(self, table: str) -> tuple[str, ...]:
        quoted = _quote_identifier(table)
        with self.connect() as connection:
            return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted})"))

    def iter_rows(
        self,
        table: str,
        *,
        after_rowid: int = 0,
        batch_size: int = 1_000,
    ) -> Iterator[list[dict[str, Any]]]:
        if not 1 <= batch_size <= 50_000:
            raise ValueError("batch_size must be between 1 and 50000")
        quoted = _quote_identifier(table)
        with self.connect() as connection:
            cursor = connection.execute(
                f"SELECT rowid AS __source_rowid, * FROM {quoted} "
                "WHERE rowid>? ORDER BY rowid",
                (after_rowid,),
            )
            while rows := cursor.fetchmany(batch_size):
                yield [dict(row) for row in rows]

    def inventory(self) -> SourceInventory:
        digest = sha256_file(self.path)
        inventories: list[TableInventory] = []
        totals: dict[str, Any] = {}
        with self.connect() as connection:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            fk_violations = len(list(connection.execute("PRAGMA foreign_key_check")))
            schema_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
            schema_version = int(schema_row[0]) if schema_row else 0
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in LEGACY_TABLES:
                if table not in existing:
                    continue
                quoted = _quote_identifier(table)
                columns = tuple(
                    str(row[1])
                    for row in connection.execute(f"PRAGMA table_info({quoted})")
                )
                row_digest = hashlib.sha256()
                count = 0
                min_timestamp: str | None = None
                max_timestamp: str | None = None
                for raw_row in connection.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
                    row = dict(raw_row)
                    row_digest.update(canonical_json(row).encode("utf-8"))
                    row_digest.update(b"\n")
                    count += 1
                    for column in TIMESTAMP_COLUMNS.get(table, ()):
                        value = row.get(column)
                        if value:
                            text = str(value)
                            min_timestamp = text if min_timestamp is None else min(min_timestamp, text)
                            max_timestamp = text if max_timestamp is None else max(max_timestamp, text)
                inventories.append(
                    TableInventory(
                        name=table,
                        columns=columns,
                        row_count=count,
                        canonical_hash=row_digest.hexdigest(),
                        min_timestamp=min_timestamp,
                        max_timestamp=max_timestamp,
                    )
                )
                totals[f"{table}.rows"] = count
            totals.update(self._metric_totals(connection, existing))
        return SourceInventory(
            source_path=str(self.path),
            source_size_bytes=self.path.stat().st_size,
            source_sha256=digest,
            schema_version=schema_version,
            quick_check=quick_check,
            foreign_key_violations=fk_violations,
            captured_at=datetime.now(timezone.utc).isoformat(),
            tables=tuple(inventories),
            totals=totals,
        )

    @staticmethod
    def _metric_totals(
        connection: sqlite3.Connection, existing: Sequence[str]
    ) -> dict[str, Any]:
        totals: dict[str, Any] = {}
        if "reaction_snapshots" in existing:
            row = connection.execute(
                """SELECT COUNT(*) AS rows,
                          SUM(total_reactions) AS reactions,
                          SUM(views_count) AS views,
                          SUM(comments_count) AS comments,
                          0 AS reactions_null,
                          SUM(CASE WHEN total_reactions=0 THEN 1 ELSE 0 END) AS reactions_zero,
                          SUM(CASE WHEN views_count IS NULL THEN 1 ELSE 0 END) AS views_null,
                          SUM(CASE WHEN views_count=0 THEN 1 ELSE 0 END) AS views_zero,
                          SUM(CASE WHEN comments_count IS NULL THEN 1 ELSE 0 END) AS comments_null,
                          SUM(CASE WHEN comments_count=0 THEN 1 ELSE 0 END) AS comments_zero,
                          SUM(CASE WHEN 1 THEN 1 ELSE 0 END) AS shares_null,
                          0 AS shares_zero,
                          SUM(CASE WHEN delta_total<0 THEN 1 ELSE 0 END) AS negative_reaction_transitions,
                          SUM(CASE WHEN delta_views<0 THEN 1 ELSE 0 END) AS negative_view_transitions,
                          SUM(CASE WHEN delta_comments<0 THEN 1 ELSE 0 END) AS negative_comment_transitions,
                          SUM(CASE WHEN synthetic=1 THEN 1 ELSE 0 END) AS synthetic,
                          SUM(CASE WHEN interval_uncertain=1 THEN 1 ELSE 0 END) AS uncertain,
                          MIN(measured_at) AS min_observed_at,
                          MAX(measured_at) AS max_observed_at
                   FROM reaction_snapshots"""
            ).fetchone()
            for key in row.keys():
                totals[f"reaction_snapshots.{key}"] = row[key]
            breakdown_rows = 0
            breakdown_sum = 0
            breakdown_invalid = 0
            breakdown_total_mismatch = 0
            for snapshot in connection.execute(
                "SELECT total_reactions, reactions_json FROM reaction_snapshots"
            ):
                try:
                    breakdown = json.loads(snapshot["reactions_json"])
                    if not isinstance(breakdown, dict):
                        raise ValueError("reaction breakdown is not an object")
                    values = [int(value) for value in breakdown.values()]
                    if any(value < 0 for value in values):
                        raise ValueError("negative reaction count")
                except (TypeError, ValueError, json.JSONDecodeError):
                    breakdown_invalid += 1
                    continue
                breakdown_rows += len(values)
                breakdown_sum += sum(values)
                if sum(values) != int(snapshot["total_reactions"]):
                    breakdown_total_mismatch += 1
            totals["reaction_snapshots.breakdown_rows"] = breakdown_rows
            totals["reaction_snapshots.breakdown_sum"] = breakdown_sum
            totals["reaction_snapshots.breakdown_invalid"] = breakdown_invalid
            totals["reaction_snapshots.breakdown_total_mismatch"] = (
                breakdown_total_mismatch
            )
        if "platform_snapshots" in existing:
            row = connection.execute(
                """SELECT COUNT(*) AS rows,
                          SUM(reactions_count) AS reactions,
                          SUM(views_count) AS views,
                          SUM(comments_count) AS comments,
                          SUM(shares_count) AS shares,
                          SUM(CASE WHEN reactions_count IS NULL THEN 1 ELSE 0 END) AS reactions_null,
                          SUM(CASE WHEN reactions_count=0 THEN 1 ELSE 0 END) AS reactions_zero,
                          SUM(CASE WHEN views_count IS NULL THEN 1 ELSE 0 END) AS views_null,
                          SUM(CASE WHEN views_count=0 THEN 1 ELSE 0 END) AS views_zero,
                          SUM(CASE WHEN comments_count IS NULL THEN 1 ELSE 0 END) AS comments_null,
                          SUM(CASE WHEN comments_count=0 THEN 1 ELSE 0 END) AS comments_zero,
                          SUM(CASE WHEN shares_count IS NULL THEN 1 ELSE 0 END) AS shares_null,
                          SUM(CASE WHEN shares_count=0 THEN 1 ELSE 0 END) AS shares_zero,
                          0 AS synthetic,
                          0 AS uncertain,
                          MIN(measured_at) AS min_observed_at,
                          MAX(measured_at) AS max_observed_at
                   FROM platform_snapshots"""
            ).fetchone()
            for key in row.keys():
                totals[f"platform_snapshots.{key}"] = row[key]
        for table in ("posts", "platform_posts"):
            if table not in existing:
                continue
            row = connection.execute(
                f"""SELECT
                       COUNT(*) AS rows,
                       SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted,
                       SUM(CASE WHEN history_complete=0 THEN 1 ELSE 0 END) AS incomplete,
                       SUM(CASE WHEN history_forced_incomplete=1 THEN 1 ELSE 0 END) AS forced_incomplete,
                       SUM(CASE WHEN is_repost=1 THEN 1 ELSE 0 END) AS reposts
                     FROM {_quote_identifier(table)}"""
            ).fetchone()
            for key in row.keys():
                totals[f"{table}.{key}"] = row[key]
        if "posts" in existing:
            row = connection.execute(
                """SELECT
                       COUNT(DISTINCT channel_id || ':' || logical_key) AS distinct_natural_keys,
                       SUM(CASE WHEN telegram_grouped_id IS NOT NULL THEN 1 ELSE 0 END) AS album_posts,
                       COUNT(DISTINCT CASE WHEN telegram_grouped_id IS NOT NULL
                           THEN channel_id || ':' || telegram_grouped_id END) AS albums,
                       SUM(CASE WHEN ambiguous_album_reactions=1 THEN 1 ELSE 0 END) AS ambiguous_albums
                     FROM posts"""
            ).fetchone()
            for key in row.keys():
                totals[f"posts.{key}"] = row[key]
        if "platform_posts" in existing:
            row = connection.execute(
                """SELECT
                       COUNT(DISTINCT platform_account_id || ':' || external_id) AS distinct_natural_keys,
                       SUM(CASE WHEN is_joint=1 THEN 1 ELSE 0 END) AS joint_posts,
                       SUM(additional_author_count) AS additional_authors
                     FROM platform_posts"""
            ).fetchone()
            for key in row.keys():
                totals[f"platform_posts.{key}"] = row[key]
        if "post_messages" in existing:
            row = connection.execute(
                """SELECT COUNT(*) AS rows,
                          COUNT(DISTINCT post_id || ':' || telegram_message_id) AS distinct_natural_keys
                     FROM post_messages"""
            ).fetchone()
            for key in row.keys():
                totals[f"post_messages.{key}"] = row[key]
        if {"platform_accounts", "channels"}.issubset(existing):
            subscriber_rows = connection.execute(
                """SELECT subscriber_count, subscriber_count_display
                     FROM platform_accounts pa
                    WHERE subscriber_measured_at IS NOT NULL
                      AND (subscriber_count IS NOT NULL OR subscriber_count_display IS NOT NULL)
                      AND (platform <> 'telegram' OR NOT EXISTS (
                          SELECT 1 FROM channels c WHERE c.platform_account_id=pa.id
                      ))
                    UNION ALL
                   SELECT subscriber_count, subscriber_count_display
                     FROM channels
                    WHERE subscriber_measured_at IS NOT NULL
                      AND (subscriber_count IS NOT NULL OR subscriber_count_display IS NOT NULL)"""
            ).fetchall()
            totals["account_metric_snapshot.rows"] = len(subscriber_rows)
            totals["account_metric_snapshot.subscribers"] = (
                sum(int(row["subscriber_count"] or 0) for row in subscriber_rows)
                if subscriber_rows
                else None
            )
            totals["account_metric_snapshot.subscribers_null"] = sum(
                row["subscriber_count"] is None for row in subscriber_rows
            )
            totals["account_metric_snapshot.subscribers_zero"] = sum(
                row["subscriber_count"] == 0 for row in subscriber_rows
            )
        rating_rows = 0
        if "institutions" in existing:
            rating_columns = (
                "social",
                "tg",
                "vk",
                "max",
                "rutube",
            )
            for institution in connection.execute("SELECT * FROM institutions"):
                rating_rows += sum(
                    institution[f"m_rating_{category}_rank"] is not None
                    or institution[f"m_rating_{category}_score"] is not None
                    for category in rating_columns
                )
        if "channels" in existing:
            rating_rows += int(
                connection.execute(
                    """SELECT COUNT(*) FROM channels
                        WHERE m_rating_tg_rank IS NOT NULL OR m_rating_tg_score IS NOT NULL"""
                ).fetchone()[0]
            )
        totals["official_rating_observation.rows"] = rating_rows
        return totals

    def canonical_row_hashes(self, table: str) -> dict[str, str]:
        """Return stable per-primary-key hashes for reconciliation/catch-up."""

        quoted = _quote_identifier(table)
        columns = self.columns(table)
        pk_columns: list[tuple[int, str]] = []
        with self.connect() as connection:
            for column in connection.execute(f"PRAGMA table_info({quoted})"):
                if int(column[5]) > 0:
                    pk_columns.append((int(column[5]), str(column[1])))
            pk_columns.sort()
            result: dict[str, str] = {}
            for row in connection.execute(f"SELECT rowid AS __source_rowid, * FROM {quoted}"):
                mapped = dict(row)
                if pk_columns:
                    key_value = [mapped[name] for _, name in pk_columns]
                elif "id" in columns:
                    key_value = [mapped["id"]]
                else:
                    key_value = [mapped["__source_rowid"]]
                key = canonical_json(key_value)
                mapped.pop("__source_rowid", None)
                result[key] = hashlib.sha256(
                    canonical_json(mapped).encode("utf-8")
                ).hexdigest()
            return result
