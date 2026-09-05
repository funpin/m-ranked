from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from collector_target.lease import advisory_lock_key, lease_name
from collector_target.model import Platform

from .model import Revision, SyncPlan, canonical_value, require_revision_ids, utc_now


ACCOUNT_SQL = """
SELECT account.id,
       account.institution_id,
       account.platform::text AS platform,
       account.canonical_external_id,
       account.current_username,
       account.current_title,
       account.current_url,
       account.access_mode::text AS access_mode,
       account.enabled,
       account.created_at,
       institution.canonical_name AS institution_name,
       institution.short_name AS institution_short_name,
       institution_alias.legacy_id AS institution_legacy_id,
       account_alias.legacy_id AS account_legacy_id,
       channel_alias.legacy_id AS channel_legacy_id,
       native_identity.external_id AS native_external_id,
       metric.has_snapshot,
       metric.subscriber_count,
       metric.subscriber_display,
       metric.observed_at AS subscriber_observed_at,
       metric.quality::text AS subscriber_quality,
       result.started_at AS result_started_at,
       result.completed_at AS result_completed_at,
       result.status::text AS result_status,
       result.sanitized_error_code,
       cursor_state.value->>'cursor' AS collector_cursor
FROM catalog.platform_account AS account
JOIN catalog.institution AS institution ON institution.id=account.institution_id
LEFT JOIN catalog.legacy_entity_alias AS institution_alias
  ON institution_alias.entity_type='institutions'
 AND institution_alias.target_uuid=institution.id
LEFT JOIN catalog.legacy_entity_alias AS account_alias
  ON account_alias.entity_type='platform_accounts'
 AND account_alias.target_uuid=account.id
LEFT JOIN catalog.legacy_entity_alias AS channel_alias
  ON channel_alias.entity_type='channels'
 AND channel_alias.target_uuid=account.id
LEFT JOIN LATERAL (
    SELECT identity.external_id
    FROM catalog.account_external_identity AS identity
    WHERE identity.platform_account_id=account.id
      AND identity.identity_namespace=concat(account.platform::text, ':native_id')
      AND identity.valid_to IS NULL
    ORDER BY identity.valid_from DESC, identity.id DESC
    LIMIT 1
) AS native_identity ON true
LEFT JOIN LATERAL (
    SELECT true AS has_snapshot,
           snapshot.subscriber_count,
           snapshot.subscriber_display,
           snapshot.observed_at,
           snapshot.quality
    FROM ingest.account_metric_snapshot AS snapshot
    WHERE snapshot.platform_account_id=account.id
    ORDER BY snapshot.observed_at DESC, snapshot.id DESC
    LIMIT 1
) AS metric ON true
LEFT JOIN LATERAL (
    SELECT item.started_at,
           item.completed_at,
           item.status,
           item.sanitized_error_code
    FROM ingest.collection_account_result AS item
    WHERE item.platform_account_id=account.id
    ORDER BY item.started_at DESC, item.id DESC
    LIMIT 1
) AS result ON true
LEFT JOIN ops_and_admin.operational_checkpoint AS cursor_state
  ON cursor_state.checkpoint_key='collector.cursor'
 AND cursor_state.scope_type='account'
 AND cursor_state.scope_id=account.id
WHERE account.id=ANY(%s::uuid[])
ORDER BY account.platform, account.id
"""


PUBLICATION_SQL = """
SELECT publication.id,
       publication.primary_account_id,
       account.platform::text AS platform,
       publication.content_group_id,
       publication.published_at,
       publication.discovered_at,
       publication.first_observation_age_seconds,
       publication.publication_type,
       publication.is_repost,
       publication.history_completeness::text AS history_completeness,
       publication.synthetic_baseline_allowed,
       publication.quality_flags,
       publication.deleted_at,
       publication.created_at,
       CASE WHEN account.platform='telegram'
            THEN post_alias.legacy_id
            ELSE platform_post_alias.legacy_id
       END AS legacy_id,
       account_alias.legacy_id AS account_legacy_id,
       channel_alias.legacy_id AS channel_legacy_id,
       identities.items AS identities,
       deletion.observed_at AS deletion_observed_at,
       deletion.outcome::text AS deletion_outcome,
       deletion.reason_code AS deletion_reason_code,
       deletion.consecutive_missing
FROM ingest.publication AS publication
JOIN catalog.platform_account AS account ON account.id=publication.primary_account_id
LEFT JOIN catalog.legacy_entity_alias AS post_alias
  ON post_alias.entity_type='posts' AND post_alias.target_uuid=publication.id
LEFT JOIN catalog.legacy_entity_alias AS platform_post_alias
  ON platform_post_alias.entity_type='platform_posts'
 AND platform_post_alias.target_uuid=publication.id
LEFT JOIN catalog.legacy_entity_alias AS account_alias
  ON account_alias.entity_type='platform_accounts'
 AND account_alias.target_uuid=account.id
LEFT JOIN catalog.legacy_entity_alias AS channel_alias
  ON channel_alias.entity_type='channels'
 AND channel_alias.target_uuid=account.id
JOIN LATERAL (
    SELECT jsonb_agg(
               jsonb_build_object(
                   'id', identity.id,
                   'publication_id', identity.publication_id,
                   'platform_account_id', identity.platform_account_id,
                   'external_id', identity.external_id,
                   'source_external_id', identity.source_external_id,
                   'role', identity.role::text,
                   'public_url', identity.public_url
               ) ORDER BY identity.role, identity.id
           ) AS items
    FROM ingest.publication_identity AS identity
    WHERE identity.publication_id=publication.id
) AS identities ON true
LEFT JOIN LATERAL (
    SELECT item.observed_at,
           item.outcome,
           item.reason_code,
           item.consecutive_missing
    FROM ingest.deletion_observation AS item
    WHERE item.publication_id=publication.id
      AND item.outcome IN ('present','missing','confirmed_deleted')
    ORDER BY item.observed_at DESC, item.id DESC
    LIMIT 1
) AS deletion ON true
WHERE publication.primary_account_id=ANY(%s::uuid[])
ORDER BY account.platform, publication.published_at, publication.id
"""


SNAPSHOT_SQL = """
SELECT snapshot.published_month,
       snapshot.id,
       snapshot.publication_id,
       snapshot.collection_run_id,
       account.platform::text AS platform,
       publication.published_at,
       snapshot.observed_at,
       snapshot.collected_at,
       snapshot.age_seconds,
       snapshot.sampling_bucket,
       snapshot.views_count,
       snapshot.reactions_count,
       snapshot.comments_count,
       snapshot.shares_count,
       snapshot.quality::text AS quality,
       snapshot.interval_uncertain,
       snapshot.synthetic,
       snapshot.metric_semantics_version,
       snapshot.capability_version,
       snapshot.source_fingerprint,
       snapshot.created_at,
       CASE WHEN account.platform='telegram'
            THEN post_alias.legacy_id
            ELSE platform_post_alias.legacy_id
       END AS publication_legacy_id,
       COALESCE(reactions.breakdown, '{}'::jsonb) AS reaction_breakdown
FROM ingest.publication_metric_snapshot AS snapshot
JOIN ingest.publication AS publication ON publication.id=snapshot.publication_id
JOIN catalog.platform_account AS account ON account.id=publication.primary_account_id
LEFT JOIN catalog.legacy_entity_alias AS post_alias
  ON post_alias.entity_type='posts' AND post_alias.target_uuid=publication.id
LEFT JOIN catalog.legacy_entity_alias AS platform_post_alias
  ON platform_post_alias.entity_type='platform_posts'
 AND platform_post_alias.target_uuid=publication.id
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(item.reaction_key, item.reaction_count ORDER BY item.reaction_key)
           AS breakdown
    FROM ingest.reaction_breakdown AS item
    WHERE item.snapshot_published_month=snapshot.published_month
      AND item.snapshot_id=snapshot.id
) AS reactions ON true
WHERE snapshot.collection_run_id=ANY(%s::uuid[])
ORDER BY snapshot.published_month, snapshot.id
"""


class PostgresReverseSource:
    def __init__(self, dsn: str, source_namespace: str):
        if not str(dsn).strip():
            raise ValueError("PostgreSQL DSN must not be blank")
        if not str(source_namespace).strip():
            raise ValueError("source namespace must not be blank")
        self._dsn = str(dsn)
        self.source_namespace = str(source_namespace).strip()

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection[Any]]:
        connection = psycopg.connect(
            self._dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
            application_name="mranked-pg-to-legacy-sync",
        )
        try:
            connection.execute("SET TIME ZONE 'UTC'")
            connection.execute("SET statement_timeout='5min'")
            yield connection
        finally:
            connection.close()

    def preflight(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT current_database() AS database_name,
                          current_user AS role_name,
                          has_table_privilege(
                              current_user, 'catalog.legacy_entity_alias',
                              'SELECT,INSERT'
                          ) AS alias_privileges"""
            ).fetchone()
            privileges = connection.execute(
                """WITH required(relation_name) AS (VALUES
                       ('migration.import_batch'),
                       ('analytics.dataset_revision'),
                       ('catalog.legacy_entity_alias'),
                       ('catalog.institution'),
                       ('catalog.platform_account'),
                       ('catalog.account_external_identity'),
                       ('ingest.collection_run'),
                       ('ingest.collection_account_result'),
                       ('ingest.account_metric_snapshot'),
                       ('ingest.publication'),
                       ('ingest.publication_identity'),
                       ('ingest.publication_metric_snapshot'),
                       ('ingest.reaction_breakdown'),
                       ('ingest.deletion_observation'),
                       ('ops_and_admin.operational_checkpoint')
                   )
                   SELECT bool_and(to_regclass(relation_name) IS NOT NULL)
                              AS schema_complete,
                          bool_and(coalesce(has_table_privilege(
                              current_user, to_regclass(relation_name), 'SELECT'
                          ), false)) AS select_privileges
                   FROM required"""
            ).fetchone()
            ambiguity = connection.execute(
                """SELECT count(*) AS count
                   FROM (
                       SELECT entity_type, target_uuid
                       FROM catalog.legacy_entity_alias
                       GROUP BY entity_type, target_uuid
                       HAVING count(*)<>1
                   ) AS invalid"""
            ).fetchone()
            multiple_primary = connection.execute(
                """SELECT count(*) AS count
                   FROM (
                       SELECT publication.id
                       FROM ingest.publication
                       LEFT JOIN ingest.publication_identity AS identity
                         ON identity.publication_id=publication.id
                        AND identity.role='primary'
                       GROUP BY publication.id
                       HAVING count(identity.id)<>1
                   ) AS invalid"""
            ).fetchone()
        if not row or not privileges or not privileges["schema_complete"]:
            raise RuntimeError("target schema is incomplete")
        if not privileges["select_privileges"]:
            raise RuntimeError("reverse-sync role lacks required read privileges")
        if not row["alias_privileges"]:
            raise RuntimeError("reverse-sync role cannot reserve legacy aliases")
        if int(ambiguity["count"]) != 0:
            raise RuntimeError("legacy alias mapping is ambiguous")
        if int(multiple_primary["count"]) != 0:
            raise RuntimeError("a publication does not have exactly one primary identity")
        return {
            "database": row["database_name"],
            "role": row["role_name"],
            "requiredSelectPrivileges": True,
            "aliasMappingsUnambiguous": True,
            "singlePrimaryIdentity": True,
        }

    @contextmanager
    def drain_lock(self) -> Iterator[psycopg.Connection[Any]]:
        with self.connect() as connection:
            global_key = advisory_lock_key(
                f"reverse-sync:{self.source_namespace}:drain"
            )
            if not self._try_lock(connection, global_key):
                raise RuntimeError("another reverse-sync process owns the drain lock")
            partitions = {
                (platform.value, "default") for platform in Platform
            }
            rows = connection.execute(
                "SELECT DISTINCT platform::text AS platform, partition_key "
                "FROM ingest.collection_run"
            ).fetchall()
            partitions.update(
                (str(row["platform"]), str(row["partition_key"])) for row in rows
            )
            acquired: list[int] = [global_key]
            try:
                for platform, partition_key in sorted(partitions):
                    lock_key = advisory_lock_key(
                        lease_name(Platform(platform), partition_key)
                    )
                    if not self._try_lock(connection, lock_key):
                        raise RuntimeError(
                            f"collector lease is active for {platform}/{partition_key}"
                        )
                    acquired.append(lock_key)
                yield connection
            finally:
                for lock_key in reversed(acquired):
                    connection.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    @staticmethod
    def _try_lock(connection: psycopg.Connection[Any], lock_key: int) -> bool:
        row = connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (lock_key,)
        ).fetchone()
        return bool(row and row["acquired"])

    def s_final(self, connection: psycopg.Connection[Any]) -> Mapping[str, Any]:
        row = connection.execute(
            """SELECT id, source_sha256, source_snapshot_at, finished_at, metadata
               FROM migration.import_batch
               WHERE source_name=%s
                 AND snapshot_kind='s_final'
                 AND status='succeeded'
                 AND dry_run=false
               ORDER BY finished_at DESC, started_at DESC
               LIMIT 1""",
            (self.source_namespace,),
        ).fetchone()
        if row is None:
            raise RuntimeError("no successful S-final import is bound to this namespace")
        return canonical_value(row)

    def revisions(
        self, connection: psycopg.Connection[Any]
    ) -> tuple[Revision, ...]:
        rows = connection.execute(
            """SELECT id, cause::text AS cause, source_run_id, committed_at,
                      correlation_id, metadata
               FROM analytics.dataset_revision
               ORDER BY id"""
        ).fetchall()
        return tuple(
            Revision(
                id=int(row["id"]),
                cause=str(row["cause"]),
                source_run_id=(
                    UUID(str(row["source_run_id"]))
                    if row["source_run_id"] is not None else None
                ),
                committed_at=row["committed_at"],
                correlation_id=UUID(str(row["correlation_id"])),
                metadata=row["metadata"] or {},
            )
            for row in rows
        )

    def build_plan(
        self,
        connection: psycopg.Connection[Any],
        *,
        baseline_revision_ids: Sequence[int],
        started_at: datetime,
    ) -> SyncPlan:
        baseline = require_revision_ids(baseline_revision_ids)
        baseline_set = set(baseline)
        all_revisions = self.revisions(connection)
        visible_ids = {item.id for item in all_revisions}
        if not set(baseline).issubset(visible_ids):
            raise RuntimeError("baseline dataset revision set is no longer visible")
        delta = tuple(item for item in all_revisions if item.id not in baseline_set)
        unsupported = [item for item in delta if item.cause != "ingestion"]
        if unsupported:
            raise RuntimeError(
                "rollback window contains a non-ingestion dataset revision"
            )
        revision_ids = tuple(item.id for item in delta)
        run_ids = tuple(
            dict.fromkeys(
                item.source_run_id for item in delta if item.source_run_id is not None
            )
        )
        if any(item.source_run_id is None for item in delta):
            raise RuntimeError("ingestion revision is missing source_run_id")
        revision_accounts: set[UUID] = set()
        for revision in delta:
            raw_account = revision.metadata.get("account_id")
            if raw_account is None:
                raise RuntimeError("ingestion revision is missing account_id metadata")
            revision_accounts.add(UUID(str(raw_account)))
        result_rows = connection.execute(
            """SELECT DISTINCT result.platform_account_id
               FROM ingest.collection_account_result AS result
               JOIN ingest.collection_run AS run ON run.id=result.collection_run_id
               WHERE run.started_at >= %s""",
            (started_at,),
        ).fetchall()
        revision_accounts.update(
            UUID(str(row["platform_account_id"])) for row in result_rows
        )
        account_ids = tuple(sorted(revision_accounts, key=str))
        accounts = self._rows(connection, ACCOUNT_SQL, (list(account_ids),)) if account_ids else ()
        publications = (
            self._rows(connection, PUBLICATION_SQL, (list(account_ids),))
            if account_ids else ()
        )
        snapshots = (
            self._rows(connection, SNAPSHOT_SQL, (list(run_ids),)) if run_ids else ()
        )
        collection_runs = self._rows(
            connection,
            """SELECT run.id, run.platform::text AS platform, run.partition_key,
                      run.collector_version, run.started_at, run.scheduled_at,
                      run.completed_at, run.status::text AS status,
                      run.account_count, run.error_count
               FROM ingest.collection_run AS run
               WHERE run.started_at >= %s
               ORDER BY run.started_at, run.id""",
            (started_at,),
        )
        return SyncPlan(
            baseline_revision_ids=baseline,
            revision_ids=revision_ids,
            revisions=delta,
            accounts=accounts,
            publications=publications,
            snapshots=snapshots,
            collection_runs=collection_runs,
            generated_at=utc_now(),
        )

    def reserve_publication_aliases(
        self,
        connection: psycopg.Connection[Any],
        publications: Sequence[Mapping[str, Any]],
        *,
        sqlite_maximums: Mapping[str, int],
    ) -> dict[UUID, tuple[str, int]]:
        result: dict[UUID, tuple[str, int]] = {}
        next_ids: dict[str, int] = {}
        for entity_type in ("posts", "platform_posts"):
            row = connection.execute(
                """SELECT coalesce(max(legacy_id),0) AS maximum
                   FROM catalog.legacy_entity_alias WHERE entity_type=%s""",
                (entity_type,),
            ).fetchone()
            next_ids[entity_type] = max(
                int(row["maximum"]), int(sqlite_maximums.get(entity_type, 0))
            )
        with connection.transaction():
            for publication in publications:
                publication_id = UUID(str(publication["id"]))
                entity_type = (
                    "posts" if publication["platform"] == "telegram"
                    else "platform_posts"
                )
                existing = connection.execute(
                    """SELECT legacy_id FROM catalog.legacy_entity_alias
                       WHERE entity_type=%s AND target_uuid=%s""",
                    (entity_type, publication_id),
                ).fetchone()
                if existing is None:
                    next_ids[entity_type] += 1
                    legacy_id = next_ids[entity_type]
                    route = (
                        f"/posts/{legacy_id}"
                        if entity_type == "posts"
                        else f"/platform-posts/{legacy_id}"
                    )
                    inserted = connection.execute(
                        """INSERT INTO catalog.legacy_entity_alias(
                               entity_type,legacy_id,target_uuid,legacy_route
                           ) VALUES(%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING
                           RETURNING legacy_id""",
                        (entity_type, legacy_id, publication_id, route),
                    ).fetchone()
                    if inserted is None:
                        raise RuntimeError("publication legacy alias reservation conflicted")
                else:
                    legacy_id = int(existing["legacy_id"])
                result[publication_id] = (entity_type, legacy_id)
        return result

    @staticmethod
    def _rows(
        connection: psycopg.Connection[Any],
        sql: str,
        params: tuple[Any, ...],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(canonical_value(row) for row in connection.execute(sql, params).fetchall())
