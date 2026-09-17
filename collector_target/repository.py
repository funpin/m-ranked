from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
import re
import os
import threading
from pathlib import Path
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
from .normalize import canonical_json, sanitize_evidence, source_fingerprint
from .evidence import ImmutableEvidenceStore


_SHARD = re.compile(r"^(\d+)/(\d+)$")
_SAFE_ERROR_CODE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]{0,79}(?::[A-Za-z0-9_.-]{1,80})?$"
)
_EXPECTED_SCHEMA_CONTRACT = "live-read-2026-09-13-text-fingerprint"


def _persist_raw_evidence() -> bool:
    """Читает COLLECTOR_PERSIST_RAW_EVIDENCE; по умолчанию включено."""
    raw = os.environ.get("COLLECTOR_PERSIST_RAW_EVIDENCE", "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError("COLLECTOR_PERSIST_RAW_EVIDENCE must be true or false")

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
        snapshot_heartbeat_hours: int = 24,
        evidence_store: ImmutableEvidenceStore | None = None,
        pool_size: int = 3,
    ) -> None:
        if connection_factory is None and not dsn:
            raise ValueError("dsn or connection_factory is required")
        if pool_size < 2:
            # Меньше двух нельзя: словарь свидетельств берёт собственное
            # соединение внутри уже открытого батча, и на единственном
            # соединении это встало бы намертво.
            raise ValueError("pool_size must be at least 2")
        if raw_retention_days < 1:
            raise ValueError("raw_retention_days must be positive")
        if statement_timeout_seconds < 1:
            raise ValueError("statement_timeout_seconds must be positive")
        if snapshot_heartbeat_hours < 1:
            raise ValueError("snapshot_heartbeat_hours must be positive")
        self._factory = connection_factory or self._psycopg_factory(str(dsn))
        # Пул поднимается только для собственного DSN: подставленная фабрика
        # соединений принадлежит вызывающему, и её жизненным циклом
        # распоряжается он.
        self._dsn = None if connection_factory is not None else str(dsn)
        self._pool_size = pool_size
        self._pool: Any = None
        self._pool_lock = threading.Lock()
        self.raw_retention = timedelta(days=raw_retention_days)
        self.statement_timeout_seconds = statement_timeout_seconds
        self.snapshot_heartbeat = timedelta(hours=snapshot_heartbeat_hours)
        self.evidence_store = evidence_store or ImmutableEvidenceStore(
            Path(os.environ.get("COLLECTOR_RAW_EVIDENCE_DIR", "data/target-raw-evidence"))
        )
        self._metric_evidence_ids: dict[str, int] = {}
        self._metric_evidence_lock = threading.Lock()

    @staticmethod
    def _metric_evidence(snapshot: Any) -> dict[str, Any]:
        return {
            metric: {
                "source_field": metric,
                "quality": quality.value,
                "flags": {
                    "unsupported_or_missing": getattr(snapshot, metric + "_count") is None,
                    "suspected_reset": quality.value == "suspected_reset",
                    "invalid": quality.value == "invalid",
                },
            }
            for metric, quality in snapshot.metric_quality.items()
        }

    def _metric_evidence_id(self, evidence: Mapping[str, Any]) -> int:
        payload = _json(evidence)
        with self._metric_evidence_lock:
            cached = self._metric_evidence_ids.get(payload)
            if cached is not None:
                return cached
            # Dictionary rows are immutable and harmless until referenced. Commit
            # them independently so a later observation rollback cannot poison
            # the process-local id cache.
            with self._connection() as connection:
                for _ in range(3):
                    row = connection.execute(
                        """WITH value(payload) AS (VALUES (%s::jsonb)), inserted AS (
                               INSERT INTO ingest.metric_evidence_dictionary(payload,payload_sha256)
                               SELECT payload,sha256(convert_to(payload::text,'UTF8')) FROM value
                               ON CONFLICT(payload_sha256) DO NOTHING RETURNING id
                           ) SELECT id FROM inserted UNION ALL
                           SELECT dictionary.id FROM ingest.metric_evidence_dictionary dictionary,value
                           WHERE dictionary.payload_sha256=sha256(convert_to(value.payload::text,'UTF8'))
                           LIMIT 1""",
                        (payload,),
                    ).fetchone()
                    if row is not None:
                        result = int(_row_value(row, "id", 0))
                        self._metric_evidence_ids[payload] = result
                        return result
            raise RuntimeError("metric evidence dictionary race did not converge")

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

    def _prepare_session(self, connection: Any) -> None:
        """Настройки сеанса, одинаковые для любого соединения."""
        connection.execute("SET TIME ZONE 'UTC'")
        connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (f"{self.statement_timeout_seconds}s",),
        )

    def _ensure_pool(self) -> Any:
        """Пул соединений, открываемый при первом обращении.

        Прежде каждый вызов репозитория поднимал собственное соединение и
        закрывал его: около трёх новых обслуживающих процессов в секунду.
        Дорога не сама установка соединения, а то, что вместе с ней теряется
        кэш планов. Снимки разложены по 63 партициям, и планирование одного
        запроса по ним занимало от 100 до 360 миллисекунд — на каждый вызов.
        Переиспользованное соединение готовит запрос один раз.
        """
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool

                self._pool = ConnectionPool(
                    self._dsn,
                    min_size=1,
                    max_size=self._pool_size,
                    max_idle=300.0,
                    timeout=30.0,
                    kwargs={"autocommit": True, "row_factory": dict_row},
                    configure=self._prepare_session,
                    # База живёт в контейнере и переживает перезапуски. Проверка
                    # при выдаче стоит одного обращения и избавляет от отказа
                    # цикла на соединении, оборванном с той стороны.
                    check=ConnectionPool.check_connection,
                    open=False,
                )
                self._pool.open()
        return self._pool

    def close(self) -> None:
        """Закрывает пул. Соединения из подставленной фабрики не трогает."""
        with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self._dsn is not None:
            with self._ensure_pool().connection() as connection:
                yield connection
            return
        connection = self._factory()
        try:
            self._prepare_session(connection)
            yield connection
        finally:
            connection.close()

    def assert_schema_contract(self) -> None:
        """Fail closed before a collector writes against an incompatible DB."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT contract_id FROM ops_and_admin.schema_contract"
            ).fetchone()
        contract = None if row is None else _row_value(row, "contract_id", 0)
        if contract != _EXPECTED_SCHEMA_CONTRACT:
            raise RuntimeError(
                "database schema contract mismatch: "
                f"expected {_EXPECTED_SCHEMA_CONTRACT!r}, found {contract!r}"
            )

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
                      -- Only a genuinely unfinished process-owned run is
                      -- resumable. Completed partial/failed runs must not pin
                      -- the scheduler to one old slot forever when an account
                      -- has a persistent provider error; the next cycle polls
                      -- every healthy account again under a new run id.
                      AND status = 'running'
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

    def metric_ever_positive(
        self,
        account: AccountRef,
        external_ids: Sequence[str],
    ) -> Mapping[str, Mapping[str, bool]]:
        """Был ли каждый показатель публикации положительным в недавних замерах.

        Распознавание временных обнулений у ВК спрашивает именно это, а не
        величину прежнего максимума. Максимум считался по всей истории снимков
        публикации — в среднем 335 строк на каждую, и на сотне публикаций это
        167 тысяч буферов и больше секунды.

        Окно ограничено двумя дюжинами последних замеров, и вот почему.
        Проверка существования без окна выходит быстрее, когда показатель был
        положительным: она останавливается на первой же подходящей строке, 50
        мс. Но если положительным он не был ни разу — а у ВК это обычное дело
        для комментариев и репостов, — останавливаться не на чем, и читается
        вся история: 1357 мс на том же аккаунте. Окно убирает этот худший
        случай: замер на проде вперемежку дал 1610/92/50 мс без окна против
        180/154/129 с ним. Чуть хуже в лучшем случае, гораздо лучше в худшем.

        Двух дюжин хватает с запасом: свежие публикации опрашиваются раз в пять
        минут, старые — раз в час, то есть окно покрывает от полутора часов до
        суток наблюдений, а обнуление у ВК живёт минуты.

        Месяц публикации — ключ партиционирования снимков — вычисляется из
        самой публикации и передаётся явно, иначе поиск идёт по всем 63
        партициям.
        """
        requested = tuple(dict.fromkeys(str(value) for value in external_ids if value))
        if not requested:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                """WITH scope AS MATERIALIZED (
                       SELECT identity.publication_id, identity.external_id,
                              date_trunc('month', publication.published_at)::date
                                  AS published_month
                         FROM ingest.publication_identity AS identity
                         JOIN ingest.publication AS publication
                           ON publication.id=identity.publication_id
                        WHERE identity.platform_account_id=%s
                          AND identity.external_id=ANY(%s)
                   )
                   SELECT scope.external_id,
                          -- Ни одного замера — публикация новая, её ноль
                          -- настоящий. Замеры есть, но по этому показателю все
                          -- пустые — значит, обнуление уже распознано и длится,
                          -- и ответ осторожный: иначе пустота записалась бы как
                          -- настоящий ноль.
                          CASE WHEN coalesce(recent.rows, 0)=0 THEN false
                               WHEN recent.views_seen=0 THEN true
                               ELSE coalesce(recent.views, false) END AS views,
                          CASE WHEN coalesce(recent.rows, 0)=0 THEN false
                               WHEN recent.reactions_seen=0 THEN true
                               ELSE coalesce(recent.reactions, false) END AS reactions,
                          CASE WHEN coalesce(recent.rows, 0)=0 THEN false
                               WHEN recent.comments_seen=0 THEN true
                               ELSE coalesce(recent.comments, false) END AS comments,
                          CASE WHEN coalesce(recent.rows, 0)=0 THEN false
                               WHEN recent.shares_seen=0 THEN true
                               ELSE coalesce(recent.shares, false) END AS shares
                     FROM scope
                     LEFT JOIN LATERAL (
                         SELECT count(*) AS rows,
                                count(recent_rows.views_count) AS views_seen,
                                count(recent_rows.reactions_count) AS reactions_seen,
                                count(recent_rows.comments_count) AS comments_seen,
                                count(recent_rows.shares_count) AS shares_seen,
                                bool_or(recent_rows.views_count>0) AS views,
                                bool_or(recent_rows.reactions_count>0) AS reactions,
                                bool_or(recent_rows.comments_count>0) AS comments,
                                bool_or(recent_rows.shares_count>0) AS shares
                           FROM (SELECT snapshot.views_count, snapshot.reactions_count,
                                        snapshot.comments_count, snapshot.shares_count
                                   FROM ingest.publication_metric_snapshot_active snapshot
                                  WHERE snapshot.publication_id=scope.publication_id
                                    AND snapshot.published_month=scope.published_month
                                  ORDER BY snapshot.observed_at DESC, snapshot.id DESC
                                  LIMIT 24) recent_rows
                     ) recent ON true""",
                (account.id, list(requested)),
            ).fetchall()
        return {
            str(_row_value(row, "external_id", 0)): {
                "views": bool(_row_value(row, "views", 1)),
                "reactions": bool(_row_value(row, "reactions", 2)),
                "comments": bool(_row_value(row, "comments", 3)),
                "shares": bool(_row_value(row, "shares", 4)),
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
                     -- Месяц публикации — ключ партиционирования снимков, и
                     -- он же вычисляется из самой публикации. Без него поиск
                     -- последнего замера шёл по всем партициям на каждую
                     -- строку выдачи.
                     LEFT JOIN LATERAL (
                         SELECT snapshot.observed_at, snapshot.sampling_bucket
                           FROM ingest.publication_metric_snapshot_active AS snapshot
                          WHERE snapshot.publication_id=publication.id
                            AND snapshot.published_month
                                =date_trunc('month', publication.published_at)::date
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
        identity_receipt = None
        metric_evidence_ids = tuple(
            self._metric_evidence_id(
                self._metric_evidence(publication.snapshot)
            )
            for publication in batch.publications
        )
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
                if identity_changed:
                    from .identity_evidence import IdentityEvidenceStore, configured_root
                    # Source fields come from the already sanitized original
                    # observation, before any database state is read as output.
                    original = batch.account_observation.sanitized_source
                    receipt = {
                        "version": 1, "kind": "collector-account-identity",
                        "accountId": str(batch.account.id), "platform": batch.context.platform.value,
                        "sourceRunId": str(batch.context.run_id),
                        "sourceFingerprint": batch.account_observation.source_fingerprint,
                        "observedAt": original["observed_at"],
                        "username": original.get("username"), "title": original.get("title"),
                        "url": original.get("url"), "nativeId": original.get("native_external_id"),
                    }
                    identity_receipt = IdentityEvidenceStore(configured_root()/"collector"/batch.context.platform.value).put(receipt)

            publication_results = self._persist_publications(
                connection, batch, metric_evidence_ids,
            )
            persisted_ids = {}
            for publication, publication_result in zip(
                batch.publications, publication_results, strict=True,
            ):
                publication_id, discovered, snapshot, publication_changed = (
                    publication_result
                )
                persisted_ids[publication.id] = publication_id
                discovered_count += int(discovered)
                snapshot_count += int(snapshot)
                changed = changed or publication_changed

            # Imported publications retain their legacy UUID. Use the identity
            # resolved while persisting, including when suppressing presence
            # probes in favor of an explicit probe from the tracked record.
            explicit_probes = tuple(
                replace(probe, publication_id=persisted_ids.get(
                    probe.publication_id, probe.publication_id,
                ))
                for probe in batch.deletion_probes
            )
            explicit_probe_ids = {probe.publication_id for probe in explicit_probes}
            presence_by_id: dict[UUID, CanonicalDeletionProbe] = {}
            for publication in batch.publications:
                publication_id = persisted_ids[publication.id]
                if (
                    publication_id in explicit_probe_ids
                    or publication.snapshot.synthetic
                ):
                    continue
                candidate = CanonicalDeletionProbe(
                    persisted_ids[publication.id],
                    publication.snapshot.observed_at,
                    DeletionProbeOutcome.PRESENT,
                    f"{batch.context.platform.value}_publication_observed",
                    2,
                )
                previous = presence_by_id.get(publication_id)
                if previous is None or previous.observed_at < candidate.observed_at:
                    presence_by_id[publication_id] = candidate
            presence_probes = tuple(presence_by_id.values())
            presence_changes = self._persist_presence_probes(
                connection, batch, presence_probes,
            )
            deletion_probe_count += presence_changes
            changed = changed or presence_changes > 0
            for probe in explicit_probes:
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
                    identity_receipt,
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
        latest_state = connection.execute(
            """SELECT semantic_fingerprint, observed_at
                 FROM ingest.account_metric_snapshot_active
                WHERE platform_account_id=%s
                ORDER BY observed_at DESC, id DESC
                LIMIT 1""",
            (batch.account.id,),
        ).fetchone()
        unchanged = (
            latest_state is not None
            and _row_value(latest_state, "semantic_fingerprint", 0) is not None
            and bytes(_row_value(latest_state, "semantic_fingerprint", 0))
                == observation.semantic_fingerprint
        )
        heartbeat_due = (
            latest_state is None
            or observation.observed_at - utc(
                _row_value(latest_state, "observed_at", 1),
                "account_snapshot.observed_at",
            ) >= self.snapshot_heartbeat
        )
        if unchanged and not heartbeat_due:
            return False
        row = connection.execute(
            """INSERT INTO ingest.account_metric_snapshot(
                   platform_account_id, collection_run_id, observed_at,
                   collected_at, subscriber_count, subscriber_display, quality,
                   source_fingerprint, semantic_fingerprint
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                observation.semantic_fingerprint,
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
            observation.sanitized_source,
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
            username = observation.username or (_row_value(current,"username",1) if current is not None else account.current_username)
            title = observation.title or (_row_value(current,"title",2) if current is not None else account.current_title)
            url = observation.url or (_row_value(current,"url",3) if current is not None else account.current_url)
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
                if current_native is None:
                    boundary = connection.execute(
                        """SELECT max(valid_to) AS last_closed FROM catalog.account_external_identity
                            WHERE platform_account_id=%s AND identity_namespace=%s""",
                        (account.id, namespace),
                    ).fetchone()
                    last_closed = _row_value(boundary, "last_closed", 0) if boundary is not None else None
                    if last_closed is not None and observation.observed_at <= utc(last_closed, "external_identity.last_closed"):
                        raise RuntimeError("account native identity time collision")
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

    def _persist_publications(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        metric_evidence_ids: Sequence[int],
    ) -> tuple[tuple[UUID, bool, bool, bool], ...]:
        publications = batch.publications
        if not publications:
            return ()
        if any(item.account_id != batch.account.id for item in publications):
            raise ValueError("publication account does not match batch account")
        external_ids = list(dict.fromkeys(
            item.external_id for item in publications
        ))

        # A stable order prevents two overlapping account batches from taking
        # the same advisory locks in opposite order.
        lock_names = sorted(
            f"publication:{batch.account.id}:{external_id}"
            for external_id in external_ids
        )
        connection.execute(
            """SELECT pg_advisory_xact_lock(hashtextextended(lock_name, 0))
                 FROM unnest(%s::text[]) AS locks(lock_name)
                ORDER BY lock_name""",
            (lock_names,),
        )
        identity_rows = connection.execute(
            """SELECT external_id, publication_id
                 FROM ingest.publication_identity
                WHERE platform_account_id=%s AND external_id=ANY(%s::text[])""",
            (batch.account.id, external_ids),
        ).fetchall()
        existing_ids = {
            str(_row_value(row, "external_id", 0)):
                _row_value(row, "publication_id", 1)
            for row in identity_rows
        }
        resolved_ids = {
            item.id: existing_ids.get(item.external_id, item.id)
            for item in publications
        }

        content_groups = [
            {
                "id": item.content_group_id,
                "group_type": f"{batch.context.platform.value}_logical_group",
            }
            for item in publications
            if item.content_group_id is not None
        ]
        if content_groups:
            connection.execute(
                """INSERT INTO ingest.content_group(id, group_type)
                   SELECT item.id, item.group_type
                     FROM jsonb_to_recordset(%s::jsonb)
                       AS item(id uuid, group_type text)
                   ON CONFLICT (id) DO NOTHING""",
                (_json(content_groups),),
            )

        publication_by_resolved_id: dict[UUID, CanonicalPublication] = {}
        for item in publications:
            publication_by_resolved_id.setdefault(resolved_ids[item.id], item)
        publication_input = [
            {
                "source_id": item.id,
                "id": publication_id,
                "primary_account_id": batch.account.id,
                "content_group_id": item.content_group_id,
                "published_at": item.published_at,
                "discovered_at": item.discovered_at,
                "first_observation_age_seconds": max(
                    0,
                    int((item.discovered_at - item.published_at).total_seconds()),
                ),
                "publication_type": item.publication_type,
                "is_repost": item.is_repost,
                "history_completeness": item.history_completeness.value,
                "synthetic_baseline_allowed": item.synthetic_baseline_allowed,
                "quality_flags": item.quality_flags,
            }
            for publication_id, item in publication_by_resolved_id.items()
        ]
        changed_rows = connection.execute(
            """WITH input AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                       source_id uuid, id uuid, primary_account_id uuid,
                       content_group_id uuid, published_at timestamptz,
                       discovered_at timestamptz,
                       first_observation_age_seconds integer,
                       publication_type text, is_repost boolean,
                       history_completeness text,
                       synthetic_baseline_allowed boolean, quality_flags jsonb
                   )
               )
               INSERT INTO ingest.publication AS current(
                   id, primary_account_id, content_group_id, published_at,
                   discovered_at, first_observation_age_seconds, publication_type,
                   is_repost, history_completeness, synthetic_baseline_allowed,
                   quality_flags
               ) SELECT id, primary_account_id, content_group_id, published_at,
                        discovered_at, first_observation_age_seconds,
                        publication_type, is_repost,
                        history_completeness::ingest.history_completeness,
                        synthetic_baseline_allowed, quality_flags
                   FROM input
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
                           THEN current.synthetic_baseline_allowed
                       WHEN excluded.history_completeness='forced_incomplete'
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
                               THEN current.synthetic_baseline_allowed
                           WHEN excluded.history_completeness='forced_incomplete'
                               THEN false
                           ELSE current.synthetic_baseline_allowed
                               OR excluded.synthetic_baseline_allowed
                       END,
                       current.quality_flags || excluded.quality_flags,
                       NULL::timestamptz
                   )
               RETURNING id""",
            (_json(publication_input),),
        ).fetchall()
        publication_changed_ids = {
            _row_value(row, "id", 0) for row in changed_rows
        }

        identities_by_external_id: dict[str, dict[str, Any]] = {}
        for item in publications:
            publication_id = resolved_ids[item.id]
            for identity in item.identities:
                candidate = {
                    "publication_id": publication_id,
                    "platform_account_id": batch.account.id,
                    "external_id": identity.external_id,
                    "source_external_id": identity.source_external_id,
                    "role": identity.role.value,
                    "public_url": identity.public_url,
                }
                previous = identities_by_external_id.setdefault(
                    identity.external_id, candidate,
                )
                if previous["publication_id"] != publication_id:
                    raise RuntimeError("publication identity conflict within batch")
        identity_input = list(identities_by_external_id.values())
        identity_changed_rows = connection.execute(
                """WITH input AS (
                       SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                           publication_id uuid, platform_account_id uuid,
                           external_id text, source_external_id text,
                           role text, public_url text
                       )
                   )
                   INSERT INTO ingest.publication_identity(
                       publication_id, platform_account_id, external_id,
                       source_external_id, role, public_url
                   ) SELECT publication_id, platform_account_id, external_id,
                            source_external_id,
                            role::ingest.publication_account_role, public_url
                       FROM input
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
                (_json(identity_input),),
            ).fetchall()
        identity_changed_ids = {
            _row_value(row, "publication_id", 0)
            for row in identity_changed_rows
        }
        identity_conflicts = connection.execute(
            """WITH input AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                       publication_id uuid, platform_account_id uuid,
                       external_id text
                   )
               )
               SELECT input.external_id, identity.publication_id
                 FROM input
                 LEFT JOIN ingest.publication_identity AS identity
                   ON identity.platform_account_id=input.platform_account_id
                  AND identity.external_id=input.external_id
                WHERE identity.publication_id IS DISTINCT FROM input.publication_id""",
            (_json(identity_input),),
        ).fetchall()
        if identity_conflicts:
            raise RuntimeError("publication identity conflict")

        snapshot_keys = list(dict.fromkeys(
            (
                resolved_ids[item.id],
                item.snapshot.published_month,
                item.snapshot.synthetic,
            )
            for item in publications
        ))
        snapshot_key_input = [
            {
                "publication_id": publication_id,
                "published_month": published_month,
                "synthetic": synthetic,
            }
            for publication_id, published_month, synthetic in snapshot_keys
        ]
        latest_rows = connection.execute(
            """WITH input AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                       publication_id uuid, published_month date, synthetic boolean
                   )
               )
               SELECT input.publication_id, input.published_month,
                      input.synthetic, latest.semantic_fingerprint,
                      latest.observed_at
                 FROM input
                 LEFT JOIN LATERAL (
                     SELECT snapshot.semantic_fingerprint, snapshot.observed_at
                       FROM ingest.publication_metric_snapshot_active AS snapshot
                      WHERE snapshot.publication_id=input.publication_id
                        AND snapshot.published_month=input.published_month
                        AND snapshot.synthetic=input.synthetic
                      ORDER BY snapshot.observed_at DESC, snapshot.id DESC
                      LIMIT 1
                 ) AS latest ON true""",
            (_json(snapshot_key_input),),
        ).fetchall()
        latest_by_id = {
            (
                _row_value(row, "publication_id", 0),
                _row_value(row, "published_month", 1),
                bool(_row_value(row, "synthetic", 2)),
            ): row for row in latest_rows
        }
        snapshots_to_insert = []
        snapshots_by_key: dict[tuple[Any, ...], CanonicalPublication] = {}
        virtual_latest = {
            group: (
                _row_value(row, "semantic_fingerprint", 3),
                _row_value(row, "observed_at", 4),
            )
            for group, row in latest_by_id.items()
        }
        for item_index, item in enumerate(publications):
            publication_id = resolved_ids[item.id]
            snapshot = item.snapshot
            snapshot_group = (
                publication_id, snapshot.published_month, snapshot.synthetic,
            )
            latest_fingerprint, latest_observed_at = virtual_latest.get(
                snapshot_group, (None, None),
            )
            unchanged = (
                latest_fingerprint is not None
                and bytes(latest_fingerprint) == snapshot.semantic_fingerprint
            )
            heartbeat_due = (
                latest_observed_at is None
                or snapshot.observed_at - utc(
                    latest_observed_at, "snapshot.observed_at",
                ) >= self.snapshot_heartbeat
            )
            if unchanged and not heartbeat_due:
                continue
            snapshot_input = {
                "published_month": snapshot.published_month,
                "publication_id": publication_id,
                "collection_run_id": batch.context.run_id,
                "observed_at": snapshot.observed_at,
                "collected_at": snapshot.collected_at,
                "age_seconds": snapshot.age_seconds,
                "sampling_bucket": snapshot.sampling_bucket,
                "views_count": snapshot.views_count,
                "reactions_count": snapshot.reactions_count,
                "comments_count": snapshot.comments_count,
                "shares_count": snapshot.shares_count,
                "quality": snapshot.quality.value,
                "interval_uncertain": snapshot.interval_uncertain,
                "synthetic": snapshot.synthetic,
                "source_fingerprint": snapshot.source_fingerprint,
                "semantic_fingerprint": snapshot.semantic_fingerprint.hex(),
                "views_quality": snapshot.metric_quality["views"].value,
                "reactions_quality": snapshot.metric_quality["reactions"].value,
                "comments_quality": snapshot.metric_quality["comments"].value,
                "shares_quality": snapshot.metric_quality["shares"].value,
                "metric_evidence_id": metric_evidence_ids[item_index],
            }
            snapshots_to_insert.append(snapshot_input)
            snapshots_by_key[
                (
                    publication_id, snapshot.published_month,
                    snapshot.synthetic, snapshot.sampling_bucket,
                    snapshot.source_fingerprint,
                )
            ] = item
            virtual_latest[snapshot_group] = (
                snapshot.semantic_fingerprint, snapshot.observed_at,
            )

        inserted_snapshots: dict[tuple[Any, ...], tuple[Any, int]] = {}
        if snapshots_to_insert:
            snapshot_rows = connection.execute(
                """WITH input AS (
                       SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                           published_month date, publication_id uuid,
                           collection_run_id uuid, observed_at timestamptz,
                           collected_at timestamptz, age_seconds integer,
                           sampling_bucket bigint, views_count bigint,
                           reactions_count bigint, comments_count bigint,
                           shares_count bigint, quality text,
                           interval_uncertain boolean, synthetic boolean,
                           source_fingerprint text, semantic_fingerprint text,
                           views_quality text, reactions_quality text,
                           comments_quality text, shares_quality text,
                           metric_evidence_id integer
                       )
                   )
                   INSERT INTO ingest.publication_metric_snapshot(
                   published_month, publication_id, collection_run_id, observed_at,
                   collected_at, age_seconds, sampling_bucket, views_count, reactions_count,
                   comments_count, shares_count, quality, interval_uncertain,
                   synthetic, metric_semantics_version, capability_version,
                   source_fingerprint, semantic_fingerprint, views_quality, reactions_quality, comments_quality, shares_quality, metric_evidence, metric_evidence_id
                   ) SELECT published_month, publication_id, collection_run_id,
                            observed_at, collected_at, age_seconds, sampling_bucket,
                            views_count, reactions_count, comments_count, shares_count,
                            quality::ingest.observation_quality, interval_uncertain,
                            synthetic, 1, 1, source_fingerprint,
                            decode(semantic_fingerprint, 'hex'),
                            views_quality::ingest.observation_quality,
                            reactions_quality::ingest.observation_quality,
                            comments_quality::ingest.observation_quality,
                            shares_quality::ingest.observation_quality, NULL,
                            metric_evidence_id
                       FROM input
                   RETURNING publication_id, published_month, synthetic,
                             sampling_bucket, source_fingerprint, id""",
                (_json(snapshots_to_insert),),
            ).fetchall()
            inserted_snapshots = {
                (
                    _row_value(row, "publication_id", 0),
                    _row_value(row, "published_month", 1),
                    bool(_row_value(row, "synthetic", 2)),
                    int(_row_value(row, "sampling_bucket", 3)),
                    str(_row_value(row, "source_fingerprint", 4)),
                ): (
                    _row_value(row, "published_month", 1),
                    int(_row_value(row, "id", 5)),
                )
                for row in snapshot_rows
            }

        reaction_input = [
            {
                "snapshot_published_month": month,
                "snapshot_id": snapshot_id,
                "reaction_key": reaction_key,
                "reaction_count": reaction_count,
            }
            for snapshot_key, (month, snapshot_id) in inserted_snapshots.items()
            for reaction_key, reaction_count in
                snapshots_by_key[snapshot_key].snapshot.reaction_breakdown.items()
        ]
        if reaction_input:
            connection.execute(
                """INSERT INTO ingest.reaction_breakdown(
                           snapshot_published_month, snapshot_id,
                           reaction_key, reaction_count
                       ) SELECT item.snapshot_published_month, item.snapshot_id,
                                item.reaction_key, item.reaction_count
                           FROM jsonb_to_recordset(%s::jsonb) AS item(
                               snapshot_published_month date, snapshot_id bigint,
                               reaction_key text, reaction_count bigint
                           )
                       ON CONFLICT DO NOTHING""",
                (_json(reaction_input),),
            )

        lineage_items = []
        lineage_keys: set[tuple[UUID, str]] = set()
        for item in publications:
            publication_id = resolved_ids[item.id]
            snapshot_key = (
                publication_id, item.snapshot.published_month,
                item.snapshot.synthetic, item.snapshot.sampling_bucket,
                item.snapshot.source_fingerprint,
            )
            lineage_key = (publication_id, item.snapshot.source_fingerprint)
            if (
                snapshot_key in inserted_snapshots
                or publication_id in publication_changed_ids
            ) and lineage_key not in lineage_keys:
                lineage_items.append((
                    "publication", publication_id,
                    item.snapshot.collected_at,
                    item.snapshot.source_fingerprint,
                    item.snapshot.sanitized_source,
                ))
                lineage_keys.add(lineage_key)
        self._persist_lineages(
            connection, batch.context.run_id, lineage_items,
        )
        if inserted_snapshots:
            from .legacy_csv import persist_native_csv_batch
            persist_native_csv_batch(connection, [
                (
                    snapshot_key[0],
                    month,
                    snapshot_id,
                    snapshots_by_key[snapshot_key].snapshot.sanitized_source,
                )
                for snapshot_key, (month, snapshot_id)
                in inserted_snapshots.items()
            ])

        discovered_ids: set[UUID] = set()
        results = []
        for item in publications:
            publication_id = resolved_ids[item.id]
            snapshot_key = (
                publication_id, item.snapshot.published_month,
                item.snapshot.synthetic, item.snapshot.sampling_bucket,
                item.snapshot.source_fingerprint,
            )
            discovered = (
                item.external_id not in existing_ids
                and publication_id not in discovered_ids
            )
            if discovered:
                discovered_ids.add(publication_id)
            snapshot_inserted = snapshot_key in inserted_snapshots
            results.append((
                publication_id,
                discovered,
                snapshot_inserted,
                publication_id in publication_changed_ids
                    or publication_id in identity_changed_ids
                    or snapshot_inserted,
            ))
        return tuple(results)

    def _persist_presence_probes(
        self,
        connection: Any,
        batch: CanonicalAccountBatch,
        probes: Sequence[CanonicalDeletionProbe],
    ) -> int:
        """Persist routine positive observations with a bounded SQL round trip count."""
        if not probes:
            return 0
        probe_by_id = {probe.publication_id: probe for probe in probes}
        if len(probe_by_id) != len(probes):
            raise ValueError("only one presence probe per publication is allowed")
        rows = connection.execute(
            """SELECT publication.id, publication.deleted_at,
                      state.status::text AS status,
                      state.last_probe_outcome::text AS last_probe_outcome,
                      state.last_checked_at, state.last_present_at,
                      state.first_missing_at, state.consecutive_missing,
                      state.reason_code, state.last_collection_run_id
                 FROM ingest.publication AS publication
                 LEFT JOIN ingest.publication_availability_state AS state
                   ON state.publication_id=publication.id
                WHERE publication.primary_account_id=%s
                  AND publication.id=ANY(%s::uuid[])
                FOR UPDATE OF publication""",
            (batch.account.id, list(probe_by_id)),
        ).fetchall()
        if len(rows) != len(probes):
            raise RuntimeError("deletion probe publication is not owned by account")

        states = []
        events = []
        reset_ids = []
        for row in rows:
            publication_id = _row_value(row, "id", 0)
            probe = probe_by_id[publication_id]
            prior_status = _row_value(row, "status", 2)
            prior_checked = _row_value(row, "last_checked_at", 4)
            prior_run = _row_value(row, "last_collection_run_id", 9)
            if prior_checked is not None:
                checked = utc(prior_checked, "availability.last_checked_at")
                if (
                    prior_run == batch.context.run_id
                    and checked == probe.observed_at
                ) or probe.observed_at <= checked:
                    continue
            old_status = (
                DeletionProbeOutcome(prior_status)
                if prior_status is not None else (
                    DeletionProbeOutcome.CONFIRMED_DELETED
                    if _row_value(row, "deleted_at", 1) is not None
                    else DeletionProbeOutcome.PRESENT
                )
            )
            previous_outcome = _row_value(row, "last_probe_outcome", 3)
            previous_reason = _row_value(row, "reason_code", 8)
            states.append({
                "publication_id": publication_id,
                "status": DeletionProbeOutcome.PRESENT.value,
                "last_probe_outcome": DeletionProbeOutcome.PRESENT.value,
                "last_checked_at": probe.observed_at,
                "last_present_at": probe.observed_at,
                "reason_code": probe.reason_code,
                "last_collection_run_id": batch.context.run_id,
            })
            if (
                prior_status is None
                or old_status != DeletionProbeOutcome.PRESENT
                or previous_outcome != DeletionProbeOutcome.PRESENT.value
                or previous_reason != probe.reason_code
            ):
                events.append({
                    "publication_id": publication_id,
                    "collection_run_id": batch.context.run_id,
                    "observed_at": probe.observed_at,
                    "old_status": old_status.value if prior_status is not None else None,
                    "new_status": DeletionProbeOutcome.PRESENT.value,
                    "probe_outcome": DeletionProbeOutcome.PRESENT.value,
                    "reason_code": probe.reason_code,
                    "consecutive_missing": 0,
                })
            if _row_value(row, "deleted_at", 1) is not None:
                reset_ids.append(publication_id)
        if not states:
            return 0

        connection.execute(
            """INSERT INTO ingest.publication_availability_state(
                   publication_id, status, last_probe_outcome, last_checked_at,
                   last_present_at, first_missing_at, consecutive_missing,
                   reason_code, last_collection_run_id
               ) SELECT item.publication_id,
                        item.status::ingest.deletion_probe_outcome,
                        item.last_probe_outcome::ingest.deletion_probe_outcome,
                        item.last_checked_at, item.last_present_at, NULL, 0,
                        item.reason_code, item.last_collection_run_id
                   FROM jsonb_to_recordset(%s::jsonb) AS item(
                       publication_id uuid, status text,
                       last_probe_outcome text, last_checked_at timestamptz,
                       last_present_at timestamptz, reason_code text,
                       last_collection_run_id uuid
                   )
               ON CONFLICT (publication_id) DO UPDATE SET
                   status=excluded.status,
                   last_probe_outcome=excluded.last_probe_outcome,
                   last_checked_at=excluded.last_checked_at,
                   last_present_at=excluded.last_present_at,
                   first_missing_at=NULL,
                   consecutive_missing=0,
                   reason_code=excluded.reason_code,
                   last_collection_run_id=excluded.last_collection_run_id,
                   updated_at=transaction_timestamp()""",
            (_json(states),),
        )
        inserted_count = 0
        if events:
            inserted_rows = connection.execute(
                """INSERT INTO ingest.publication_availability_event(
                       publication_id, collection_run_id, observed_at,
                       old_status, new_status, probe_outcome, reason_code,
                       consecutive_missing
                   ) SELECT item.publication_id, item.collection_run_id,
                            item.observed_at,
                            item.old_status::ingest.deletion_probe_outcome,
                            item.new_status::ingest.deletion_probe_outcome,
                            item.probe_outcome::ingest.deletion_probe_outcome,
                            item.reason_code, item.consecutive_missing
                       FROM jsonb_to_recordset(%s::jsonb) AS item(
                           publication_id uuid, collection_run_id uuid,
                           observed_at timestamptz, old_status text,
                           new_status text, probe_outcome text,
                           reason_code text, consecutive_missing integer
                       )
                   ON CONFLICT (publication_id, collection_run_id, observed_at)
                   DO NOTHING
                   RETURNING publication_id""",
                (_json(events),),
            ).fetchall()
            inserted_count = len(inserted_rows)
        if reset_ids:
            connection.execute(
                """UPDATE ingest.publication SET deleted_at=NULL
                    WHERE id=ANY(%s::uuid[]) AND deleted_at IS NOT NULL""",
                (reset_ids,),
            )
        return inserted_count

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
        prior = connection.execute(
            """SELECT status::text AS status,
                      last_probe_outcome::text AS last_probe_outcome,
                      last_checked_at, last_present_at, first_missing_at,
                      consecutive_missing, reason_code, last_collection_run_id
                 FROM ingest.publication_availability_state
                WHERE publication_id=%s
                FOR UPDATE""",
            (probe.publication_id,),
        ).fetchone()
        if prior is not None:
            last_checked_at = utc(
                _row_value(prior, "last_checked_at", 2),
                "availability.last_checked_at",
            )
            if (
                _row_value(prior, "last_collection_run_id", 7)
                    == batch.context.run_id
                and last_checked_at == probe.observed_at
            ):
                return False
            # A resumed older run, or a second run for the same observation
            # instant, must never regress current availability.
            if probe.observed_at <= last_checked_at:
                return False
            old_status = DeletionProbeOutcome(_row_value(prior, "status", 0))
            previous_probe_outcome = DeletionProbeOutcome(
                _row_value(prior, "last_probe_outcome", 1)
            )
            previous_count = int(_row_value(prior, "consecutive_missing", 5))
            last_present_at = _row_value(prior, "last_present_at", 3)
            first_missing_at = _row_value(prior, "first_missing_at", 4)
            previous_reason = str(_row_value(prior, "reason_code", 6))
        else:
            old_status = (
                DeletionProbeOutcome.CONFIRMED_DELETED
                if _row_value(publication, "deleted_at", 1) is not None
                else DeletionProbeOutcome.PRESENT
            )
            previous_probe_outcome = None
            previous_count = 1 if old_status == DeletionProbeOutcome.CONFIRMED_DELETED else 0
            last_present_at = None
            first_missing_at = _row_value(publication, "deleted_at", 1)
            previous_reason = None
        outcome = probe.outcome
        if outcome == DeletionProbeOutcome.PRESENT:
            consecutive_missing = 0
            status = DeletionProbeOutcome.PRESENT
            last_present_at = probe.observed_at
            first_missing_at = None
        elif outcome == DeletionProbeOutcome.MISSING:
            consecutive_missing = previous_count + 1
            if old_status == DeletionProbeOutcome.PRESENT:
                first_missing_at = probe.observed_at
            if consecutive_missing >= probe.confirmation_threshold:
                status = DeletionProbeOutcome.CONFIRMED_DELETED
            else:
                status = DeletionProbeOutcome.MISSING
        elif outcome == DeletionProbeOutcome.CONFIRMED_DELETED:
            consecutive_missing = max(previous_count, probe.confirmation_threshold)
            status = DeletionProbeOutcome.CONFIRMED_DELETED
            first_missing_at = first_missing_at or probe.observed_at
        else:
            # Transient/auth/rate/ambiguous and unsupported results neither
            # increment nor clear a pending authoritative-missing sequence.
            consecutive_missing = previous_count
            status = old_status
        if prior is None:
            connection.execute(
                """INSERT INTO ingest.publication_availability_state(
                       publication_id, status, last_probe_outcome, last_checked_at,
                       last_present_at, first_missing_at, consecutive_missing,
                       reason_code, last_collection_run_id
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    probe.publication_id,
                    status.value,
                    outcome.value,
                    probe.observed_at,
                    last_present_at,
                    first_missing_at,
                    consecutive_missing,
                    probe.reason_code,
                    batch.context.run_id,
                ),
            )
        else:
            connection.execute(
                """UPDATE ingest.publication_availability_state
                      SET status=%s, last_probe_outcome=%s, last_checked_at=%s,
                          last_present_at=%s, first_missing_at=%s,
                          consecutive_missing=%s, reason_code=%s,
                          last_collection_run_id=%s,
                          updated_at=transaction_timestamp()
                    WHERE publication_id=%s""",
                (
                    status.value,
                    outcome.value,
                    probe.observed_at,
                    last_present_at,
                    first_missing_at,
                    consecutive_missing,
                    probe.reason_code,
                    batch.context.run_id,
                    probe.publication_id,
                ),
            )
        meaningful_event = (
            prior is None
            or status != old_status
            or outcome != previous_probe_outcome
            or probe.reason_code != previous_reason
            or (
                outcome == DeletionProbeOutcome.MISSING
                and consecutive_missing != previous_count
            )
        )
        inserted = None
        if meaningful_event:
            inserted = connection.execute(
                """INSERT INTO ingest.publication_availability_event(
                       publication_id, collection_run_id, observed_at,
                       old_status, new_status, probe_outcome, reason_code,
                       consecutive_missing
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (publication_id, collection_run_id, observed_at)
                   DO NOTHING
                   RETURNING publication_id""",
                (
                    probe.publication_id,
                    batch.context.run_id,
                    probe.observed_at,
                    old_status.value if prior is not None else None,
                    status.value,
                    outcome.value,
                    probe.reason_code,
                    consecutive_missing,
                ),
            ).fetchone()
        if outcome == DeletionProbeOutcome.PRESENT:
            connection.execute(
                """UPDATE ingest.publication
                      SET deleted_at=NULL
                    WHERE id=%s AND deleted_at IS NOT NULL""",
                (probe.publication_id,),
            )
        elif status == DeletionProbeOutcome.CONFIRMED_DELETED:
            connection.execute(
                """UPDATE ingest.publication
                      SET deleted_at=%s
                    WHERE id=%s AND deleted_at IS NULL""",
                (probe.observed_at, probe.publication_id),
            )
        return inserted is not None

    def _persist_lineage(
        self,
        connection: Any,
        run_id: UUID,
        owner_type: str,
        owner_id: UUID,
        collected_at: datetime,
        fingerprint: str,
        evidence: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> None:
        self._persist_lineages(connection, run_id, [
            (owner_type, owner_id, collected_at, fingerprint, evidence),
        ], force=force)

    def _persist_lineages(
        self,
        connection: Any,
        run_id: UUID,
        items: Sequence[tuple[str, UUID, datetime, str, Mapping[str, Any]]],
        *,
        force: bool = False,
    ) -> None:
        # Прод держит сохранение сырых свидетельств выключенным ради места:
        # ingest.raw_payload растёт на каждое наблюдение. Прежде флаг ставила
        # внешняя заплатка через legacy app.config; теперь его читает сам
        # коллектор. По умолчанию сохраняем — это поведение разработки.
        if not items or (not force and not _persist_raw_evidence()):
            return
        lock_names = sorted({
            "raw-evidence:" + fingerprint
            for _owner_type, _owner_id, _collected_at, fingerprint, _evidence
            in items
        })
        connection.execute(
            """SELECT pg_advisory_xact_lock(hashtextextended(lock_name, 0))
                 FROM unnest(%s::text[]) AS locks(lock_name)
                ORDER BY lock_name""",
            (lock_names,),
        )
        payloads = []
        for owner_type, owner_id, collected_at, fingerprint, evidence in items:
            collected = utc(collected_at, "lineage.collected_at")
            object_uri, object_hash = self.evidence_store.put(evidence)
            if object_hash != fingerprint:
                raise ValueError("canonical evidence fingerprint mismatch")
            payloads.append({
                "id": raw_payload_uuid(
                    run_id, owner_type, owner_id, fingerprint,
                ),
                "collection_run_id": run_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "collected_at": collected,
                "sha256": fingerprint,
                "external_ref": object_uri,
                "purge_after": collected + self.raw_retention,
            })
        connection.execute(
            """INSERT INTO ingest.raw_payload(
                   id, collection_run_id, owner_type, owner_id, collected_at,
                   sha256, content_encoding, external_ref, purge_after
               ) SELECT item.id, item.collection_run_id,
                        item.owner_type::ingest.raw_owner_type, item.owner_id,
                        item.collected_at, item.sha256, 'identity',
                        item.external_ref, item.purge_after
                   FROM jsonb_to_recordset(%s::jsonb) AS item(
                       id uuid, collection_run_id uuid, owner_type text,
                       owner_id uuid, collected_at timestamptz, sha256 text,
                       external_ref text, purge_after timestamptz
                   )
               ON CONFLICT (collection_run_id, owner_type, owner_id, sha256)
               DO NOTHING""",
            (_json(payloads),),
        )

    def quarantine_rejected_batch(self, raw: Any, context: CollectionContext, error_code: str) -> None:
        """Commit retrievable sanitized rejection evidence without canonical facts."""
        evidence = sanitize_evidence(raw)
        fingerprint = source_fingerprint(evidence)
        collected = utc(context.started_at, "quarantine.collected_at")
        with self._connection() as connection, connection.transaction():
            # Rejected input must remain inspectable even when routine raw
            # evidence retention is disabled.  Otherwise the quarantine row
            # references a payload that was deliberately skipped and the
            # whole account fails with a foreign-key violation.
            self._persist_lineage(
                connection,
                context.run_id,
                "account",
                raw.account.id,
                collected,
                fingerprint,
                evidence,
                force=True,
            )
            payload_id = raw_payload_uuid(
                context.run_id, "account", raw.account.id, fingerprint)
            connection.execute(
                """INSERT INTO ingest.evidence_quarantine(raw_payload_id,reason_code)
                   VALUES(%s,%s) ON CONFLICT DO NOTHING""",
                (payload_id, _error_code(error_code)),
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
        identity_receipt: str | None = None,
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
        if identity_receipt is not None:
            metadata["identity_source_receipt"] = identity_receipt
        metadata["identity_observation"] = batch.account_observation is not None
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
                   %s,'cache.invalidated','cache','public',%s,%s::jsonb
               )""",
            (
                revision_id,
                ["publications", "overview", "comparison"],
                _json(payload),
            ),
        )
        # Preserve the domain event separately from the cache invalidation.
        connection.execute(
            """INSERT INTO ops_and_admin.outbox_event(
                   dataset_revision_id,event_type,aggregate_type,aggregate_id,affected_tags,payload
               ) VALUES (%s,'source.account.updated','platform_account',%s,%s,%s::jsonb)""",
            (revision_id, str(batch.account.id), ["publications"], _json(payload)),
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
