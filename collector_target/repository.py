from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import re
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import UUID

from .model import (
    AccountRef,
    CanonicalAccountBatch,
    CanonicalAccountObservation,
    CanonicalDeletionProbe,
    CanonicalPublication,
    CollectionContext,
    DeletionProbeOutcome,
    IngestionResult,
    Platform,
    RunStatus,
    RunSummary,
    TrackedPublication,
    checkpoint_uuid,
    raw_payload_uuid,
    utc,
)
from .normalize import canonical_json, sanitize_evidence


_SHARD = re.compile(r"^(\d+)/(\d+)$")
_SAFE_ERROR_CODE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]{0,79}(?::[A-Za-z0-9_.-]{1,80})?$"
)


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[index]


def _json(value: Any) -> str:
    return canonical_json(value)


def _error_code(value: str) -> str:
    value = value.strip()
    return value if _SAFE_ERROR_CODE.fullmatch(value) else "CollectorError"


class PostgresCollectorRepository:
    """Collector-facing PostgreSQL repository.

    Every account batch is one database transaction: normalized observations,
    sanitized lineage, checkpoint, dataset revision, and outbox event either all
    commit or all roll back. A connection is never shared across account tasks.
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
        raw_retention_days: int = 7,
        statement_timeout_seconds: int = 60,
    ) -> None:
        if connection_factory is None and not dsn:
            raise ValueError("dsn or connection_factory is required")
        if raw_retention_days < 1:
            raise ValueError("raw_retention_days must be positive")
        if statement_timeout_seconds < 1:
            raise ValueError("statement_timeout_seconds must be positive")
        self._factory = connection_factory or self._psycopg_factory(str(dsn))
        self.raw_retention = timedelta(days=raw_retention_days)
        self.statement_timeout_seconds = statement_timeout_seconds

    @staticmethod
    def _psycopg_factory(dsn: str) -> Callable[[], Any]:
        def connect() -> Any:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - packaging guard
                raise RuntimeError("psycopg is required for target collection") from exc
            return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

        return connect

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._factory()
        try:
            connection.execute("SET TIME ZONE 'UTC'")
            connection.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (f"{self.statement_timeout_seconds}s",),
            )
            yield connection
        finally:
            connection.close()

    def start_run(self, context: CollectionContext) -> None:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO ingest.collection_run(
                   id, platform, partition_key, collector_version, started_at,
                       scheduled_at, status, correlation_id
                   ) VALUES (%s,%s,%s,%s,%s,%s,'running',%s)
                   ON CONFLICT (id) DO UPDATE SET
                       collector_version=excluded.collector_version,
                       started_at=LEAST(ingest.collection_run.started_at, excluded.started_at),
                       completed_at=NULL,
                       status='running',
                       correlation_id=excluded.correlation_id
                   WHERE ingest.collection_run.status <> 'succeeded'""",
                (
                    context.run_id,
                    context.platform.value,
                    context.partition_key,
                    context.collector_version,
                    context.started_at,
                    context.scheduled_at,
                    context.correlation_id,
                ),
            )
            schedule_value = {
                "scheduled_at": context.scheduled_at,
                "run_id": context.run_id,
                "collector_version": context.collector_version,
                "partition_key": context.partition_key,
            }
            key = "collector.schedule"
            checkpoint_id = checkpoint_uuid(
                key, "platform", context.partition_scope_id,
            )
            connection.execute(
                """INSERT INTO ops_and_admin.operational_checkpoint(
                       id, checkpoint_key, scope_type, scope_id, platform, value,
                       source_observed_at, correlation_id
                   ) VALUES (%s,%s,'platform',%s,%s,%s::jsonb,%s,%s)
                   ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
                   DO UPDATE SET
                       value=excluded.value,
                       source_observed_at=excluded.source_observed_at,
                       updated_at=transaction_timestamp(),
                       correlation_id=excluded.correlation_id""",
                (
                    checkpoint_id,
                    key,
                    context.partition_scope_id,
                    context.platform.value,
                    _json(schedule_value),
                    context.scheduled_at,
                    context.correlation_id,
                ),
            )

    def record_skipped_run(self, context: CollectionContext) -> RunSummary:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO ingest.collection_run(
                       id, platform, partition_key, collector_version, started_at,
                       scheduled_at, completed_at, status, correlation_id
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,'skipped',%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    context.run_id,
                    context.platform.value,
                    context.partition_key,
                    context.collector_version,
                    context.started_at,
                    context.scheduled_at,
                    context.started_at,
                    context.correlation_id,
                ),
            )
        return RunSummary(
            context.run_id,
            context.platform,
            RunStatus.SKIPPED,
            0,
            0,
            context.started_at,
            context.started_at,
        )

    def resumable_scheduled_at(
        self,
        platform: Platform,
        partition_key: str,
        collector_version: str,
    ) -> datetime | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT scheduled_at
                     FROM ingest.collection_run
                    WHERE platform=%s
                      AND partition_key=%s
                      AND collector_version=%s
                      AND status IN ('running','partial','failed')
                    ORDER BY scheduled_at, started_at
                    LIMIT 1""",
                (platform.value, partition_key, collector_version),
            ).fetchone()
        return (
            utc(_row_value(row, "scheduled_at", 0), "run.scheduled_at")
            if row is not None else None
        )

    def enabled_accounts(
        self, platform: Platform, partition_key: str,
    ) -> Sequence[AccountRef]:
        params: list[Any] = [platform.value]
        shard_filter = ""
        if partition_key not in {"default", "all"}:
            match = _SHARD.fullmatch(partition_key)
            if match is None:
                raise ValueError("partition_key must be default, all, or INDEX/COUNT")
            index, count = (int(match.group(1)), int(match.group(2)))
            if count < 1 or index < 0 or index >= count:
                raise ValueError("partition shard must satisfy 0 <= INDEX < COUNT")
            shard_filter = (
                " AND mod(abs(hashtextextended(account.id::text, 0)::numeric), %s) = %s"
            )
            params.extend((count, index))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT account.id, account.institution_id,
                          account.platform::text AS platform,
                          account.canonical_external_id,
                          account.access_mode::text AS access_mode,
                          account.current_username, account.current_title,
                          account.current_url, native.external_id AS native_external_id
                     FROM catalog.platform_account AS account
                     LEFT JOIN LATERAL (
                         SELECT identity.external_id
                           FROM catalog.account_external_identity AS identity
                          WHERE identity.platform_account_id=account.id
                            AND identity.valid_to IS NULL
                          ORDER BY (
                              identity.identity_namespace = concat(
                                  account.platform::text, ':native_id'
                              )
                          ) DESC,
                          identity.verified_at DESC NULLS LAST,
                          identity.id DESC
                          LIMIT 1
                     ) AS native ON true
                    WHERE account.enabled AND account.platform=%s"""
                + shard_filter
                + " ORDER BY id",
                tuple(params),
            ).fetchall()
        return tuple(
            AccountRef(
                id=_row_value(row, "id", 0),
                institution_id=_row_value(row, "institution_id", 1),
                platform=Platform(_row_value(row, "platform", 2)),
                canonical_external_id=_row_value(row, "canonical_external_id", 3),
                access_mode=_row_value(row, "access_mode", 4),
                current_username=_row_value(row, "current_username", 5),
                current_title=_row_value(row, "current_title", 6),
                current_url=_row_value(row, "current_url", 7),
                native_external_id=_row_value(row, "native_external_id", 8),
            )
            for row in rows
        )

    def begin_account(
        self,
        context: CollectionContext,
        account: AccountRef,
        started_at: datetime,
    ) -> bool:
        started = utc(started_at, "account.started_at")
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """INSERT INTO ingest.collection_account_result(
                       collection_run_id, platform_account_id, started_at, status
                   ) VALUES (%s,%s,%s,'running')
                   ON CONFLICT (collection_run_id, platform_account_id)
                   DO UPDATE SET
                       started_at=LEAST(
                           ingest.collection_account_result.started_at,
                           excluded.started_at
                       ),
                       completed_at=NULL,
                       status='running',
                       discovered_count=0,
                       snapshot_count=0,
                       sanitized_error_code=NULL
                   WHERE ingest.collection_account_result.status <> 'succeeded'
                   RETURNING status::text AS status""",
                (context.run_id, account.id, started),
            ).fetchone()
        return row is not None

    def metric_high_watermarks(
        self,
        account: AccountRef,
        external_ids: Sequence[str],
    ) -> Mapping[str, Mapping[str, int | None]]:
        requested = tuple(dict.fromkeys(str(value) for value in external_ids if value))
        if not requested:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT identity.external_id,
                          max(snapshot.views_count) AS views,
                          max(snapshot.reactions_count) AS reactions,
                          max(snapshot.comments_count) AS comments,
                          max(snapshot.shares_count) AS shares
                     FROM ingest.publication_identity AS identity
                     JOIN ingest.publication_metric_snapshot AS snapshot
                       ON snapshot.publication_id=identity.publication_id
                    WHERE identity.platform_account_id=%s
                      AND identity.external_id=ANY(%s)
                    GROUP BY identity.external_id""",
                (account.id, list(requested)),
            ).fetchall()
        return {
            str(_row_value(row, "external_id", 0)): {
                "views": _row_value(row, "views", 1),
                "reactions": _row_value(row, "reactions", 2),
                "comments": _row_value(row, "comments", 3),
                "shares": _row_value(row, "shares", 4),
            }
            for row in rows
        }

    def tracked_publications(
        self,
        account: AccountRef,
        *,
        published_after: datetime,
        limit: int,
    ) -> Sequence[TrackedPublication]:
        """Read a bounded circular page without advancing its durable cursor.

        The cursor is advanced only when the owning account batch commits, so a
        failed/resumed deterministic run selects the same page. UUID ordering is
        stable and intentionally independent of discovery-page ordering.
        """

        cutoff = utc(published_after, "published_after")
        bounded_limit = int(limit)
        if bounded_limit < 1 or bounded_limit > 10_000:
            raise ValueError("tracked publication limit must be between 1 and 10000")
        with self._connection() as connection:
            checkpoint = connection.execute(
                """SELECT value->>'cursor' AS cursor
                     FROM ops_and_admin.operational_checkpoint
                    WHERE checkpoint_key='collector.refresh_cursor.v1'
                      AND scope_type='account' AND scope_id=%s
                      AND platform IS NULL""",
                (account.id,),
            ).fetchone()
            cursor: UUID | None = None
            if checkpoint is not None:
                raw_cursor = _row_value(checkpoint, "cursor", 0)
                if raw_cursor:
                    try:
                        cursor = UUID(str(raw_cursor))
                    except ValueError:
                        cursor = None
            rows = connection.execute(
                """SELECT publication.id,
                          primary_identity.external_id,
                          primary_identity.source_external_id,
                          primary_identity.public_url,
                          publication.published_at,
                          ARRAY(
                              SELECT identity.external_id
                                FROM ingest.publication_identity AS identity
                               WHERE identity.publication_id=publication.id
                                 AND identity.platform_account_id=%s
                               ORDER BY
                                   (identity.role='primary') DESC,
                                   identity.id
                          ) AS identity_external_ids,
                          latest.observed_at AS latest_observed_at,
                          latest.sampling_bucket AS latest_sampling_bucket
                     FROM ingest.publication AS publication
                     JOIN LATERAL (
                         SELECT identity.external_id,
                                identity.source_external_id,
                                identity.public_url
                           FROM ingest.publication_identity AS identity
                          WHERE identity.publication_id=publication.id
                            AND identity.platform_account_id=%s
                            AND identity.role='primary'
                          ORDER BY identity.id
                          LIMIT 1
                     ) AS primary_identity ON true
                     LEFT JOIN LATERAL (
                         SELECT snapshot.observed_at, snapshot.sampling_bucket
                           FROM ingest.publication_metric_snapshot AS snapshot
                          WHERE snapshot.publication_id=publication.id
                          ORDER BY snapshot.observed_at DESC, snapshot.id DESC
                          LIMIT 1
                     ) AS latest ON true
                    WHERE publication.primary_account_id=%s
                      AND publication.deleted_at IS NULL
                      AND publication.published_at >= %s
                    ORDER BY CASE
                        WHEN %s::uuid IS NULL OR publication.id > %s::uuid THEN 0
                        ELSE 1
                    END,
                    publication.id
                    LIMIT %s""",
                (
                    account.id,
                    account.id,
                    account.id,
                    cutoff,
                    cursor,
                    cursor,
                    bounded_limit,
                ),
            ).fetchall()
        return tuple(
            TrackedPublication(
                id=_row_value(row, "id", 0),
                external_id=str(_row_value(row, "external_id", 1)),
                source_external_id=_row_value(row, "source_external_id", 2),
                public_url=_row_value(row, "public_url", 3),
                published_at=utc(
                    _row_value(row, "published_at", 4),
                    "publication.published_at",
                ),
                identity_external_ids=tuple(
                    str(value)
                    for value in (_row_value(row, "identity_external_ids", 5) or ())
                ),
                latest_observed_at=(
                    utc(
                        _row_value(row, "latest_observed_at", 6),
                        "snapshot.observed_at",
                    )
                    if _row_value(row, "latest_observed_at", 6) is not None
                    else None
                ),
                latest_sampling_bucket=(
                    int(_row_value(row, "latest_sampling_bucket", 7))
                    if _row_value(row, "latest_sampling_bucket", 7) is not None
                    else None
                ),
            )
            for row in rows
        )

    def persist_account_batch(self, batch: CanonicalAccountBatch) -> IngestionResult:
        if batch.account.platform != batch.context.platform:
            raise ValueError("account platform does not match collection context")
        discovered_count = 0
        snapshot_count = 0
        deletion_probe_count = 0
        changed = False
        with self._connection() as connection, connection.transaction():
            for published_month in sorted({
                publication.snapshot.published_month
                for publication in batch.publications
            }):
                connection.execute(
                    "SELECT ops_and_admin.ensure_publication_metric_partition(%s::date)",
                    (published_month,),
                )
            if batch.account_observation is not None:
                identity_changed = self._persist_account_identity(
                    connection, batch, batch.account_observation,
                )
                account_changed = self._persist_account_observation(
                    connection, batch, batch.account_observation,
                )
                changed = changed or identity_changed or account_changed

            for publication in batch.publications:
                discovered, snapshot, publication_changed = self._persist_publication(
                    connection, batch, publication,
                )
                discovered_count += int(discovered)
                snapshot_count += int(snapshot)
                changed = changed or publication_changed

            explicit_probe_ids = {
                probe.publication_id for probe in batch.deletion_probes
            }
            presence_probes = tuple(
                CanonicalDeletionProbe(
                    publication.id,
                    publication.snapshot.observed_at,
                    DeletionProbeOutcome.PRESENT,
                    f"{batch.context.platform.value}_publication_observed",
                    2,
                )
                for publication in batch.publications
                if (
                    publication.id not in explicit_probe_ids
                    and not publication.snapshot.synthetic
                )
            )
            for probe in (*presence_probes, *batch.deletion_probes):
                probe_changed = self._persist_deletion_probe(
                    connection, batch, probe,
                )
                deletion_probe_count += int(probe_changed)
                changed = changed or probe_changed

            if batch.cursor is not None:
                self._persist_cursor(connection, batch)
            if batch.refresh_cursor is not None:
                self._persist_refresh_cursor(connection, batch)

            completed_at = self._batch_completed_at(batch)
            result = connection.execute(
                """UPDATE ingest.collection_account_result
                      SET completed_at=%s,
                          status='succeeded',
                          discovered_count=GREATEST(discovered_count, %s),
                          snapshot_count=GREATEST(snapshot_count, %s),
                          sanitized_error_code=NULL
                    WHERE collection_run_id=%s AND platform_account_id=%s
                    RETURNING id""",
                (
                    completed_at,
                    discovered_count,
                    snapshot_count,
                    batch.context.run_id,
                    batch.account.id,
                ),
            ).fetchone()
            if result is None:
                raise RuntimeError("collection account result was not started")

            revision_id = (
                self._record_revision(
                    connection,
                    batch,
                    discovered_count,
                    snapshot_count,
                    deletion_probe_count,
                    completed_at,
                )
                if changed else None
            )
        return IngestionResult(
            batch.context.run_id,
            batch.account.id,
            discovered_count,
            snapshot_count,
            revision_id,
        )

    def _persist_account_observation(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        observation: CanonicalAccountObservation,
    ) -> bool:
        row = connection.execute(
            """INSERT INTO ingest.account_metric_snapshot(
                   platform_account_id, collection_run_id, observed_at,
                   collected_at, subscriber_count, subscriber_display, quality,
                   source_fingerprint
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (platform_account_id, observed_at, source_fingerprint)
               DO NOTHING
               RETURNING id""",
            (
                batch.account.id,
                batch.context.run_id,
                observation.observed_at,
                observation.collected_at,
                observation.subscriber_count,
                observation.subscriber_display,
                observation.quality.value,
                observation.source_fingerprint,
            ),
        ).fetchone()
        if row is None:
            return False
        self._persist_lineage(
            connection,
            batch.context.run_id,
            "account",
            batch.account.id,
            observation.collected_at,
            observation.source_fingerprint,
        )
        return True

    def _persist_account_identity(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        observation: CanonicalAccountObservation,
    ) -> bool:
        """Version presentation/native identity without catalog admin privileges."""
        account = batch.account
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"account-identity:{account.id}",),
        )
        changed = False
        presentation_seen = any(
            value is not None
            for value in (observation.username, observation.title, observation.url)
        )
        if presentation_seen:
            current = connection.execute(
                """SELECT id, username, title, url, valid_from
                     FROM catalog.account_identity_history
                    WHERE platform_account_id=%s AND valid_to IS NULL
                    FOR UPDATE""",
                (account.id,),
            ).fetchone()
            username = observation.username or account.current_username
            title = observation.title or account.current_title
            url = observation.url or account.current_url
            differs = current is None or (
                _row_value(current, "username", 1),
                _row_value(current, "title", 2),
                _row_value(current, "url", 3),
            ) != (username, title, url)
            if differs:
                if current is not None:
                    valid_from = utc(
                        _row_value(current, "valid_from", 4),
                        "identity.valid_from",
                    )
                    if observation.observed_at <= valid_from:
                        raise RuntimeError("account identity observation time collision")
                    connection.execute(
                        """UPDATE catalog.account_identity_history
                              SET valid_to=%s
                            WHERE id=%s AND valid_to IS NULL""",
                        (observation.observed_at, _row_value(current, "id", 0)),
                    )
                connection.execute(
                    """INSERT INTO catalog.account_identity_history(
                           platform_account_id, username, title, url, valid_from,
                           source_run_id
                       ) VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        account.id,
                        username,
                        title,
                        url,
                        observation.observed_at,
                        batch.context.run_id,
                    ),
                )
                changed = True
            current_row_changed = connection.execute(
                """UPDATE catalog.platform_account
                      SET current_username=%s,
                          current_title=%s,
                          current_url=%s,
                          updated_at=GREATEST(updated_at, %s),
                          row_version=row_version + 1
                    WHERE id=%s
                      AND ROW(current_username, current_title, current_url)
                          IS DISTINCT FROM ROW(%s,%s,%s)
                    RETURNING id""",
                (
                    username,
                    title,
                    url,
                    observation.observed_at,
                    account.id,
                    username,
                    title,
                    url,
                ),
            ).fetchone()
            changed = changed or current_row_changed is not None

        if observation.native_external_id is not None:
            # Keep the namespace emitted by the deterministic SQLite bridge so
            # target collection versions that same identity instead of creating
            # a second parallel "current" native identifier.
            namespace = f"{account.platform.value}:native_id"
            current_native = connection.execute(
                """SELECT id, external_id, valid_from
                     FROM catalog.account_external_identity
                    WHERE platform_account_id=%s
                      AND identity_namespace=%s
                      AND valid_to IS NULL
                    FOR UPDATE""",
                (account.id, namespace),
            ).fetchone()
            if (
                current_native is None
                or str(_row_value(current_native, "external_id", 1))
                    != observation.native_external_id
            ):
                if current_native is not None:
                    valid_from = utc(
                        _row_value(current_native, "valid_from", 2),
                        "external_identity.valid_from",
                    )
                    if observation.observed_at <= valid_from:
                        raise RuntimeError("account native identity time collision")
                    connection.execute(
                        """UPDATE catalog.account_external_identity
                              SET valid_to=%s
                            WHERE id=%s AND valid_to IS NULL""",
                        (
                            observation.observed_at,
                            _row_value(current_native, "id", 0),
                        ),
                    )
                connection.execute(
                    """INSERT INTO catalog.account_external_identity(
                           platform_account_id, identity_namespace, external_id,
                           valid_from, verified_at, source_run_id
                       ) VALUES (%s,%s,%s,%s,%s,%s)""",
                    (
                        account.id,
                        namespace,
                        observation.native_external_id,
                        observation.observed_at,
                        observation.observed_at,
                        batch.context.run_id,
                    ),
                )
                changed = True
        return changed

    def _persist_publication(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        publication: CanonicalPublication,
    ) -> tuple[bool, bool, bool]:
        if publication.account_id != batch.account.id:
            raise ValueError("publication account does not match batch account")
        lock_name = f"publication:{batch.account.id}:{publication.external_id}"
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_name,),
        )
        identity_row = connection.execute(
            """SELECT publication_id
                 FROM ingest.publication_identity
                WHERE platform_account_id=%s AND external_id=%s""",
            (batch.account.id, publication.external_id),
        ).fetchone()
        known = identity_row is not None
        publication_id = (
            _row_value(identity_row, "publication_id", 0)
            if identity_row is not None else publication.id
        )

        if publication.content_group_id is not None:
            connection.execute(
                """INSERT INTO ingest.content_group(id, group_type)
                   VALUES (%s,%s) ON CONFLICT (id) DO NOTHING""",
                (
                    publication.content_group_id,
                    f"{batch.context.platform.value}_logical_group",
                ),
            )

        first_age = max(
            0,
            int((publication.discovered_at - publication.published_at).total_seconds()),
        )
        changed_row = connection.execute(
            """INSERT INTO ingest.publication AS current(
                   id, primary_account_id, content_group_id, published_at,
                   discovered_at, first_observation_age_seconds, publication_type,
                   is_repost, history_completeness, synthetic_baseline_allowed,
                   quality_flags
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
               ON CONFLICT (id) DO UPDATE SET
                   content_group_id=COALESCE(excluded.content_group_id, current.content_group_id),
                   published_at=excluded.published_at,
                   discovered_at=LEAST(current.discovered_at, excluded.discovered_at),
                   first_observation_age_seconds=LEAST(
                       current.first_observation_age_seconds,
                       excluded.first_observation_age_seconds
                   ),
                   publication_type=excluded.publication_type,
                   is_repost=current.is_repost OR excluded.is_repost,
                   history_completeness=CASE
                       WHEN current.history_completeness='forced_incomplete'
                         OR excluded.history_completeness='forced_incomplete'
                           THEN 'forced_incomplete'::ingest.history_completeness
                       WHEN current.history_completeness='complete'
                         OR excluded.history_completeness='complete'
                           THEN 'complete'::ingest.history_completeness
                       ELSE 'incomplete'::ingest.history_completeness
                   END,
                   synthetic_baseline_allowed=CASE
                       WHEN current.history_completeness='forced_incomplete'
                         OR excluded.history_completeness='forced_incomplete'
                           THEN false
                       ELSE current.synthetic_baseline_allowed
                           OR excluded.synthetic_baseline_allowed
                   END,
                   quality_flags=current.quality_flags || excluded.quality_flags,
                   deleted_at=NULL
               WHERE ROW(
                       current.content_group_id,
                       current.published_at,
                       current.discovered_at,
                       current.first_observation_age_seconds,
                       current.publication_type,
                       current.is_repost,
                       current.history_completeness,
                       current.synthetic_baseline_allowed,
                       current.quality_flags,
                       current.deleted_at
                   ) IS DISTINCT FROM ROW(
                       COALESCE(excluded.content_group_id, current.content_group_id),
                       excluded.published_at,
                       LEAST(current.discovered_at, excluded.discovered_at),
                       LEAST(
                           current.first_observation_age_seconds,
                           excluded.first_observation_age_seconds
                       ),
                       excluded.publication_type,
                       current.is_repost OR excluded.is_repost,
                       CASE
                           WHEN current.history_completeness='forced_incomplete'
                             OR excluded.history_completeness='forced_incomplete'
                               THEN 'forced_incomplete'::ingest.history_completeness
                           WHEN current.history_completeness='complete'
                             OR excluded.history_completeness='complete'
                               THEN 'complete'::ingest.history_completeness
                           ELSE 'incomplete'::ingest.history_completeness
                       END,
                       CASE
                           WHEN current.history_completeness='forced_incomplete'
                             OR excluded.history_completeness='forced_incomplete'
                               THEN false
                           ELSE current.synthetic_baseline_allowed
                               OR excluded.synthetic_baseline_allowed
                       END,
                       current.quality_flags || excluded.quality_flags,
                       NULL::timestamptz
                   )
               RETURNING id""",
            (
                publication_id,
                batch.account.id,
                publication.content_group_id,
                publication.published_at,
                publication.discovered_at,
                first_age,
                publication.publication_type,
                publication.is_repost,
                publication.history_completeness.value,
                publication.synthetic_baseline_allowed,
                _json(publication.quality_flags),
            ),
        ).fetchone()
        publication_changed = changed_row is not None

        identity_changed = False
        for identity in publication.identities:
            identity_result = connection.execute(
                """INSERT INTO ingest.publication_identity(
                       publication_id, platform_account_id, external_id,
                       source_external_id, role, public_url
                   ) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (platform_account_id, external_id) DO UPDATE SET
                       source_external_id=COALESCE(
                           excluded.source_external_id,
                           ingest.publication_identity.source_external_id
                       ),
                       role=excluded.role,
                       public_url=COALESCE(
                           excluded.public_url,
                           ingest.publication_identity.public_url
                       )
                   WHERE ingest.publication_identity.publication_id=excluded.publication_id
                     AND ROW(
                         ingest.publication_identity.source_external_id,
                         ingest.publication_identity.role,
                         ingest.publication_identity.public_url
                     ) IS DISTINCT FROM ROW(
                         COALESCE(
                             excluded.source_external_id,
                             ingest.publication_identity.source_external_id
                         ),
                         excluded.role,
                         COALESCE(
                             excluded.public_url,
                             ingest.publication_identity.public_url
                         )
                     )
                   RETURNING publication_id""",
                (
                    publication_id,
                    batch.account.id,
                    identity.external_id,
                    identity.source_external_id,
                    identity.role.value,
                    identity.public_url,
                ),
            ).fetchone()
            if identity_result is None:
                mapped = connection.execute(
                    """SELECT publication_id
                         FROM ingest.publication_identity
                        WHERE platform_account_id=%s AND external_id=%s""",
                    (batch.account.id, identity.external_id),
                ).fetchone()
                if (
                    mapped is None
                    or _row_value(mapped, "publication_id", 0) != publication_id
                ):
                    raise RuntimeError("publication identity conflict")
            else:
                identity_changed = True

        snapshot = publication.snapshot
        snapshot_row = connection.execute(
            """INSERT INTO ingest.publication_metric_snapshot(
                   published_month, publication_id, collection_run_id, observed_at,
                   collected_at, age_seconds, sampling_bucket, views_count, reactions_count,
                   comments_count, shares_count, quality, interval_uncertain,
                   synthetic, metric_semantics_version, capability_version,
                   source_fingerprint
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,1,%s)
               ON CONFLICT (published_month, publication_id, sampling_bucket)
               DO NOTHING
               RETURNING id""",
            (
                snapshot.published_month,
                publication_id,
                batch.context.run_id,
                snapshot.observed_at,
                snapshot.collected_at,
                snapshot.age_seconds,
                snapshot.sampling_bucket,
                snapshot.views_count,
                snapshot.reactions_count,
                snapshot.comments_count,
                snapshot.shares_count,
                snapshot.quality.value,
                snapshot.interval_uncertain,
                snapshot.synthetic,
                snapshot.source_fingerprint,
            ),
        ).fetchone()
        snapshot_inserted = snapshot_row is not None
        if snapshot_row is not None:
            snapshot_id = _row_value(snapshot_row, "id", 0)
            for reaction_key, reaction_count in snapshot.reaction_breakdown.items():
                connection.execute(
                    """INSERT INTO ingest.reaction_breakdown(
                           snapshot_published_month, snapshot_id,
                           reaction_key, reaction_count
                       ) VALUES (%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (
                        snapshot.published_month,
                        snapshot_id,
                        reaction_key,
                        reaction_count,
                    ),
                )
        if snapshot_inserted or publication_changed:
            self._persist_lineage(
                connection,
                batch.context.run_id,
                "publication",
                publication_id,
                snapshot.collected_at,
                snapshot.source_fingerprint,
            )
        return (
            not known,
            snapshot_inserted,
            publication_changed or identity_changed or snapshot_inserted,
        )

    def _persist_deletion_probe(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        probe: CanonicalDeletionProbe,
    ) -> bool:
        publication = connection.execute(
            """SELECT id, deleted_at
                 FROM ingest.publication
                WHERE id=%s AND primary_account_id=%s
                FOR UPDATE""",
            (probe.publication_id, batch.account.id),
        ).fetchone()
        if publication is None:
            raise RuntimeError("deletion probe publication is not owned by account")
        existing = connection.execute(
            """SELECT id
                 FROM ingest.deletion_observation
                WHERE publication_id=%s
                  AND collection_run_id=%s
                  AND observed_at=%s""",
            (probe.publication_id, batch.context.run_id, probe.observed_at),
        ).fetchone()
        if existing is not None:
            return False
        prior = connection.execute(
            """SELECT outcome::text AS outcome, consecutive_missing
                 FROM ingest.deletion_observation
                WHERE publication_id=%s
                ORDER BY observed_at DESC, id DESC
                LIMIT 1""",
            (probe.publication_id,),
        ).fetchone()
        previous_count = (
            int(_row_value(prior, "consecutive_missing", 1))
            if prior is not None else 0
        )
        outcome = probe.outcome
        if outcome == DeletionProbeOutcome.PRESENT:
            consecutive_missing = 0
        elif outcome == DeletionProbeOutcome.MISSING:
            consecutive_missing = previous_count + 1
            if consecutive_missing >= probe.confirmation_threshold:
                outcome = DeletionProbeOutcome.CONFIRMED_DELETED
        else:
            # Transient/auth/rate/ambiguous and unsupported results neither
            # increment nor clear a pending authoritative-missing sequence.
            consecutive_missing = previous_count
        inserted = connection.execute(
            """INSERT INTO ingest.deletion_observation(
                   publication_id, collection_run_id, observed_at,
                   outcome, reason_code, consecutive_missing
               ) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (publication_id, collection_run_id, observed_at)
               DO NOTHING
               RETURNING id""",
            (
                probe.publication_id,
                batch.context.run_id,
                probe.observed_at,
                outcome.value,
                probe.reason_code,
                consecutive_missing,
            ),
        ).fetchone()
        if inserted is None:
            return False
        if outcome == DeletionProbeOutcome.PRESENT:
            connection.execute(
                """UPDATE ingest.publication
                      SET deleted_at=NULL
                    WHERE id=%s AND deleted_at IS NOT NULL""",
                (probe.publication_id,),
            )
        elif outcome == DeletionProbeOutcome.CONFIRMED_DELETED:
            connection.execute(
                """UPDATE ingest.publication
                      SET deleted_at=%s
                    WHERE id=%s AND deleted_at IS NULL""",
                (probe.observed_at, probe.publication_id),
            )
        return True

    def _persist_lineage(
        self,
        connection: Any,
        run_id: UUID,
        owner_type: str,
        owner_id: UUID,
        collected_at: datetime,
        fingerprint: str,
    ) -> None:
        collected = utc(collected_at, "lineage.collected_at")
        payload_id = raw_payload_uuid(run_id, owner_type, owner_id, fingerprint)
        connection.execute(
            """INSERT INTO ingest.raw_payload(
                   id, collection_run_id, owner_type, owner_id, collected_at,
                   sha256, content_encoding, external_ref, purge_after
               ) VALUES (%s,%s,%s,%s,%s,%s,'identity',%s,%s)
               ON CONFLICT (collection_run_id, owner_type, owner_id, sha256)
               DO NOTHING""",
            (
                payload_id,
                run_id,
                owner_type,
                owner_id,
                collected,
                fingerprint,
                f"sha256:{fingerprint}",
                collected + self.raw_retention,
            ),
        )

    def _persist_cursor(self, connection: Any, batch: CanonicalAccountBatch) -> None:
        key = "collector.cursor"
        checkpoint_id = checkpoint_uuid(key, "account", batch.account.id)
        value = sanitize_evidence({
            "cursor": batch.cursor,
            "run_id": batch.context.run_id,
            "scheduled_at": batch.context.scheduled_at,
            "source_name": batch.source_name,
            "source_version": batch.source_version,
        })
        connection.execute(
            """INSERT INTO ops_and_admin.operational_checkpoint(
                   id, checkpoint_key, scope_type, scope_id, value,
                   source_observed_at, correlation_id
               ) VALUES (%s,%s,'account',%s,%s::jsonb,%s,%s)
               ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
               DO UPDATE SET
                   value=excluded.value,
                   source_observed_at=excluded.source_observed_at,
                   updated_at=transaction_timestamp(),
                   correlation_id=excluded.correlation_id""",
            (
                checkpoint_id,
                key,
                batch.account.id,
                _json(value),
                batch.context.scheduled_at,
                batch.context.correlation_id,
            ),
        )

    def _persist_refresh_cursor(
        self, connection: Any, batch: CanonicalAccountBatch,
    ) -> None:
        key = "collector.refresh_cursor.v1"
        checkpoint_id = checkpoint_uuid(key, "account", batch.account.id)
        value = sanitize_evidence({
            "cursor": batch.refresh_cursor,
            "run_id": batch.context.run_id,
            "scheduled_at": batch.context.scheduled_at,
            "source_name": batch.source_name,
            "source_version": batch.source_version,
        })
        connection.execute(
            """INSERT INTO ops_and_admin.operational_checkpoint(
                   id, checkpoint_key, scope_type, scope_id, value,
                   source_observed_at, correlation_id
               ) VALUES (%s,%s,'account',%s,%s::jsonb,%s,%s)
               ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
               DO UPDATE SET
                   value=excluded.value,
                   source_observed_at=excluded.source_observed_at,
                   updated_at=transaction_timestamp(),
                   correlation_id=excluded.correlation_id""",
            (
                checkpoint_id,
                key,
                batch.account.id,
                _json(value),
                batch.context.scheduled_at,
                batch.context.correlation_id,
            ),
        )

    @staticmethod
    def _batch_completed_at(batch: CanonicalAccountBatch) -> datetime:
        collected = [
            publication.snapshot.collected_at for publication in batch.publications
        ]
        if batch.account_observation is not None:
            collected.append(batch.account_observation.collected_at)
        collected.extend(probe.observed_at for probe in batch.deletion_probes)
        return max(collected, default=batch.context.started_at)

    def _record_revision(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        discovered_count: int,
        snapshot_count: int,
        deletion_probe_count: int,
        completed_at: datetime,
    ) -> int:
        metadata = sanitize_evidence({
            "platform": batch.context.platform,
            "partition_key": batch.context.partition_key,
            "account_id": batch.account.id,
            "scheduled_at": batch.context.scheduled_at,
            "collected_at": completed_at,
            "source_name": batch.source_name,
            "source_version": batch.source_version,
            "discovered_count": discovered_count,
            "snapshot_count": snapshot_count,
            "deletion_probe_count": deletion_probe_count,
        })
        row = connection.execute(
            """INSERT INTO analytics.dataset_revision(
                   cause, correlation_id, source_run_id, metadata
               ) VALUES ('ingestion',%s,%s,%s::jsonb)
               RETURNING id""",
            (
                batch.context.correlation_id,
                batch.context.run_id,
                _json(metadata),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("dataset revision was not created")
        revision_id = int(_row_value(row, "id", 0))
        payload = {
            "revision": revision_id,
            "run_id": batch.context.run_id,
            "account_id": batch.account.id,
            "platform": batch.context.platform,
        }
        connection.execute(
            """INSERT INTO ops_and_admin.outbox_event(
                   dataset_revision_id, event_type, aggregate_type,
                   aggregate_id, affected_tags, payload
               ) VALUES (
                   %s,'projection.rebuild.requested','platform_account',%s,%s,%s::jsonb
               )""",
            (
                revision_id,
                str(batch.account.id),
                ["publications", "overview", "comparison"],
                _json(payload),
            ),
        )
        return revision_id

    def record_account_failure(
        self,
        context: CollectionContext,
        account: AccountRef,
        completed_at: datetime,
        error_code: str,
    ) -> None:
        completed = utc(completed_at, "account.completed_at")
        code = _error_code(error_code)
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO ingest.collection_account_result(
                       collection_run_id, platform_account_id, started_at,
                       completed_at, status, sanitized_error_code
                   ) VALUES (%s,%s,%s,%s,'failed',%s)
                   ON CONFLICT (collection_run_id, platform_account_id)
                   DO UPDATE SET
                       completed_at=excluded.completed_at,
                       status='failed',
                       discovered_count=0,
                       snapshot_count=0,
                       sanitized_error_code=excluded.sanitized_error_code""",
                (
                    context.run_id,
                    account.id,
                    context.started_at,
                    completed,
                    code,
                ),
            )

    def finish_run(
        self, context: CollectionContext, completed_at: datetime,
    ) -> RunSummary:
        completed = utc(completed_at, "run.completed_at")
        with self._connection() as connection, connection.transaction():
            counts = connection.execute(
                """SELECT count(*)::integer AS account_count,
                          count(*) FILTER (WHERE status='failed')::integer AS error_count,
                          count(*) FILTER (WHERE status='succeeded')::integer AS success_count
                     FROM ingest.collection_account_result
                    WHERE collection_run_id=%s""",
                (context.run_id,),
            ).fetchone()
            account_count = int(_row_value(counts, "account_count", 0))
            error_count = int(_row_value(counts, "error_count", 1))
            success_count = int(_row_value(counts, "success_count", 2))
            if error_count == 0:
                status = RunStatus.SUCCEEDED
            elif success_count == 0:
                status = RunStatus.FAILED
            else:
                status = RunStatus.PARTIAL
            row = connection.execute(
                """UPDATE ingest.collection_run
                      SET completed_at=%s, status=%s, account_count=%s, error_count=%s
                    WHERE id=%s
                    RETURNING started_at""",
                (
                    completed,
                    status.value,
                    account_count,
                    error_count,
                    context.run_id,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("collection run was not started")
            started_at = utc(_row_value(row, "started_at", 0), "run.started_at")
        return RunSummary(
            context.run_id,
            context.platform,
            status,
            account_count,
            error_count,
            started_at,
            completed,
        )

    def fail_run(
        self, context: CollectionContext, completed_at: datetime,
    ) -> RunSummary:
        completed = utc(completed_at, "run.completed_at")
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """UPDATE ingest.collection_run AS run
                      SET completed_at=%s,
                          status='failed',
                          account_count=counts.account_count,
                          error_count=GREATEST(counts.error_count, 1)
                     FROM (
                         SELECT count(*)::integer AS account_count,
                                count(*) FILTER (
                                    WHERE status='failed'
                                )::integer AS error_count
                           FROM ingest.collection_account_result
                          WHERE collection_run_id=%s
                     ) AS counts
                    WHERE run.id=%s
                    RETURNING run.started_at, run.account_count, run.error_count""",
                (completed, context.run_id, context.run_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("collection run was not started")
            started_at = utc(_row_value(row, "started_at", 0), "run.started_at")
            account_count = int(_row_value(row, "account_count", 1))
            error_count = int(_row_value(row, "error_count", 2))
        return RunSummary(
            context.run_id,
            context.platform,
            RunStatus.FAILED,
            account_count,
            error_count,
            started_at,
            completed,
        )
