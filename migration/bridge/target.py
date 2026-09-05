from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from .model import BRIDGE_VERSION, SourceInventory


class PostgresTarget:
    """Small psycopg adapter whose operations mirror the Flyway-owned schema."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection: Any | None = None

    def __enter__(self) -> "PostgresTarget":
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised by integration setup
            raise RuntimeError(
                "psycopg is required for import; install migration/bridge/requirements.txt"
            ) from exc
        self.connection = psycopg.connect(self.dsn, autocommit=True)
        self.connection.execute("SET TIME ZONE 'UTC'")
        self.connection.execute("SET statement_timeout = '5min'")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.connection is None:
            raise RuntimeError("target is not connected")
        with self.connection.transaction():
            yield

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        if self.connection is None:
            raise RuntimeError("target is not connected")
        return self.connection.execute(sql, params)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        row = self.execute(sql, params).fetchone()
        return tuple(row) if row is not None else None

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in self.execute(sql, params).fetchall()]

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return value

    def _named_row(
        self,
        sql: str,
        names: tuple[str, ...],
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        row = self.fetchone(sql, params)
        if row is None:
            return {name: None for name in names}
        return {
            name: self._json_value(value)
            for name, value in zip(names, row, strict=True)
        }

    def prepare_batch(
        self,
        *,
        batch_id: UUID,
        inventory: SourceInventory,
        source_name: str,
        snapshot_kind: str,
        dry_run: bool,
        source_namespace: UUID,
        source_snapshot_at: datetime,
    ) -> str:
        row = self.fetchone(
            """INSERT INTO migration.import_batch(
                   id, source_name, source_file_name, source_size_bytes,
                   source_sha256, source_schema_version, snapshot_kind,
                   tool_version, status, dry_run, source_snapshot_at, metadata
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s::jsonb)
               ON CONFLICT (
                   source_name, source_sha256, snapshot_kind, tool_version, dry_run
               )
               DO UPDATE SET
                   status=CASE
                       WHEN migration.import_batch.status='succeeded'
                           THEN migration.import_batch.status
                       ELSE 'running'::migration.batch_status
                   END,
                   error_summary=NULL,
                   metadata=migration.import_batch.metadata || excluded.metadata
               RETURNING id, status::text""",
            (
                batch_id,
                source_name,
                Path(inventory.source_path).name,
                inventory.source_size_bytes,
                inventory.source_sha256,
                inventory.schema_version,
                snapshot_kind,
                BRIDGE_VERSION,
                dry_run,
                source_snapshot_at,
                json.dumps(
                    {
                        "source_namespace": str(source_namespace),
                        "quick_check": inventory.quick_check,
                        "foreign_key_violations": inventory.foreign_key_violations,
                    },
                    sort_keys=True,
                ),
            ),
        )
        if row is None:
            raise RuntimeError("failed to create migration batch")
        returned_id, status = row
        if UUID(str(returned_id)) != batch_id:
            raise RuntimeError(
                "same source hash is already bound to a different deterministic batch id"
            )
        return str(status)

    def finish_batch(
        self,
        batch_id: UUID,
        *,
        status: str,
        rows_read: int,
        rows_written: int,
        error_summary: str | None = None,
    ) -> None:
        self.execute(
            """UPDATE migration.import_batch
                  SET status=%s::migration.batch_status,
                      rows_read=%s,
                      rows_written=%s,
                      error_summary=%s,
                      finished_at=transaction_timestamp()
                WHERE id=%s""",
            (status, rows_read, rows_written, error_summary, batch_id),
        )

    def checkpoint(self, batch_id: UUID, stream_name: str) -> tuple[int, int, bool]:
        row = self.fetchone(
            """SELECT COALESCE((high_water_mark->>'rowid')::bigint,0),
                      rows_processed, completed
                 FROM migration.checkpoint
                WHERE batch_id=%s AND stream_name=%s""",
            (batch_id, stream_name),
        )
        return (int(row[0]), int(row[1]), bool(row[2])) if row else (0, 0, False)

    def save_checkpoint(
        self,
        batch_id: UUID,
        stream_name: str,
        source_table: str,
        rowid: int,
        rows_processed: int,
        *,
        completed: bool,
    ) -> None:
        self.execute(
            """INSERT INTO migration.checkpoint(
                   batch_id, stream_name, source_table, high_water_mark,
                   last_sequence, rows_processed, completed
               ) VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s)
               ON CONFLICT (batch_id, stream_name) DO UPDATE SET
                   high_water_mark=excluded.high_water_mark,
                   last_sequence=excluded.last_sequence,
                   rows_processed=excluded.rows_processed,
                   completed=excluded.completed,
                   updated_at=transaction_timestamp()""",
            (
                batch_id,
                stream_name,
                source_table,
                json.dumps({"rowid": rowid}),
                rowid,
                rows_processed,
                completed,
            ),
        )

    def record_mapping(
        self,
        *,
        source_namespace: UUID,
        source_table: str,
        source_pk: str,
        target_type: str,
        target_uuid: UUID | None,
        target_bigint: int | None,
        natural_key: Mapping[str, Any],
        source_row_hash: str,
        batch_id: UUID,
    ) -> None:
        cursor = self.execute(
            """INSERT INTO migration.legacy_identity_map(
                   source_namespace, source_table, source_pk, target_type,
                   target_uuid, target_bigint, natural_key, source_row_hash,
                   first_batch_id, last_seen_batch_id
               ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
               ON CONFLICT (source_namespace, source_table, source_pk, target_type)
               DO UPDATE SET
                   source_row_hash=excluded.source_row_hash,
                   natural_key=excluded.natural_key,
                   last_seen_batch_id=excluded.last_seen_batch_id
               WHERE migration.legacy_identity_map.target_uuid IS NOT DISTINCT FROM excluded.target_uuid
                 AND migration.legacy_identity_map.target_bigint IS NOT DISTINCT FROM excluded.target_bigint""",
            (
                source_namespace,
                source_table,
                source_pk,
                target_type,
                target_uuid,
                target_bigint,
                json.dumps(dict(natural_key), ensure_ascii=False, sort_keys=True),
                source_row_hash,
                batch_id,
                batch_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"identity remap rejected for {source_table}[{source_pk}] -> {target_type}"
            )

    def resolve_uuid(
        self,
        source_namespace: UUID,
        source_table: str,
        source_pk: str,
        target_type: str,
    ) -> UUID | None:
        row = self.fetchone(
            """SELECT target_uuid FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND source_table=%s
                  AND source_pk=%s AND target_type=%s""",
            (source_namespace, source_table, source_pk, target_type),
        )
        return UUID(str(row[0])) if row and row[0] is not None else None

    def resolve_bigint(
        self,
        source_namespace: UUID,
        source_table: str,
        source_pk: str,
        target_type: str,
    ) -> int | None:
        row = self.fetchone(
            """SELECT target_bigint FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND source_table=%s
                  AND source_pk=%s AND target_type=%s""",
            (source_namespace, source_table, source_pk, target_type),
        )
        return int(row[0]) if row and row[0] is not None else None

    def record_alias(
        self,
        entity_type: str,
        legacy_id: int,
        target_uuid: UUID,
        source_hash: str,
        legacy_route: str,
    ) -> None:
        cursor = self.execute(
            """INSERT INTO catalog.legacy_entity_alias(
                   entity_type, legacy_id, target_uuid, legacy_route, source_hash
               ) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (entity_type, legacy_id) DO UPDATE SET
                   legacy_route=excluded.legacy_route,
                   source_hash=excluded.source_hash
               WHERE catalog.legacy_entity_alias.target_uuid=excluded.target_uuid""",
            (entity_type, legacy_id, target_uuid, legacy_route, source_hash),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"legacy alias remap rejected: {entity_type}/{legacy_id}")

    def record_evidence(
        self,
        *,
        batch_id: UUID,
        source_table: str,
        source_pk: str,
        source_row_hash: str,
        evidence_kind: str,
        evidence: Mapping[str, Any],
    ) -> int:
        row = self.fetchone(
            """INSERT INTO migration.legacy_evidence(
                   batch_id, source_table, source_pk, source_row_hash,
                   evidence_kind, evidence, sanitized
               ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,true)
               ON CONFLICT (batch_id, source_table, source_pk, evidence_kind, source_row_hash)
               DO UPDATE SET evidence=excluded.evidence
               RETURNING id""",
            (
                batch_id,
                source_table,
                source_pk,
                source_row_hash,
                evidence_kind,
                json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True, default=str),
            ),
        )
        if row is None:
            raise RuntimeError("failed to persist migration evidence")
        return int(row[0])

    def ensure_partition(self, month: datetime) -> None:
        self.execute(
            "SELECT ops_and_admin.ensure_publication_metric_partition(%s::date)",
            (month.date().replace(day=1),),
        )

    def record_revision(
        self,
        batch_id: UUID,
        source_run_id: UUID | None,
        stream_name: str,
        affected_tags: list[str],
    ) -> int:
        row = self.fetchone(
            """INSERT INTO analytics.dataset_revision(
                   cause, correlation_id, source_run_id, metadata
               ) VALUES ('migration',%s,%s,%s::jsonb)
               RETURNING id""",
            (
                batch_id,
                source_run_id,
                json.dumps({"stream": stream_name}, sort_keys=True),
            ),
        )
        if row is None:
            raise RuntimeError("failed to record dataset revision")
        revision = int(row[0])
        self.execute(
            """INSERT INTO ops_and_admin.outbox_event(
                   dataset_revision_id, event_type, aggregate_type,
                   aggregate_id, affected_tags, payload
               ) VALUES (%s,'dataset.revision.changed','migration',%s,%s,%s::jsonb)
               ON CONFLICT DO NOTHING""",
            (
                revision,
                str(batch_id),
                affected_tags,
                json.dumps({"revision": revision, "stream": stream_name}, sort_keys=True),
            ),
        )
        # The projection revision is not advertised as ready until a rebuild completes.
        for projection in (
            "publication_latest",
            "publication_hourly",
            "institution_daily_metrics",
            "institution_monthly_metrics",
            "institution_period_metrics",
            "comparison",
        ):
            self.execute(
                """INSERT INTO analytics.projection_state(
                       projection_name, dataset_revision_id, status, refreshed_at, row_count
                   ) VALUES (%s,%s,'rebuilding',transaction_timestamp(),0)
                   ON CONFLICT (projection_name) DO UPDATE SET
                       dataset_revision_id=excluded.dataset_revision_id,
                       status='rebuilding', refreshed_at=excluded.refreshed_at,
                       row_count=0, error_code=NULL""",
                (projection, revision),
            )
        return revision

    def latest_batch_revision(self, batch_id: UUID) -> int | None:
        row = self.fetchone(
            """SELECT MAX(id) FROM analytics.dataset_revision
                WHERE cause='migration' AND correlation_id=%s""",
            (batch_id,),
        )
        return int(row[0]) if row and row[0] is not None else None

    def rebuild_core_projections(self, revision: int) -> Mapping[str, Any]:
        row = self.fetchone(
            "SELECT analytics.rebuild_core_projections(%s)",
            (revision,),
        )
        if row is None or not isinstance(row[0], Mapping):
            raise RuntimeError("projection rebuild returned no structured result")
        return dict(row[0])

    def record_reconciliation(
        self,
        *,
        batch_id: UUID,
        check_name: str,
        scope: str,
        source_table: str | None,
        target_table: str | None,
        status: str,
        critical: bool,
        expected: Any,
        actual: Any,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        difference: Any = None
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            difference = actual - expected
        self.execute(
            """INSERT INTO migration.reconciliation_result(
                   batch_id, check_name, scope, source_table, target_table,
                   status, critical, expected_value, actual_value, difference, details
               ) VALUES (%s,%s,%s,%s,%s,%s::migration.reconciliation_status,%s,
                         %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
               ON CONFLICT (batch_id, check_name, scope, source_table, target_table)
               DO UPDATE SET status=excluded.status, critical=excluded.critical,
                   expected_value=excluded.expected_value,
                   actual_value=excluded.actual_value,
                   difference=excluded.difference,
                   details=excluded.details,
                   checked_at=transaction_timestamp()""",
            (
                batch_id,
                check_name,
                scope,
                source_table,
                target_table,
                status,
                critical,
                json.dumps(expected, ensure_ascii=False, sort_keys=True),
                json.dumps(actual, ensure_ascii=False, sort_keys=True),
                json.dumps(difference, ensure_ascii=False, sort_keys=True),
                json.dumps(dict(details or {}), ensure_ascii=False, sort_keys=True),
            ),
        )

    def mapped_count(
        self,
        source_namespace: UUID,
        batch_id: UUID,
        source_table: str,
    ) -> int:
        row = self.fetchone(
            """SELECT COUNT(DISTINCT source_pk)
                 FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND source_table=%s
                  AND last_seen_batch_id=%s""",
            (source_namespace, source_table, batch_id),
        )
        return int(row[0]) if row else 0

    def namespace_is_current(self, source_namespace: UUID, batch_id: UUID) -> bool:
        row = self.fetchone(
            """SELECT NOT EXISTS (
                   SELECT 1 FROM migration.legacy_identity_map
                    WHERE source_namespace=%s AND last_seen_batch_id<>%s
               )""",
            (source_namespace, batch_id),
        )
        return bool(row[0]) if row else False

    def mapping_hashes(
        self,
        source_namespace: UUID,
        batch_id: UUID,
        source_table: str,
    ) -> dict[str, str]:
        rows = self.fetchall(
            """SELECT source_pk, MIN(source_row_hash), COUNT(DISTINCT source_row_hash)
                 FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND source_table=%s
                  AND last_seen_batch_id=%s
                GROUP BY source_pk ORDER BY source_pk""",
            (source_namespace, source_table, batch_id),
        )
        inconsistent = [str(row[0]) for row in rows if int(row[2]) != 1]
        if inconsistent:
            raise RuntimeError(
                f"inconsistent source hashes in identity map for {source_table}: "
                f"{inconsistent[:5]}"
            )
        return {str(row[0]): str(row[1]) for row in rows}

    def snapshot_summary(
        self,
        source_namespace: UUID,
        batch_id: UUID,
        source_table: str,
    ) -> dict[str, Any]:
        return self._named_row(
            """SELECT COUNT(s.id),
                      SUM(s.reactions_count), SUM(s.views_count),
                      SUM(s.comments_count), SUM(s.shares_count),
                      COUNT(*) FILTER (WHERE s.reactions_count IS NULL),
                      COUNT(*) FILTER (WHERE s.reactions_count=0),
                      COUNT(*) FILTER (WHERE s.views_count IS NULL),
                      COUNT(*) FILTER (WHERE s.views_count=0),
                      COUNT(*) FILTER (WHERE s.comments_count IS NULL),
                      COUNT(*) FILTER (WHERE s.comments_count=0),
                      COUNT(*) FILTER (WHERE s.shares_count IS NULL),
                      COUNT(*) FILTER (WHERE s.shares_count=0),
                      COUNT(*) FILTER (WHERE s.synthetic),
                      COUNT(*) FILTER (WHERE s.interval_uncertain),
                      MIN(s.observed_at), MAX(s.observed_at)
                 FROM migration.legacy_identity_map m
                 LEFT JOIN ingest.publication_metric_snapshot s
                   ON s.id=m.target_bigint
                WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                  AND m.source_table=%s
                  AND m.target_type='publication_metric_snapshot'""",
            (
                "rows",
                "reactions",
                "views",
                "comments",
                "shares",
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
                "min_observed_at",
                "max_observed_at",
            ),
            (source_namespace, batch_id, source_table),
        )

    def reaction_breakdown_summary(
        self,
        source_namespace: UUID,
        batch_id: UUID,
    ) -> dict[str, Any]:
        return self._named_row(
            """WITH imported AS (
                   SELECT s.published_month, s.id, s.reactions_count
                     FROM migration.legacy_identity_map m
                     JOIN ingest.publication_metric_snapshot s ON s.id=m.target_bigint
                    WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                      AND m.source_table='reaction_snapshots'
                      AND m.target_type='publication_metric_snapshot'
               ), totals AS (
                   SELECT i.id, i.reactions_count,
                          COUNT(rb.reaction_key) AS item_count,
                          COALESCE(SUM(rb.reaction_count),0) AS item_sum
                     FROM imported i
                     LEFT JOIN ingest.reaction_breakdown rb
                       ON rb.snapshot_published_month=i.published_month
                      AND rb.snapshot_id=i.id
                    GROUP BY i.id, i.reactions_count
               )
               SELECT COALESCE(SUM(item_count),0), COALESCE(SUM(item_sum),0),
                      COUNT(*) FILTER (WHERE item_sum<>reactions_count)
                 FROM totals""",
            ("breakdown_rows", "breakdown_sum", "breakdown_total_mismatch"),
            (source_namespace, batch_id),
        )

    def publication_summary(
        self,
        source_namespace: UUID,
        batch_id: UUID,
        source_table: str,
    ) -> dict[str, Any]:
        return self._named_row(
            """SELECT COUNT(p.id),
                      COUNT(*) FILTER (WHERE p.deleted_at IS NOT NULL),
                      COUNT(*) FILTER (WHERE p.history_completeness<>'complete'),
                      COUNT(*) FILTER (WHERE p.history_completeness='forced_incomplete'),
                      COUNT(*) FILTER (WHERE p.is_repost),
                      COUNT(*) FILTER (WHERE p.content_group_id IS NOT NULL),
                      COUNT(DISTINCT p.content_group_id) FILTER (
                          WHERE p.content_group_id IS NOT NULL
                      ),
                      COUNT(*) FILTER (
                          WHERE COALESCE(
                              CASE WHEN jsonb_typeof(
                                            p.quality_flags->'ambiguous_album_reactions'
                                        )='boolean'
                                   THEN (p.quality_flags
                                             ->>'ambiguous_album_reactions')::boolean
                              END,
                              CASE WHEN jsonb_typeof(
                                            p.quality_flags->'ambiguous_reactions'
                                        )='boolean'
                                   THEN (p.quality_flags
                                             ->>'ambiguous_reactions')::boolean
                              END,
                              false
                          )
                      ),
                      MIN(p.published_at), MAX(p.published_at)
                 FROM migration.legacy_identity_map m
                 LEFT JOIN ingest.publication p ON p.id=m.target_uuid
                WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                  AND m.source_table=%s AND m.target_type='publication'""",
            (
                "rows",
                "deleted",
                "incomplete",
                "forced_incomplete",
                "reposts",
                "album_posts",
                "albums",
                "ambiguous_albums",
                "min_published_at",
                "max_published_at",
            ),
            (source_namespace, batch_id, source_table),
        )

    def account_snapshot_summary(
        self,
        source_namespace: UUID,
        batch_id: UUID,
    ) -> dict[str, Any]:
        return self._named_row(
            """WITH imported_snapshots AS (
                   SELECT DISTINCT target_bigint
                     FROM migration.legacy_identity_map
                    WHERE source_namespace=%s AND last_seen_batch_id=%s
                      AND source_table IN ('channels','platform_accounts')
                      AND target_type='account_metric_snapshot'
               )
               SELECT COUNT(s.id), SUM(s.subscriber_count),
                      COUNT(*) FILTER (WHERE s.subscriber_count IS NULL),
                      COUNT(*) FILTER (WHERE s.subscriber_count=0),
                      MIN(s.observed_at), MAX(s.observed_at)
                 FROM ingest.account_metric_snapshot s
                 JOIN imported_snapshots imported ON imported.target_bigint=s.id""",
            (
                "rows",
                "subscribers",
                "subscribers_null",
                "subscribers_zero",
                "min_observed_at",
                "max_observed_at",
            ),
            (source_namespace, batch_id),
        )

    def integrity_summary(
        self,
        source_namespace: UUID,
        batch_id: UUID,
    ) -> dict[str, Any]:
        return self._named_row(
            """SELECT
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='institution'
                     AND NOT EXISTS (SELECT 1 FROM catalog.institution t WHERE t.id=m.target_uuid)),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='platform_account'
                     AND NOT EXISTS (SELECT 1 FROM catalog.platform_account t WHERE t.id=m.target_uuid)),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='account_metric_snapshot'
                     AND NOT EXISTS (SELECT 1 FROM ingest.account_metric_snapshot t WHERE t.id=m.target_bigint)),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='publication'
                     AND NOT EXISTS (SELECT 1 FROM ingest.publication t WHERE t.id=m.target_uuid)),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='publication_identity'
                     AND NOT EXISTS (SELECT 1 FROM ingest.publication_identity t WHERE t.id=m.target_bigint)),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type='publication_metric_snapshot'
                     AND NOT EXISTS (
                         SELECT 1 FROM ingest.publication_metric_snapshot t WHERE t.id=m.target_bigint
                     )),
                 (SELECT COUNT(*) FROM migration.legacy_identity_map m
                   WHERE m.source_namespace=%s AND m.last_seen_batch_id=%s
                     AND m.target_type LIKE 'official_rating_observation:%%'
                     AND NOT EXISTS (
                         SELECT 1 FROM rating.official_rating_observation t WHERE t.id=m.target_uuid
                     )),
                 (SELECT COUNT(*) FROM ingest.publication_metric_snapshot_default),
                 (SELECT COUNT(*) FROM ingest.reaction_breakdown_default),
                 (SELECT COUNT(*) FROM pg_constraint c
                    JOIN pg_namespace n ON n.oid=c.connamespace
                   WHERE n.nspname IN (
                       'catalog','ingest','analytics','rating','ops_and_admin','migration'
                   ) AND NOT c.convalidated)""",
            (
                "missing_institutions",
                "missing_accounts",
                "missing_account_snapshots",
                "missing_publications",
                "missing_publication_identities",
                "missing_snapshots",
                "missing_official_ratings",
                "default_snapshot_partition_rows",
                "default_reaction_partition_rows",
                "unvalidated_constraints",
            ),
            (
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
                source_namespace,
                batch_id,
            ),
        )

    def official_rating_count(
        self,
        source_namespace: UUID,
        batch_id: UUID,
    ) -> int:
        row = self.fetchone(
            """SELECT COUNT(*) FROM migration.legacy_identity_map
                WHERE source_namespace=%s AND last_seen_batch_id=%s
                  AND target_type LIKE 'official_rating_observation:%%'""",
            (source_namespace, batch_id),
        )
        return int(row[0]) if row else 0

    def publication_contexts(
        self, publication_ids: list[UUID]
    ) -> dict[UUID, tuple[datetime, str]]:
        if not publication_ids:
            return {}
        rows = self.execute(
            """SELECT p.id, p.published_at, pa.platform::text
                 FROM ingest.publication p
                 JOIN catalog.platform_account pa ON pa.id=p.primary_account_id
                WHERE p.id=ANY(%s)""",
            (publication_ids,),
        ).fetchall()
        return {
            UUID(str(row[0])): (row[1], str(row[2]))
            for row in rows
        }
