from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.telegram_identity import (
    telegram_message_external_id,
    telegram_publication_external_id,
)

from .mapping import validate_mapping
from .model import (
    BRIDGE_VERSION,
    BridgeOptions,
    BridgeStats,
    SourceInventory,
    canonical_json,
    row_hash,
    stable_bigint,
    stable_uuid,
)
from .normalize import (
    access_mode,
    as_utc,
    completeness,
    observation_quality,
    parse_json,
    sanitize_evidence,
)
from .source import LEGACY_TABLES, LegacySource
from .target import PostgresTarget
from migration.reverse_sync_format import (
    parse_reverse_publication_envelope,
    parse_reverse_snapshot_envelope,
)


ImportHandler = Callable[[dict[str, Any]], int]


def _without_internal(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("__")}


def _source_pk(table: str, row: Mapping[str, Any]) -> str:
    if table == "post_messages":
        return f"{row['post_id']}:{row['telegram_message_id']}"
    if table == "app_state":
        return str(row["key"])
    if table == "schema_migrations":
        return str(row["version"])
    if "id" in row:
        return str(row["id"])
    return str(row["__source_rowid"])


def _https_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text.startswith("https://") else None


def _safe_error(value: Any) -> dict[str, Any]:
    text = str(value or "")
    return {
        "present": bool(text),
        "length": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
    }


def _safe_raw(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {"present": False}
    parsed = parse_json(value, fallback={})
    if isinstance(parsed, Mapping) and "unparsed_text" in parsed:
        text = str(parsed["unparsed_text"])
        return {
            "present": True,
            "unparsed": True,
            "length": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    return {"present": True, "payload": sanitize_evidence(parsed)}


class BridgeService:
    STREAMS: tuple[str, ...] = (
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

    def __init__(
        self,
        options: BridgeOptions,
        source: LegacySource,
        target: PostgresTarget,
        *,
        snapshot_kind: str,
    ):
        if snapshot_kind not in {"s0", "catch_up", "s_final", "fixture"}:
            raise ValueError("snapshot_kind must be s0, catch_up, s_final or fixture")
        self.options = options
        self.source = source
        self.target = target
        self.snapshot_kind = snapshot_kind
        self.inventory = source.inventory()
        self.source_namespace_uuid = stable_uuid(
            "m-ranked-bridge",
            "source_namespace",
            {"name": options.source_namespace},
        )
        self.batch_id = stable_uuid(
            options.source_namespace,
            "import_batch",
            {
                "source_sha256": self.inventory.source_sha256,
                "snapshot_kind": snapshot_kind,
                "tool_version": BRIDGE_VERSION,
            },
        )
        self.source_snapshot_at = datetime.fromtimestamp(
            source.path.stat().st_mtime, timezone.utc
        )
        self.stats = BridgeStats(
            batch_id=self.batch_id,
            source_sha256=self.inventory.source_sha256,
            schema_version=self.inventory.schema_version,
            dry_run=options.dry_run,
        )
        self.force_full_replay = False
        self.runs: dict[str, UUID] = {
            platform: stable_uuid(
                options.source_namespace,
                "migration_collection_run",
                {"batch_id": str(self.batch_id), "platform": platform},
            )
            for platform in ("telegram", "vk", "max", "rutube")
        }
        self.account_rows = {
            int(row["id"]): row
            for row in self._all_rows("platform_accounts")
        }
        self.channel_rows = {
            int(row["id"]): row for row in self._all_rows("channels")
        }
        self.channels_by_account = {
            int(row["platform_account_id"]): row
            for row in self.channel_rows.values()
            if row.get("platform_account_id") is not None
        }

    def run(self) -> tuple[BridgeStats, dict[str, Any]]:
        errors = validate_mapping(self.source)
        if self.inventory.quick_check != "ok":
            errors.append(f"SQLite quick_check={self.inventory.quick_check}")
        if self.inventory.foreign_key_violations:
            errors.append(
                f"SQLite foreign_key_check={self.inventory.foreign_key_violations}"
            )
        if errors:
            raise RuntimeError("source gate failed: " + "; ".join(errors))
        if self.options.dry_run:
            self.stats.rows_read = sum(table.row_count for table in self.inventory.tables)
            self.stats.rows_by_stream = {
                table.name: table.row_count for table in self.inventory.tables
            }
            self.stats.finish()
            return self.stats, self._dry_run_reconciliation()

        with self.target.transaction():
            previous_status = self.target.prepare_batch(
                batch_id=self.batch_id,
                inventory=self.inventory,
                source_name=self.options.source_namespace,
                snapshot_kind=self.snapshot_kind,
                dry_run=False,
                source_namespace=self.source_namespace_uuid,
                source_snapshot_at=self.source_snapshot_at,
            )
            self._ensure_collection_runs()
        if previous_status == "succeeded" and self.target.namespace_is_current(
            self.source_namespace_uuid, self.batch_id
        ):
            reconciliation = self.reconcile()
            self.stats.rows_read = sum(table.row_count for table in self.inventory.tables)
            self.stats.rows_by_stream = {
                table.name: table.row_count for table in self.inventory.tables
            }
            self.stats.finish()
            return self.stats, reconciliation
        if previous_status == "succeeded":
            # A later catch-up/final batch advanced the identity map. Replaying an
            # older accepted snapshot is the explicit, reversible rollback path.
            self.force_full_replay = True

        try:
            handlers: dict[str, ImportHandler] = {
                "schema_migrations": self._import_schema_migration,
                "app_state": self._import_app_state,
                "institutions": self._import_institution,
                "platform_accounts": self._import_platform_account,
                "channels": self._import_channel,
                "platform_posts": self._import_platform_post,
                "posts": self._import_post,
                "post_messages": self._import_post_message,
            }
            for stream in self.STREAMS:
                if stream not in {table.name for table in self.inventory.tables}:
                    continue
                if stream in {"platform_snapshots", "reaction_snapshots"}:
                    self._import_snapshot_stream(stream)
                else:
                    self._import_stream(stream, handlers[stream])
            with self.target.transaction():
                self._finish_collection_runs("succeeded")
                revision = self.target.latest_batch_revision(self.batch_id)
                if revision is None:
                    revision = self.target.record_revision(
                        self.batch_id,
                        None,
                        "import_completion",
                        ["catalog", "publications", "analytics", "overview", "comparison"],
                    )
                projection_result = self.target.rebuild_core_projections(revision)
                self.stats.projection_rebuild = dict(projection_result)
            reconciliation = self.reconcile()
            status = "succeeded" if reconciliation["gate"]["status"] == "pass" else "failed"
            with self.target.transaction():
                self.target.finish_batch(
                    self.batch_id,
                    status=status,
                    rows_read=self.stats.rows_read,
                    rows_written=self.stats.rows_written,
                    error_summary=(
                        None
                        if status == "succeeded"
                        else "critical reconciliation mismatch"
                    ),
                )
            self.stats.finish()
            return self.stats, reconciliation
        except Exception as exc:
            with self.target.transaction():
                self._finish_collection_runs("failed")
                self.target.finish_batch(
                    self.batch_id,
                    status="failed",
                    rows_read=self.stats.rows_read,
                    rows_written=self.stats.rows_written,
                    error_summary=f"{type(exc).__name__}: {exc}"[:1_000],
                )
            raise

    def _all_rows(self, table: str) -> Iterator[dict[str, Any]]:
        if table not in self.source.table_names():
            return
        for batch in self.source.iter_rows(table, batch_size=self.options.batch_size):
            yield from batch

    def _import_stream(self, stream: str, handler: ImportHandler) -> None:
        after_rowid, processed, completed = self.target.checkpoint(self.batch_id, stream)
        if completed and self.options.resume and not self.force_full_replay:
            self.stats.rows_by_stream[stream] = processed
            return
        if not self.options.resume or self.force_full_replay:
            after_rowid, processed = 0, 0
        last_rowid = after_rowid
        for rows in self.source.iter_rows(
            stream, after_rowid=after_rowid, batch_size=self.options.batch_size
        ):
            writes = 0
            with self.target.transaction():
                for row in rows:
                    writes += handler(row)
                    last_rowid = int(row["__source_rowid"])
                processed += len(rows)
                self.target.record_revision(
                    self.batch_id,
                    None,
                    stream,
                    self._affected_tags(stream),
                )
                self.target.save_checkpoint(
                    self.batch_id,
                    stream,
                    stream,
                    last_rowid,
                    processed,
                    completed=False,
                )
            self.stats.rows_read += len(rows)
            self.stats.rows_written += writes
        with self.target.transaction():
            self.target.save_checkpoint(
                self.batch_id,
                stream,
                stream,
                last_rowid,
                processed,
                completed=True,
            )
        self.stats.rows_by_stream[stream] = processed

    def _import_snapshot_stream(self, stream: str) -> None:
        after_rowid, processed, completed = self.target.checkpoint(self.batch_id, stream)
        if completed and self.options.resume and not self.force_full_replay:
            self.stats.rows_by_stream[stream] = processed
            return
        if not self.options.resume or self.force_full_replay:
            after_rowid, processed = 0, 0
        last_rowid = after_rowid
        for rows in self.source.iter_rows(
            stream, after_rowid=after_rowid, batch_size=self.options.batch_size
        ):
            publication_ids = [
                self._publication_uuid(
                    "platform_posts" if stream == "platform_snapshots" else "posts",
                    int(
                        row["platform_post_id"]
                        if stream == "platform_snapshots"
                        else row["post_id"]
                    ),
                )
                for row in rows
            ]
            contexts = self.target.publication_contexts(publication_ids)
            if len(contexts) != len(set(publication_ids)):
                missing = sorted(str(value) for value in set(publication_ids) - contexts.keys())
                raise RuntimeError(f"snapshots reference missing publications: {missing[:5]}")
            writes = 0
            used_runs: set[UUID] = set()
            with self.target.transaction():
                for row, publication_id in zip(rows, publication_ids, strict=True):
                    published_at, platform = contexts[publication_id]
                    run_id = self.runs[platform]
                    used_runs.add(run_id)
                    self.target.ensure_partition(published_at)
                    writes += self._import_snapshot(
                        stream,
                        row,
                        publication_id,
                        published_at,
                        run_id,
                    )
                    last_rowid = int(row["__source_rowid"])
                processed += len(rows)
                source_run = next(iter(used_runs)) if len(used_runs) == 1 else None
                self.target.record_revision(
                    self.batch_id,
                    source_run,
                    stream,
                    ["publications", "analytics", "overview", "comparison"],
                )
                self.target.save_checkpoint(
                    self.batch_id,
                    stream,
                    stream,
                    last_rowid,
                    processed,
                    completed=False,
                )
            self.stats.rows_read += len(rows)
            self.stats.rows_written += writes
        with self.target.transaction():
            self.target.save_checkpoint(
                self.batch_id,
                stream,
                stream,
                last_rowid,
                processed,
                completed=True,
            )
        self.stats.rows_by_stream[stream] = processed

    @staticmethod
    def _affected_tags(stream: str) -> list[str]:
        if stream in {"institutions", "platform_accounts", "channels"}:
            return ["catalog", "overview"]
        if stream in {"platform_posts", "posts", "post_messages"}:
            return ["publications", "overview", "comparison"]
        return ["operations"]

    def _ensure_collection_runs(self) -> None:
        counts = {platform: 0 for platform in self.runs}
        for row in self.account_rows.values():
            platform = str(row["platform"])
            if platform in counts:
                counts[platform] += 1
        for platform, run_id in self.runs.items():
            self.target.execute(
                """INSERT INTO ingest.collection_run(
                       id, platform, partition_key, collector_version,
                       scheduled_at, started_at, status, account_count,
                       error_count, correlation_id
                   ) VALUES (%s,%s::catalog.platform_code,%s,%s,%s,%s,'running',%s,0,%s)
                   ON CONFLICT (id) DO UPDATE SET
                       status=CASE WHEN ingest.collection_run.status='succeeded'
                                   THEN ingest.collection_run.status ELSE 'running' END,
                       scheduled_at=LEAST(
                           ingest.collection_run.scheduled_at,
                           excluded.scheduled_at
                       ),
                       account_count=excluded.account_count,
                       error_count=0""",
                (
                    run_id,
                    platform,
                    f"migration:{self.options.source_namespace}",
                    f"sqlite-bridge/{BRIDGE_VERSION}",
                    self.source_snapshot_at,
                    self.source_snapshot_at,
                    counts[platform],
                    self.batch_id,
                ),
            )

    def _finish_collection_runs(self, status: str) -> None:
        for run_id in self.runs.values():
            self.target.execute(
                """UPDATE ingest.collection_run
                      SET status=%s::ingest.run_status,
                          completed_at=GREATEST(started_at, transaction_timestamp())
                    WHERE id=%s AND status<>'succeeded'""",
                (status, run_id),
            )

    def _institution_uuid(self, legacy_id: int) -> UUID:
        aliased = self.target.fetchone(
            """SELECT target_uuid FROM catalog.legacy_entity_alias
                WHERE entity_type='institutions' AND legacy_id=%s""",
            (legacy_id,),
        )
        if aliased is not None:
            return UUID(str(aliased[0]))
        return stable_uuid(
            self.options.source_namespace,
            "institution",
            {"source_table": "institutions", "legacy_id": legacy_id},
        )

    def _account_uuid(self, source_table: str, legacy_id: int) -> UUID:
        if source_table == "channels":
            channel = self.channel_rows[legacy_id]
            linked = channel.get("platform_account_id")
            if linked is not None:
                return self._account_uuid("platform_accounts", int(linked))
        aliased = self.target.fetchone(
            """SELECT target_uuid FROM catalog.legacy_entity_alias
                WHERE entity_type=%s AND legacy_id=%s""",
            (source_table, legacy_id),
        )
        if aliased is not None:
            return UUID(str(aliased[0]))
        return stable_uuid(
            self.options.source_namespace,
            "platform_account",
            {"source_table": source_table, "legacy_id": legacy_id},
        )

    def _publication_uuid(self, source_table: str, legacy_id: int) -> UUID:
        aliased = self.target.fetchone(
            """SELECT target_uuid FROM catalog.legacy_entity_alias
                WHERE entity_type=%s AND legacy_id=%s""",
            (source_table, legacy_id),
        )
        if aliased is not None:
            return UUID(str(aliased[0]))
        return stable_uuid(
            self.options.source_namespace,
            "publication",
            {"source_table": source_table, "legacy_id": legacy_id},
        )

    def _import_schema_migration(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        evidence_id = self.target.record_evidence(
            batch_id=self.batch_id,
            source_table="schema_migrations",
            source_pk=str(row["version"]),
            source_row_hash=digest,
            evidence_kind="sqlite_schema_provenance",
            evidence=cleaned,
        )
        stable_evidence_id = self.target.resolve_bigint(
            self.source_namespace_uuid,
            "schema_migrations",
            str(row["version"]),
            "legacy_evidence",
        ) or evidence_id
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="schema_migrations",
            source_pk=str(row["version"]),
            target_type="legacy_evidence",
            target_uuid=None,
            target_bigint=stable_evidence_id,
            natural_key={"version": row["version"]},
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        return 2

    def _import_app_state(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        key = str(row["key"])
        evidence_id = self.target.record_evidence(
            batch_id=self.batch_id,
            source_table="app_state",
            source_pk=key,
            source_row_hash=digest,
            evidence_kind="legacy_operational_state",
            evidence={"key": key, "value": sanitize_evidence(parse_json(row["value"], fallback=None))},
        )
        stable_evidence_id = self.target.resolve_bigint(
            self.source_namespace_uuid,
            "app_state",
            key,
            "legacy_evidence",
        ) or evidence_id
        writes = 1
        known = (
            key in {"last_poll", "next_poll"}
            or key.startswith("poll_last_")
            or any(key.startswith(f"{platform}_poll_last_") for platform in self.runs)
            or key.startswith("telegram_web_last_")
        )
        if known:
            platform = next(
                (candidate for candidate in self.runs if key.startswith(f"{candidate}_")),
                None,
            )
            scope_type = "platform" if platform else "system"
            scope_id = (
                stable_uuid(
                    self.options.source_namespace,
                    "platform_scope",
                    {"platform": platform},
                )
                if platform
                else None
            )
            self.target.execute(
                """INSERT INTO ops_and_admin.operational_checkpoint(
                       id, checkpoint_key, scope_type, scope_id, platform,
                       value, source_observed_at, correlation_id
                   ) VALUES (%s,%s,%s,%s,%s::catalog.platform_code,%s::jsonb,%s,%s)
                   ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
                   DO UPDATE SET value=excluded.value,
                       source_observed_at=excluded.source_observed_at,
                       updated_at=transaction_timestamp(),
                       correlation_id=excluded.correlation_id""",
                (
                    stable_uuid(
                        self.options.source_namespace,
                        "operational_checkpoint",
                        {"key": key},
                    ),
                    key,
                    scope_type,
                    scope_id,
                    platform,
                    json.dumps(parse_json(row["value"], fallback=None), default=str),
                    self.source_snapshot_at,
                    self.batch_id,
                ),
            )
            writes += 1
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="app_state",
            source_pk=key,
            target_type="legacy_evidence",
            target_uuid=None,
            target_bigint=stable_evidence_id,
            natural_key={"key": key},
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        return writes + 1

    def _import_institution(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        legacy_id = int(row["id"])
        target_id = self._institution_uuid(legacy_id)
        created_at = as_utc(row.get("created_at"), fallback=self.source_snapshot_at)
        self.target.execute(
            """INSERT INTO catalog.institution(
                   id, canonical_name, short_name, status, created_at, updated_at
               ) VALUES (%s,%s,%s,'active',%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   canonical_name=excluded.canonical_name,
                   short_name=excluded.short_name,
                   status=excluded.status,
                   updated_at=excluded.updated_at,
                   row_version=catalog.institution.row_version+1""",
            (
                target_id,
                str(row["name"]).strip(),
                str(row["short_name"]).strip() if row.get("short_name") else None,
                created_at,
                self.source_snapshot_at,
            ),
        )
        self.target.record_alias(
            "institutions", legacy_id, target_id, digest, f"/institutions/{legacy_id}"
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="institutions",
            source_pk=str(legacy_id),
            target_type="institution",
            target_uuid=target_id,
            target_bigint=None,
            natural_key={"legacy_id": legacy_id, "name": row["name"]},
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        writes = 3
        for category, prefix in (
            ("social", "m_rating_social"),
            ("telegram", "m_rating_tg"),
            ("vk", "m_rating_vk"),
            ("max", "m_rating_max"),
            ("rutube", "m_rating_rutube"),
        ):
            rank = row.get(f"{prefix}_rank")
            score = row.get(f"{prefix}_score")
            period = str(row.get("m_rating_period") or "legacy-unknown")
            if rank is None and score is None:
                continue
            rating_digest = hashlib.sha256(
                canonical_json(
                    {
                        "institution": legacy_id,
                        "category": category,
                        "period": period,
                        "rank": rank,
                        "score": score,
                    }
                ).encode("utf-8")
            ).hexdigest()
            rating_id = stable_uuid(
                self.options.source_namespace,
                "official_rating_observation",
                {"institution": legacy_id, "category": category, "hash": rating_digest},
            )
            fetched_at = as_utc(
                row.get("m_rating_measured_at"), fallback=self.source_snapshot_at
            )
            self.target.execute(
                """INSERT INTO rating.official_rating_observation(
                       id, institution_id, category, period, rank, score,
                       source_url, source_hash, fetched_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,'https://m-rating.ru/',%s,%s)
                   ON CONFLICT (institution_id, category, period, source_hash) DO NOTHING""",
                (
                    rating_id,
                    target_id,
                    category,
                    period,
                    rank,
                    score,
                    rating_digest,
                    fetched_at,
                ),
            )
            self.target.record_mapping(
                source_namespace=self.source_namespace_uuid,
                source_table="institutions",
                source_pk=str(legacy_id),
                target_type=f"official_rating_observation:{category}",
                target_uuid=rating_id,
                target_bigint=None,
                natural_key={
                    "institution_id": str(target_id),
                    "category": category,
                    "period": period,
                    "source_hash": rating_digest,
                },
                source_row_hash=digest,
                batch_id=self.batch_id,
            )
            writes += 2
        return writes

    def _upsert_account(
        self,
        *,
        target_id: UUID,
        institution_id: UUID,
        platform: str,
        canonical_external_id: str,
        username: Any,
        title: Any,
        url: Any,
        raw_access_mode: Any,
        enabled: Any,
        created_at: datetime,
        run_id: UUID,
        native_id: Any,
    ) -> int:
        safe_url = _https_or_none(url)
        self.target.execute(
            """INSERT INTO catalog.platform_account(
                   id, institution_id, platform, canonical_external_id,
                   current_username, current_title, current_url, access_mode,
                   enabled, created_at, updated_at
               ) VALUES (%s,%s,%s::catalog.platform_code,%s,%s,%s,%s,
                         %s::catalog.access_mode,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   institution_id=excluded.institution_id,
                   canonical_external_id=excluded.canonical_external_id,
                   current_username=excluded.current_username,
                   current_title=excluded.current_title,
                   current_url=excluded.current_url,
                   access_mode=excluded.access_mode,
                   enabled=excluded.enabled,
                   updated_at=excluded.updated_at,
                   row_version=catalog.platform_account.row_version+1""",
            (
                target_id,
                institution_id,
                platform,
                canonical_external_id,
                username,
                title,
                safe_url,
                access_mode(platform, raw_access_mode),
                bool(enabled),
                created_at,
                self.source_snapshot_at,
            ),
        )
        self.target.execute(
            """INSERT INTO catalog.account_identity_history(
                   platform_account_id, username, title, url, valid_from, source_run_id
               ) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (platform_account_id) WHERE valid_to IS NULL
               DO UPDATE SET username=excluded.username, title=excluded.title,
                   url=excluded.url, source_run_id=excluded.source_run_id""",
            (target_id, username, title, safe_url, created_at, run_id),
        )
        writes = 2
        if native_id is not None and str(native_id).strip():
            self.target.execute(
                """INSERT INTO catalog.account_external_identity(
                       platform_account_id, identity_namespace, external_id,
                       valid_from, verified_at, source_run_id
                   ) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (platform_account_id, identity_namespace)
                       WHERE valid_to IS NULL
                   DO UPDATE SET external_id=excluded.external_id,
                       verified_at=excluded.verified_at,
                       source_run_id=excluded.source_run_id""",
                (
                    target_id,
                    f"{platform}:native_id",
                    str(native_id),
                    created_at,
                    self.source_snapshot_at,
                    run_id,
                ),
            )
            writes += 1
        return writes

    def _insert_account_snapshot(
        self,
        *,
        account_id: UUID,
        platform: str,
        row: Mapping[str, Any],
        source_table: str,
        digest: str,
    ) -> int:
        measured_at = row.get("subscriber_measured_at")
        if not measured_at:
            return 0
        if row.get("subscriber_count") is None and row.get("subscriber_count_display") is None:
            return 0
        observed_at = as_utc(measured_at)
        collected_at = max(observed_at, self.source_snapshot_at)
        fingerprint = hashlib.sha256(
            f"{source_table}:{digest}:subscriber".encode("utf-8")
        ).hexdigest()
        existing = self.target.fetchone(
            """SELECT id FROM ingest.account_metric_snapshot
                WHERE platform_account_id=%s AND observed_at=%s
                  AND source_fingerprint=%s""",
            (account_id, observed_at, fingerprint),
        )
        snapshot_id = (
            int(existing[0])
            if existing
            else stable_bigint(
                self.options.source_namespace,
                "account_metric_snapshot",
                {"source_table": source_table, "source_pk": _source_pk(source_table, row)},
            )
        )
        self.target.execute(
            """INSERT INTO ingest.account_metric_snapshot(
                   id, platform_account_id, collection_run_id, observed_at, collected_at,
                   subscriber_count, subscriber_display, quality, source_fingerprint,
                   created_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::ingest.observation_quality,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   collection_run_id=excluded.collection_run_id,
                   observed_at=excluded.observed_at,
                   collected_at=excluded.collected_at,
                   subscriber_count=excluded.subscriber_count,
                   subscriber_display=excluded.subscriber_display,
                   quality=excluded.quality,
                   source_fingerprint=excluded.source_fingerprint,
                   created_at=excluded.created_at
               WHERE ingest.account_metric_snapshot.platform_account_id=
                     excluded.platform_account_id""",
            (
                snapshot_id,
                account_id,
                self.runs[platform],
                observed_at,
                collected_at,
                row.get("subscriber_count"),
                row.get("subscriber_count_display"),
                observation_quality(row.get("data_quality"), default="unknown"),
                fingerprint,
                self.source_snapshot_at,
            ),
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table=source_table,
            source_pk=_source_pk(source_table, row),
            target_type="account_metric_snapshot",
            target_uuid=None,
            target_bigint=snapshot_id,
            natural_key={
                "platform_account_id": str(account_id),
                "observed_at": observed_at.isoformat(),
            },
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        return 2

    def _upsert_account_checkpoint(
        self,
        account_id: UUID,
        platform: str,
        key: str,
        value: Any,
        observed_at: Any,
    ) -> int:
        if value is None and observed_at is None:
            return 0
        checkpoint_id = stable_uuid(
            self.options.source_namespace,
            "operational_checkpoint",
            {"account": str(account_id), "key": key},
        )
        self.target.execute(
            """INSERT INTO ops_and_admin.operational_checkpoint(
                   id, checkpoint_key, scope_type, scope_id, platform,
                   value, source_observed_at, correlation_id
               ) VALUES (%s,%s,'account',%s,%s::catalog.platform_code,%s::jsonb,%s,%s)
               ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
               DO UPDATE SET value=excluded.value,
                   source_observed_at=excluded.source_observed_at,
                   updated_at=transaction_timestamp(),
                   correlation_id=excluded.correlation_id""",
            (
                checkpoint_id,
                key,
                account_id,
                platform,
                json.dumps(value, default=str),
                as_utc(observed_at, fallback=self.source_snapshot_at),
                self.batch_id,
            ),
        )
        return 1

    def _import_platform_account(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        legacy_id = int(row["id"])
        platform = str(row["platform"])
        target_id = self._account_uuid("platform_accounts", legacy_id)
        institution_id = self._institution_uuid(int(row["institution_id"]))
        created_at = as_utc(row.get("added_at"), fallback=self.source_snapshot_at)
        canonical = str(row.get("native_id") or row.get("external_key") or f"legacy:{legacy_id}")
        writes = self._upsert_account(
            target_id=target_id,
            institution_id=institution_id,
            platform=platform,
            canonical_external_id=canonical,
            username=row.get("username"),
            title=row.get("title"),
            url=row.get("url"),
            raw_access_mode=row.get("access_mode"),
            enabled=row.get("enabled"),
            created_at=created_at,
            run_id=self.runs[platform],
            native_id=row.get("native_id"),
        )
        self.target.record_alias(
            "platform_accounts",
            legacy_id,
            target_id,
            digest,
            f"/platform-accounts/{legacy_id}",
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="platform_accounts",
            source_pk=str(legacy_id),
            target_type="platform_account",
            target_uuid=target_id,
            target_bigint=None,
            natural_key={"platform": platform, "canonical_external_id": canonical},
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        writes += 2
        if platform != "telegram" or legacy_id not in self.channels_by_account:
            writes += self._insert_account_snapshot(
                account_id=target_id,
                platform=platform,
                row=row,
                source_table="platform_accounts",
                digest=digest,
            )
        writes += self._upsert_account_checkpoint(
            target_id,
            platform,
            "last_checked_at",
            row.get("last_checked_at"),
            row.get("last_checked_at"),
        )
        if row.get("last_error"):
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table="platform_accounts",
                source_pk=str(legacy_id),
                source_row_hash=digest,
                evidence_kind="sanitized_last_error",
                evidence=_safe_error(row.get("last_error")),
            )
            writes += 1
        return writes

    def _import_channel(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        legacy_id = int(row["id"])
        if row.get("institution_id") is None:
            raise RuntimeError(f"channel {legacy_id} has no institution_id")
        target_id = self._account_uuid("channels", legacy_id)
        institution_id = self._institution_uuid(int(row["institution_id"]))
        created_at = as_utc(row.get("added_at"), fallback=self.source_snapshot_at)
        username = str(row["username"])
        writes = self._upsert_account(
            target_id=target_id,
            institution_id=institution_id,
            platform="telegram",
            canonical_external_id=str(row.get("telegram_id") or username.casefold()),
            username=username,
            title=row.get("title"),
            url=f"https://t.me/{username}",
            raw_access_mode=("mtproto" if row.get("telegram_id") else "public_web"),
            enabled=row.get("enabled"),
            created_at=created_at,
            run_id=self.runs["telegram"],
            native_id=row.get("telegram_id"),
        )
        self.target.record_alias(
            "channels", legacy_id, target_id, digest, f"/channels/{legacy_id}"
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="channels",
            source_pk=str(legacy_id),
            target_type="platform_account",
            target_uuid=target_id,
            target_bigint=None,
            natural_key={"platform": "telegram", "username": username.casefold()},
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        writes += 2
        writes += self._insert_account_snapshot(
            account_id=target_id,
            platform="telegram",
            row=row,
            source_table="channels",
            digest=digest,
        )
        writes += self._upsert_account_checkpoint(
            target_id,
            "telegram",
            "last_seen_message_id",
            int(row.get("last_seen_message_id") or 0),
            row.get("last_checked_at"),
        )
        writes += self._upsert_account_checkpoint(
            target_id,
            "telegram",
            "last_checked_at",
            row.get("last_checked_at"),
            row.get("last_checked_at"),
        )
        if row.get("last_error"):
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table="channels",
                source_pk=str(legacy_id),
                source_row_hash=digest,
                evidence_kind="sanitized_last_error",
                evidence=_safe_error(row.get("last_error")),
            )
            writes += 1
        rating_rank = row.get("m_rating_tg_rank")
        rating_score = row.get("m_rating_tg_score")
        if rating_rank is not None or rating_score is not None:
            period = str(row.get("m_rating_period") or "legacy-unknown")
            rating_digest = hashlib.sha256(
                canonical_json(
                    {
                        "source_table": "channels",
                        "channel": legacy_id,
                        "institution": int(row["institution_id"]),
                        "category": "telegram",
                        "period": period,
                        "rank": rating_rank,
                        "score": rating_score,
                    }
                ).encode("utf-8")
            ).hexdigest()
            rating_id = stable_uuid(
                self.options.source_namespace,
                "official_rating_observation",
                {"source_table": "channels", "legacy_id": legacy_id},
            )
            self.target.execute(
                """INSERT INTO rating.official_rating_observation(
                       id, institution_id, category, period, rank, score,
                       source_url, source_hash, fetched_at
                   ) VALUES (%s,%s,'telegram',%s,%s,%s,'https://m-rating.ru/',%s,%s)
                   ON CONFLICT (institution_id, category, period, source_hash)
                   DO NOTHING""",
                (
                    rating_id,
                    institution_id,
                    period,
                    rating_rank,
                    rating_score,
                    rating_digest,
                    as_utc(
                        row.get("m_rating_measured_at"),
                        fallback=self.source_snapshot_at,
                    ),
                ),
            )
            self.target.record_mapping(
                source_namespace=self.source_namespace_uuid,
                source_table="channels",
                source_pk=str(legacy_id),
                target_type="official_rating_observation:telegram",
                target_uuid=rating_id,
                target_bigint=None,
                natural_key={
                    "institution_id": str(institution_id),
                    "category": "telegram",
                    "period": period,
                    "source_hash": rating_digest,
                },
                source_row_hash=digest,
                batch_id=self.batch_id,
            )
            writes += 2
        return writes

    def _insert_content_group(
        self, account_id: UUID, grouped_id: Any, created_at: datetime
    ) -> UUID | None:
        if grouped_id is None:
            return None
        group_id = stable_uuid(
            self.options.source_namespace,
            "telegram_album",
            {"account": str(account_id), "grouped_id": str(grouped_id)},
        )
        self.target.execute(
            """INSERT INTO ingest.content_group(id, group_type, created_at)
               VALUES (%s,'telegram_album',%s) ON CONFLICT (id) DO NOTHING""",
            (group_id, created_at),
        )
        return group_id

    def _upsert_publication(
        self,
        *,
        target_id: UUID,
        account_id: UUID,
        content_group_id: UUID | None,
        row: Mapping[str, Any],
        quality_flags: Mapping[str, Any],
    ) -> None:
        published_at = as_utc(row["published_at"])
        discovered_at = as_utc(row["discovered_at"])
        created_at = as_utc(row.get("created_at"), fallback=discovered_at)
        self.target.execute(
            """INSERT INTO ingest.publication(
                   id, primary_account_id, content_group_id, published_at,
                   discovered_at, first_observation_age_seconds, publication_type,
                   is_repost, history_completeness, synthetic_baseline_allowed,
                   quality_flags, deleted_at, created_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                         %s::ingest.history_completeness,%s,%s::jsonb,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   primary_account_id=excluded.primary_account_id,
                   content_group_id=excluded.content_group_id,
                   published_at=excluded.published_at,
                   discovered_at=excluded.discovered_at,
                   first_observation_age_seconds=excluded.first_observation_age_seconds,
                   publication_type=excluded.publication_type,
                   is_repost=excluded.is_repost,
                   history_completeness=excluded.history_completeness,
                   synthetic_baseline_allowed=excluded.synthetic_baseline_allowed,
                   quality_flags=excluded.quality_flags,
                   deleted_at=excluded.deleted_at""",
            (
                target_id,
                account_id,
                content_group_id,
                published_at,
                discovered_at,
                row.get("first_observation_age_seconds"),
                str(row.get("post_type") or "unknown"),
                bool(row.get("is_repost")),
                completeness(row),
                bool(row.get("baseline_from_publication")),
                json.dumps(dict(quality_flags), sort_keys=True),
                as_utc(row["deleted_at"]) if row.get("deleted_at") else None,
                created_at,
            ),
        )

    def _insert_publication_identity(
        self,
        *,
        publication_id: UUID,
        account_id: UUID,
        external_id: str,
        source_external_id: Any,
        role: str,
        public_url: Any,
    ) -> int:
        row = self.target.fetchone(
            """INSERT INTO ingest.publication_identity(
                   publication_id, platform_account_id, external_id,
                   source_external_id, role, public_url
               ) VALUES (%s,%s,%s,%s,%s::ingest.publication_account_role,%s)
               ON CONFLICT (platform_account_id, external_id) DO UPDATE SET
                   source_external_id=excluded.source_external_id,
                   role=excluded.role,
                   public_url=excluded.public_url
               WHERE ingest.publication_identity.publication_id=excluded.publication_id
               RETURNING id""",
            (
                publication_id,
                account_id,
                external_id,
                source_external_id,
                role,
                _https_or_none(public_url),
            ),
        )
        if row is None:
            raise RuntimeError(f"external identity remap rejected: {account_id}/{external_id}")
        return int(row[0])

    def _heal_legacy_telegram_message_identity(
        self,
        *,
        publication_id: UUID,
        account_id: UUID,
        message_id: Any,
        role: str,
    ) -> None:
        """Upgrade bridge 1.0 bare Telegram IDs without changing identity IDs."""

        bare_id = str(int(message_id))
        canonical_id = telegram_message_external_id(bare_id)
        canonical = self.target.fetchone(
            """SELECT publication_id
                 FROM ingest.publication_identity
                WHERE platform_account_id=%s AND external_id=%s""",
            (account_id, canonical_id),
        )
        if canonical is not None and UUID(str(canonical[0])) != publication_id:
            raise RuntimeError(
                f"canonical Telegram identity is already owned: {account_id}/{canonical_id}"
            )
        if canonical is None:
            self.target.execute(
                """UPDATE ingest.publication_identity
                      SET external_id=%s,
                          role=%s::ingest.publication_account_role
                    WHERE publication_id=%s
                      AND platform_account_id=%s
                      AND external_id=%s""",
                (canonical_id, role, publication_id, account_id, bare_id),
            )
        else:
            # A previously interrupted 1.1 replay can leave the old alias next
            # to the canonical one. Keep it non-primary for compatibility; the
            # reverse adapter rejects/ignores unnamespaced target identities.
            self.target.execute(
                """UPDATE ingest.publication_identity
                      SET role='source'::ingest.publication_account_role
                    WHERE publication_id=%s
                      AND platform_account_id=%s
                      AND external_id=%s""",
                (publication_id, account_id, bare_id),
            )

    def _assert_single_primary_identity(self, publication_id: UUID) -> None:
        row = self.target.fetchone(
            """SELECT count(*)
                 FROM ingest.publication_identity
                WHERE publication_id=%s AND role='primary'""",
            (publication_id,),
        )
        if row is None or int(row[0]) != 1:
            raise RuntimeError(
                f"publication must have exactly one primary identity: {publication_id}"
            )

    def _insert_deletion_observation(
        self,
        *,
        publication_id: UUID,
        run_id: UUID,
        row: Mapping[str, Any],
    ) -> int:
        count = int(row.get("missing_check_count") or 0)
        if not count and not row.get("deleted_at") and not row.get("missing_last_checked_at"):
            return 0
        observed_at = as_utc(
            row.get("missing_last_checked_at") or row.get("deleted_at"),
            fallback=self.source_snapshot_at,
        )
        outcome = "confirmed_deleted" if row.get("deleted_at") else "missing"
        self.target.execute(
            """INSERT INTO ingest.deletion_observation(
                   publication_id, collection_run_id, observed_at,
                   outcome, reason_code, consecutive_missing
               ) VALUES (%s,%s,%s,%s::ingest.deletion_probe_outcome,%s,%s)
               ON CONFLICT (publication_id, collection_run_id, observed_at)
               DO UPDATE SET outcome=excluded.outcome,
                   reason_code=excluded.reason_code,
                   consecutive_missing=excluded.consecutive_missing""",
            (
                publication_id,
                run_id,
                observed_at,
                outcome,
                str(row.get("missing_reason") or "legacy_unknown"),
                count,
            ),
        )
        return 1

    def _import_platform_post(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        legacy_id = int(row["id"])
        target_id = self._publication_uuid("platform_posts", legacy_id)
        account_legacy_id = int(row["platform_account_id"])
        account_id = self._account_uuid("platform_accounts", account_legacy_id)
        account = self.account_rows[account_legacy_id]
        platform = str(account["platform"])
        reverse_envelope = parse_reverse_publication_envelope(row.get("raw_json"))
        if reverse_envelope is not None:
            if reverse_envelope.legacy_table != "platform_posts":
                raise RuntimeError(
                    "reverse-sync publication table does not match source stream"
                )
            if reverse_envelope.publication_id != target_id:
                raise RuntimeError(
                    "reverse-sync publication identity does not match legacy alias"
                )
            primary = next(
                identity
                for identity in reverse_envelope.identities
                if identity["role"] == "primary"
            )
            if (
                primary["external_id"] != str(row["external_id"])
                or primary.get("source_external_id") != row.get("source_external_id")
                or primary.get("public_url") != _https_or_none(row.get("url"))
            ):
                raise RuntimeError(
                    "reverse-sync publication envelope disagrees with legacy columns"
                )
            quality_flags = dict(reverse_envelope.quality_flags)
            expected_joint = bool(
                quality_flags.get("joint_post")
                or quality_flags.get("legacy_is_joint")
            )
            expected_authors = int(
                quality_flags.get(
                    "additional_author_count",
                    quality_flags.get("legacy_additional_author_count", 0),
                )
                or 0
            )
            if expected_joint != bool(row.get("is_joint")) or expected_authors != int(
                row.get("additional_author_count") or 0
            ):
                raise RuntimeError(
                    "reverse-sync publication flags disagree with legacy columns"
                )
            identities = reverse_envelope.identities
        else:
            quality_flags = {
                "legacy_is_joint": bool(row.get("is_joint")),
                "legacy_additional_author_count": int(
                    row.get("additional_author_count") or 0
                ),
            }
            identities = ({
                "external_id": str(row["external_id"]),
                "source_external_id": row.get("source_external_id"),
                "role": "primary",
                "public_url": _https_or_none(row.get("url")),
            },)
        self._upsert_publication(
            target_id=target_id,
            account_id=account_id,
            content_group_id=None,
            row=row,
            quality_flags=quality_flags,
        )
        for identity in identities:
            self._insert_publication_identity(
                publication_id=target_id,
                account_id=account_id,
                external_id=str(identity["external_id"]),
                source_external_id=identity.get("source_external_id"),
                role=str(identity["role"]),
                public_url=identity.get("public_url"),
            )
        self._assert_single_primary_identity(target_id)
        self.target.record_alias(
            "platform_posts",
            legacy_id,
            target_id,
            digest,
            f"/platform-posts/{legacy_id}",
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="platform_posts",
            source_pk=str(legacy_id),
            target_type="publication",
            target_uuid=target_id,
            target_bigint=None,
            natural_key={
                "platform_account_id": account_legacy_id,
                "external_id": row["external_id"],
            },
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        writes = 3 + len(identities) + self._insert_deletion_observation(
            publication_id=target_id, run_id=self.runs[platform], row=row
        )
        if row.get("raw_json"):
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table="platform_posts",
                source_pk=str(legacy_id),
                source_row_hash=digest,
                evidence_kind="raw_json",
                evidence=_safe_raw(row.get("raw_json")),
            )
            writes += 1
        if row.get("is_joint") or row.get("additional_author_count"):
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table="platform_posts",
                source_pk=str(legacy_id),
                source_row_hash=digest,
                evidence_kind="joint_post_lineage",
                evidence={
                    "is_joint": bool(row.get("is_joint")),
                    "additional_author_count": int(row.get("additional_author_count") or 0),
                    "source_external_id": row.get("source_external_id"),
                },
            )
            writes += 1
        return writes

    def _import_post(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        legacy_id = int(row["id"])
        target_id = self._publication_uuid("posts", legacy_id)
        channel_id = int(row["channel_id"])
        account_id = self._account_uuid("channels", channel_id)
        created_at = as_utc(row.get("created_at"), fallback=self.source_snapshot_at)
        group_id = self._insert_content_group(
            account_id, row.get("telegram_grouped_id"), created_at
        )
        ambiguity = bool(row.get("ambiguous_album_reactions"))
        existing = self.target.fetchone(
            "SELECT quality_flags FROM ingest.publication WHERE id=%s",
            (target_id,),
        )
        existing_flags = existing[0] if existing is not None else None
        if existing_flags is not None and not isinstance(existing_flags, Mapping):
            raise RuntimeError("target Telegram quality flags are not an object")
        preserved_keys = tuple(
            key
            for key in ("ambiguous_album_reactions", "ambiguous_reactions")
            if isinstance(existing_flags, Mapping) and key in existing_flags
        )
        quality_flags = {
            key: ambiguity
            for key in (preserved_keys or ("ambiguous_album_reactions",))
        }
        self._upsert_publication(
            target_id=target_id,
            account_id=account_id,
            content_group_id=group_id,
            row=row,
            quality_flags=quality_flags,
        )
        channel = self.channel_rows[channel_id]
        is_album = row.get("telegram_grouped_id") is not None
        self._heal_legacy_telegram_message_identity(
            publication_id=target_id,
            account_id=account_id,
            message_id=row["telegram_message_id"],
            role="album_member" if is_album else "primary",
        )
        primary_external_id = telegram_publication_external_id(
            row["telegram_message_id"], row.get("telegram_grouped_id")
        )
        identity_id = self._insert_publication_identity(
            publication_id=target_id,
            account_id=account_id,
            external_id=primary_external_id,
            source_external_id=None,
            role="primary",
            public_url=f"https://t.me/{channel['username']}/{row['telegram_message_id']}",
        )
        self._assert_single_primary_identity(target_id)
        self.target.record_alias(
            "posts", legacy_id, target_id, digest, f"/posts/{legacy_id}"
        )
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="posts",
            source_pk=str(legacy_id),
            target_type="publication",
            target_uuid=target_id,
            target_bigint=None,
            natural_key={
                "channel_id": channel_id,
                "logical_key": row["logical_key"],
                "telegram_message_id": row["telegram_message_id"],
                "target_external_id": primary_external_id,
            },
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        writes = 4 + (1 if group_id else 0)
        writes += self._insert_deletion_observation(
            publication_id=target_id,
            run_id=self.runs["telegram"],
            row=row,
        )
        if row.get("telegram_grouped_id") is not None:
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table="posts",
                source_pk=str(legacy_id),
                source_row_hash=digest,
                evidence_kind="telegram_album",
                evidence={
                    "logical_key": row["logical_key"],
                    "telegram_grouped_id": row["telegram_grouped_id"],
                    "primary_identity_id": identity_id,
                },
            )
            writes += 1
        return writes

    def _import_post_message(self, row: dict[str, Any]) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        publication_legacy_id = int(row["post_id"])
        publication_id = self._publication_uuid("posts", publication_legacy_id)
        # Resolve the owning channel/account with one bounded source lookup per member.
        with self.source.connect() as connection:
            post = connection.execute(
                """SELECT channel_id, telegram_message_id, telegram_grouped_id
                     FROM posts WHERE id=?""",
                (publication_legacy_id,),
            ).fetchone()
        if post is None:
            raise RuntimeError(f"album member references missing post {publication_legacy_id}")
        account_id = self._account_uuid("channels", int(post["channel_id"]))
        message_id = str(row["telegram_message_id"])
        external_id = telegram_message_external_id(message_id)
        is_album = post["telegram_grouped_id"] is not None
        role = "album_member" if is_album else "primary"
        self._heal_legacy_telegram_message_identity(
            publication_id=publication_id,
            account_id=account_id,
            message_id=message_id,
            role=role,
        )
        identity_id = self._insert_publication_identity(
            publication_id=publication_id,
            account_id=account_id,
            external_id=external_id,
            source_external_id=None,
            role=role,
            public_url=f"https://t.me/{self.channel_rows[int(post['channel_id'])]['username']}/{message_id}",
        )
        source_pk = _source_pk("post_messages", row)
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table="post_messages",
            source_pk=source_pk,
            target_type="publication_identity",
            target_uuid=None,
            target_bigint=identity_id,
            natural_key={
                "post_id": publication_legacy_id,
                "telegram_message_id": message_id,
                "target_external_id": external_id,
            },
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        self._assert_single_primary_identity(publication_id)
        return 2

    def _import_snapshot(
        self,
        stream: str,
        row: dict[str, Any],
        publication_id: UUID,
        published_at: datetime,
        run_id: UUID,
    ) -> int:
        cleaned = _without_internal(row)
        digest = row_hash(cleaned)
        source_pk = str(row["id"])
        raw_field = (
            row.get("raw_state_json")
            if stream == "reaction_snapshots"
            else row.get("raw_json")
        )
        reverse_envelope = parse_reverse_snapshot_envelope(raw_field)
        if stream == "reaction_snapshots":
            views = row.get("views_count")
            reactions = row.get("total_reactions")
            comments = row.get("comments_count")
            shares = None
            interval_uncertain = bool(row.get("interval_uncertain"))
            synthetic = bool(row.get("synthetic"))
        else:
            views = row.get("views_count")
            reactions = row.get("reactions_count")
            comments = row.get("comments_count")
            shares = row.get("shares_count")
            interval_uncertain = False
            synthetic = False
        month = published_at.astimezone(timezone.utc).date().replace(day=1)
        if reverse_envelope is not None:
            if reverse_envelope.legacy_table != stream:
                raise RuntimeError("reverse-sync snapshot table does not match source stream")
            if reverse_envelope.publication_id != publication_id:
                raise RuntimeError("reverse-sync snapshot publication identity mismatch")
            if reverse_envelope.published_month != month:
                raise RuntimeError("reverse-sync snapshot published month mismatch")
            if stream == "reaction_snapshots" and (
                reverse_envelope.interval_uncertain != interval_uncertain
                or reverse_envelope.synthetic != synthetic
            ):
                raise RuntimeError("reverse-sync Telegram snapshot flags mismatch")
            snapshot_id = reverse_envelope.snapshot_id
            fingerprint = reverse_envelope.source_fingerprint
            quality = reverse_envelope.quality
            collected_at = reverse_envelope.collected_at
            created_at = reverse_envelope.created_at
            interval_uncertain = reverse_envelope.interval_uncertain
            synthetic = reverse_envelope.synthetic
            metric_semantics_version = reverse_envelope.metric_semantics_version
            capability_version = reverse_envelope.capability_version
        else:
            snapshot_id = stable_bigint(
                self.options.source_namespace,
                "publication_metric_snapshot",
                {"source_table": stream, "source_pk": source_pk},
            )
            fingerprint = hashlib.sha256(
                f"{stream}:{source_pk}:{digest}".encode("utf-8")
            ).hexdigest()
            quality = "unknown"
            metric_semantics_version = 1
            capability_version = 1
        observed_at = as_utc(row["measured_at"])
        if reverse_envelope is None:
            created_at = as_utc(row.get("created_at"), fallback=self.source_snapshot_at)
            collected_at = max(observed_at, created_at)
        self.target.execute(
            """INSERT INTO ingest.publication_metric_snapshot(
                   published_month, id, publication_id, collection_run_id,
                   observed_at, collected_at, age_seconds, sampling_bucket, views_count,
                   reactions_count, comments_count, shares_count, quality,
                   interval_uncertain, synthetic, metric_semantics_version,
                   capability_version, source_fingerprint, created_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                         %s::ingest.observation_quality,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (published_month, publication_id, sampling_bucket)
               DO UPDATE SET
                   observed_at=excluded.observed_at,
                   collected_at=excluded.collected_at,
                   age_seconds=excluded.age_seconds,
                   views_count=excluded.views_count,
                   reactions_count=excluded.reactions_count,
                   comments_count=excluded.comments_count,
                   shares_count=excluded.shares_count,
                   interval_uncertain=excluded.interval_uncertain,
                   synthetic=excluded.synthetic,
                   quality=excluded.quality,
                   metric_semantics_version=excluded.metric_semantics_version,
                   capability_version=excluded.capability_version,
                   source_fingerprint=excluded.source_fingerprint
               WHERE ingest.publication_metric_snapshot.id=excluded.id""",
            (
                month,
                snapshot_id,
                publication_id,
                run_id,
                observed_at,
                collected_at,
                int(row["age_seconds"]),
                int(row["measurement_bucket"]),
                views,
                reactions,
                comments,
                shares,
                quality,
                interval_uncertain,
                synthetic,
                metric_semantics_version,
                capability_version,
                fingerprint,
                created_at,
            ),
        )
        writes = 1
        if stream == "reaction_snapshots":
            breakdown = parse_json(row.get("reactions_json"), fallback={})
            if not isinstance(breakdown, Mapping):
                raise RuntimeError(f"reaction breakdown is not an object for snapshot {source_pk}")
            for reaction_key, count in breakdown.items():
                self.target.execute(
                    """INSERT INTO ingest.reaction_breakdown(
                           snapshot_published_month, snapshot_id, reaction_key, reaction_count
                       ) VALUES (%s,%s,%s,%s)
                       ON CONFLICT (snapshot_published_month, snapshot_id, reaction_key)
                       DO UPDATE SET reaction_count=excluded.reaction_count""",
                    (month, snapshot_id, str(reaction_key), int(count)),
                )
                writes += 1
            derived = {
                key: row.get(key)
                for key in (
                    "delta_total",
                    "delta_by_reaction_json",
                    "delta_seconds",
                    "rate_per_hour",
                    "delta_comments",
                    "delta_views",
                    "spike",
                )
            }
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table=stream,
                source_pk=source_pk,
                source_row_hash=digest,
                evidence_kind="legacy_derived_metrics",
                evidence=sanitize_evidence(derived),
            )
            writes += 1
            if row.get("raw_state_json"):
                self.target.record_evidence(
                    batch_id=self.batch_id,
                    source_table=stream,
                    source_pk=source_pk,
                    source_row_hash=digest,
                    evidence_kind="raw_state_json",
                    evidence=_safe_raw(row.get("raw_state_json")),
                )
                writes += 1
        elif row.get("raw_json"):
            self.target.record_evidence(
                batch_id=self.batch_id,
                source_table=stream,
                source_pk=source_pk,
                source_row_hash=digest,
                evidence_kind="raw_json",
                evidence=_safe_raw(row.get("raw_json")),
            )
            writes += 1
        self.target.record_mapping(
            source_namespace=self.source_namespace_uuid,
            source_table=stream,
            source_pk=source_pk,
            target_type="publication_metric_snapshot",
            target_uuid=None,
            target_bigint=snapshot_id,
            natural_key={
                "publication_id": str(publication_id),
                "published_month": month.isoformat(),
                "sampling_bucket": int(row["measurement_bucket"]),
            },
            source_row_hash=digest,
            batch_id=self.batch_id,
        )
        return writes + 1

    def reconcile(self) -> dict[str, Any]:
        mismatches: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []

        def add_check(
            check_name: str,
            scope: str,
            expected: Any,
            actual: Any,
            *,
            source_table: str | None,
            target_table: str | None,
            critical: bool = True,
            details: Mapping[str, Any] | None = None,
        ) -> None:
            status = "pass" if actual == expected else "fail"
            check = {
                "check": check_name,
                "scope": scope,
                "expected": expected,
                "actual": actual,
                "status": status,
                "critical": critical,
            }
            if details:
                check["details"] = dict(details)
            checks.append(check)
            if status == "fail" and critical:
                mismatches.append(check)
            self.target.record_reconciliation(
                batch_id=self.batch_id,
                check_name=check_name,
                scope=scope,
                source_table=source_table,
                target_table=target_table,
                status=status,
                critical=critical,
                expected=expected,
                actual=actual,
                details=details,
            )

        for table in self.inventory.tables:
            actual = self.target.mapped_count(
                self.source_namespace_uuid, self.batch_id, table.name
            )
            expected = table.row_count
            add_check(
                "mapped_row_count",
                table.name,
                expected,
                actual,
                source_table=table.name,
                target_table="migration.legacy_identity_map",
                details={"source_canonical_hash": table.canonical_hash},
            )

            expected_hashes: dict[str, str] = {}
            for row in self._all_rows(table.name):
                expected_hashes[_source_pk(table.name, row)] = row_hash(
                    _without_internal(row)
                )
            actual_hashes = self.target.mapping_hashes(
                self.source_namespace_uuid, self.batch_id, table.name
            )
            expected_digest = hashlib.sha256(
                canonical_json(sorted(expected_hashes.items())).encode("utf-8")
            ).hexdigest()
            actual_digest = hashlib.sha256(
                canonical_json(sorted(actual_hashes.items())).encode("utf-8")
            ).hexdigest()
            changed = sorted(
                key
                for key in expected_hashes.keys() & actual_hashes.keys()
                if expected_hashes[key] != actual_hashes[key]
            )
            missing = sorted(expected_hashes.keys() - actual_hashes.keys())
            extra = sorted(actual_hashes.keys() - expected_hashes.keys())
            add_check(
                "source_row_hashes",
                table.name,
                {"rows": len(expected_hashes), "sha256": expected_digest},
                {"rows": len(actual_hashes), "sha256": actual_digest},
                source_table=table.name,
                target_table="migration.legacy_identity_map",
                details={
                    "missing_sample": missing[:10],
                    "extra_sample": extra[:10],
                    "changed_sample": changed[:10],
                },
            )

        stale = self.target.fetchone(
            """SELECT COUNT(*) FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND last_seen_batch_id<>%s""",
            (self.source_namespace_uuid, self.batch_id),
        )
        stale_count = int(stale[0]) if stale else 0
        add_check(
            "source_rows_missing_since_prior_batch",
            "all",
            0,
            stale_count,
            source_table=None,
            target_table="migration.legacy_identity_map",
            details={"policy": "never delete automatically; operator must explain hard delete"},
        )

        integrity = self.target.integrity_summary(
            self.source_namespace_uuid, self.batch_id
        )
        for name, actual in integrity.items():
            add_check(
                "target_integrity",
                name,
                0,
                actual,
                source_table=None,
                target_table=(
                    "ingest.publication_metric_snapshot_default"
                    if name == "default_snapshot_partition_rows"
                    else "ingest.reaction_breakdown_default"
                    if name == "default_reaction_partition_rows"
                    else "migration.legacy_identity_map"
                ),
            )

        totals = self.inventory.totals
        snapshot_count_keys = {
            "reactions_null",
            "reactions_zero",
            "views_null",
            "views_zero",
            "comments_null",
            "comments_zero",
            "shares_null",
            "shares_zero",
            "synthetic",
            "uncertain",
        }
        for source_table in ("platform_snapshots", "reaction_snapshots"):
            if source_table not in {table.name for table in self.inventory.tables}:
                continue
            actual_summary = self.target.snapshot_summary(
                self.source_namespace_uuid, self.batch_id, source_table
            )
            expected_summary: dict[str, Any] = {}
            for key in actual_summary:
                if key in {"min_observed_at", "max_observed_at"}:
                    expected_summary[key] = totals.get(f"{source_table}.{key}")
                elif key == "shares" and source_table == "reaction_snapshots":
                    expected_summary[key] = None
                else:
                    value = totals.get(f"{source_table}.{key}")
                    expected_summary[key] = (
                        int(value or 0) if key in snapshot_count_keys or key == "rows" else value
                    )
            add_check(
                "snapshot_metrics",
                source_table,
                expected_summary,
                actual_summary,
                source_table=source_table,
                target_table="ingest.publication_metric_snapshot",
                details={"null_and_zero_are_compared_separately": True},
            )

        if "reaction_snapshots" in {table.name for table in self.inventory.tables}:
            actual_breakdown = self.target.reaction_breakdown_summary(
                self.source_namespace_uuid, self.batch_id
            )
            expected_breakdown = {
                key: int(totals.get(f"reaction_snapshots.{key}") or 0)
                for key in actual_breakdown
            }
            add_check(
                "reaction_breakdown",
                "reaction_snapshots",
                expected_breakdown,
                actual_breakdown,
                source_table="reaction_snapshots",
                target_table="ingest.reaction_breakdown",
            )
            add_check(
                "reaction_breakdown_parse",
                "reaction_snapshots",
                0,
                int(totals.get("reaction_snapshots.breakdown_invalid") or 0),
                source_table="reaction_snapshots",
                target_table="ingest.reaction_breakdown",
            )

        for source_table in ("posts", "platform_posts"):
            if source_table not in {table.name for table in self.inventory.tables}:
                continue
            actual_publications = self.target.publication_summary(
                self.source_namespace_uuid, self.batch_id, source_table
            )
            applicable = {
                "rows",
                "deleted",
                "incomplete",
                "forced_incomplete",
                "reposts",
            }
            if source_table == "posts":
                applicable.update({"album_posts", "albums", "ambiguous_albums"})
            expected_publications = {
                key: (
                    totals.get(f"{source_table}.{key}")
                    if key.startswith("min_") or key.startswith("max_")
                    else int(totals.get(f"{source_table}.{key}") or 0)
                )
                for key in actual_publications
                if key in applicable
            }
            comparable_actual = {
                key: actual_publications[key] for key in expected_publications
            }
            add_check(
                "publication_semantics",
                source_table,
                expected_publications,
                comparable_actual,
                source_table=source_table,
                target_table="ingest.publication",
            )

        expected_accounts = {
            key: (
                totals.get(f"account_metric_snapshot.{key}")
                if key == "subscribers"
                else int(totals.get(f"account_metric_snapshot.{key}") or 0)
            )
            for key in ("rows", "subscribers", "subscribers_null", "subscribers_zero")
        }
        actual_accounts_full = self.target.account_snapshot_summary(
            self.source_namespace_uuid, self.batch_id
        )
        actual_accounts = {
            key: actual_accounts_full[key] for key in expected_accounts
        }
        add_check(
            "account_snapshot_metrics",
            "accounts",
            expected_accounts,
            actual_accounts,
            source_table="platform_accounts+channels",
            target_table="ingest.account_metric_snapshot",
        )

        expected_rating_count = int(
            totals.get("official_rating_observation.rows") or 0
        )
        actual_rating_count = self.target.official_rating_count(
            self.source_namespace_uuid, self.batch_id
        )
        add_check(
            "official_rating_count",
            "all",
            expected_rating_count,
            actual_rating_count,
            source_table="institutions+channels",
            target_table="rating.official_rating_observation",
        )

        critical_mismatches = len(mismatches)
        return {
            "report_version": 1,
            "report_type": "post-import-reconciliation",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batch_id": str(self.batch_id),
            "source": self.inventory.as_dict(),
            "checks": checks,
            "mismatches": mismatches,
            "gate": {
                "status": "pass" if critical_mismatches == 0 else "fail",
                "critical_mismatches": critical_mismatches,
            },
        }

    def _dry_run_reconciliation(self) -> dict[str, Any]:
        return {
            "report_version": 1,
            "report_type": "dry-run",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batch_id": str(self.batch_id),
            "source": self.inventory.as_dict(),
            "checks": [
                {
                    "check": "source_integrity",
                    "status": "pass",
                    "quick_check": self.inventory.quick_check,
                    "foreign_key_violations": self.inventory.foreign_key_violations,
                },
                {
                    "check": "column_mapping",
                    "status": "pass",
                    "tables": len(self.inventory.tables),
                },
            ],
            "mismatches": [],
            "gate": {"status": "pass", "critical_mismatches": 0},
        }
