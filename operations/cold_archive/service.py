from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .model import ArchiveResult, ArchiveVerification, MonthRange
from .parquet import DATASET_TYPE, SCHEMA_VERSION, ParquetArchiveWriter, verify_archive


EXPORT_SQL = """
SELECT
    snapshot.published_month,
    snapshot.id AS snapshot_id,
    snapshot.publication_id,
    snapshot.collection_run_id,
    publication.primary_account_id,
    account.platform::text AS platform,
    publication.published_at,
    snapshot.observed_at,
    snapshot.collected_at,
    snapshot.age_seconds::bigint AS age_seconds,
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
    COALESCE(reactions.breakdown, '{}'::jsonb) AS reaction_breakdown_json
FROM ingest.publication_metric_snapshot AS snapshot
JOIN ingest.publication AS publication ON publication.id = snapshot.publication_id
JOIN catalog.platform_account AS account ON account.id = publication.primary_account_id
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(item.reaction_key, item.reaction_count ORDER BY item.reaction_key) AS breakdown
    FROM ingest.reaction_breakdown AS item
    WHERE item.snapshot_published_month = snapshot.published_month
      AND item.snapshot_id = snapshot.id
) AS reactions ON true
WHERE snapshot.published_month = %s
ORDER BY snapshot.published_month, snapshot.id
"""


class ColdArchiveService:
    """Exports and verifies one immutable publication snapshot partition."""

    def __init__(
        self,
        dsn: str,
        output_dir: Path,
        *,
        batch_size: int = 5_000,
        min_free_bytes: int = 256 * 1024 * 1024,
    ):
        if not dsn.strip():
            raise ValueError("dsn must not be blank")
        if batch_size < 1 or batch_size > 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes must not be negative")
        self._dsn = dsn
        self._output_dir = output_dir.resolve()
        self._batch_size = batch_size
        self._min_free_bytes = min_free_bytes

    def archive(
        self,
        month: MonthRange,
        *,
        drop_hot_partition: bool = False,
        drop_confirmation: str | None = None,
    ) -> ArchiveResult:
        if drop_hot_partition and drop_confirmation != "DROP_HOT_PARTITION":
            raise ValueError(
                "drop requires the exact confirmation DROP_HOT_PARTITION"
            )
        self._prepare_output_directory()
        lock_key = f"cold-archive:{DATASET_TYPE}:{month.key}"
        # Autocommit keeps the session advisory lock independent while each
        # export/manifest/drop phase opens its own explicit transaction.
        with psycopg.connect(
            self._dsn, row_factory=dict_row, autocommit=True
        ) as connection:
            with self._advisory_lock(connection, lock_key):
                reused = self._reuse_verified(connection, month)
                if reused is not None:
                    if drop_hot_partition:
                        self._drop(connection, month, reused.manifest_id)
                        return replace(reused, hot_partition_dropped=True)
                    return reused

                self._assert_partition_and_capacity(connection, month)
                temporary_path, expected_count = self._export(connection, month)
                try:
                    verification = verify_archive(
                        temporary_path,
                        expected_row_count=expected_count,
                    )
                    final_path = self._publish_object(temporary_path, month, verification)
                finally:
                    temporary_path.unlink(missing_ok=True)

                manifest_path = self._publish_sidecar(month, final_path, verification)
                manifest_id = self._record_verified_manifest(
                    connection,
                    month,
                    final_path,
                    manifest_path,
                    verification,
                )
                result = ArchiveResult(
                    manifest_id=str(manifest_id),
                    month=month,
                    object_path=final_path,
                    manifest_path=manifest_path,
                    verification=verification,
                    reused=False,
                )
                if drop_hot_partition:
                    self._drop(connection, month, str(manifest_id))
                    result = replace(result, hot_partition_dropped=True)
                return result

    def _prepare_output_directory(self) -> None:
        self._output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._output_dir.is_symlink() or not self._output_dir.is_dir():
            raise ValueError("archive output must be a real directory")
        self._output_dir.chmod(0o700)

    @contextmanager
    def _advisory_lock(
        self, connection: psycopg.Connection[Any], lock_key: str
    ) -> Iterator[None]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (lock_key,))
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_key,)
                )

    def _reuse_verified(
        self, connection: psycopg.Connection[Any], month: MonthRange
    ) -> ArchiveResult | None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, object_uri, sha256, row_count, min_observed_at,
                       max_observed_at, verification_details
                FROM ops_and_admin.archive_manifest
                WHERE dataset_type = %s
                  AND schema_version = %s
                  AND partition_start = %s
                  AND partition_end = %s
                  AND status = 'verified'
                  AND verified_at IS NOT NULL
                ORDER BY verified_at DESC, id
                LIMIT 1
                """,
                (DATASET_TYPE, SCHEMA_VERSION, month.start_utc, month.end_utc),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        object_path = _file_uri_to_path(row["object_uri"])
        if object_path is None or not object_path.is_file():
            return None
        try:
            object_path.resolve().relative_to(self._output_dir)
        except ValueError:
            # A manifest produced for another spool/failure domain must not make
            # this local destination appear complete.
            return None
        verification = verify_archive(
            object_path,
            expected_row_count=row["row_count"],
            expected_sha256=row["sha256"],
        )
        sidecar_raw = row["verification_details"].get("manifestPath")
        manifest_path = Path(sidecar_raw) if sidecar_raw else object_path.with_suffix(".manifest.json")
        return ArchiveResult(
            manifest_id=str(row["id"]),
            month=month,
            object_path=object_path,
            manifest_path=manifest_path,
            verification=verification,
            reused=True,
        )

    def _assert_partition_and_capacity(
        self, connection: psycopg.Connection[Any], month: MonthRange
    ) -> None:
        partition_name = f"ingest.publication_metric_snapshot_{month.partition_suffix}"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass(%s) AS relation, "
                "COALESCE(pg_total_relation_size(to_regclass(%s)), 0) AS bytes",
                (partition_name, partition_name),
            )
            row = cursor.fetchone()
        if row["relation"] is None:
            raise ValueError(f"snapshot partition {partition_name} does not exist")
        required = max(int(row["bytes"]) * 2, 1) + self._min_free_bytes
        free = shutil.disk_usage(self._output_dir).free
        if free < required:
            raise RuntimeError(
                f"archive staging capacity gate failed: require {required} bytes, have {free}"
            )

    def _export(
        self, connection: psycopg.Connection[Any], month: MonthRange
    ) -> tuple[Path, int]:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{DATASET_TYPE}-{month.key}-",
            suffix=".parquet.staging",
            dir=self._output_dir,
        )
        os.close(descriptor)
        temporary_path = Path(raw_path)
        temporary_path.chmod(0o600)
        row_count = 0
        try:
            with connection.transaction():
                with connection.cursor() as control:
                    control.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                with connection.cursor(
                    name=f"archive_{month.partition_suffix}", row_factory=dict_row
                ) as cursor:
                    cursor.itersize = self._batch_size
                    cursor.execute(EXPORT_SQL, (month.start,))
                    with ParquetArchiveWriter(temporary_path) as writer:
                        while True:
                            rows = cursor.fetchmany(self._batch_size)
                            if not rows:
                                break
                            row_count += writer.append(rows)
                        writer.close()
            _fsync_file(temporary_path)
            return temporary_path, row_count
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _publish_object(
        self,
        temporary_path: Path,
        month: MonthRange,
        verification: ArchiveVerification,
    ) -> Path:
        final_path = self._output_dir / (
            f"{DATASET_TYPE}-{month.key}-{verification.sha256[:16]}.parquet"
        )
        if final_path.exists():
            verify_archive(
                final_path,
                expected_row_count=verification.row_count,
                expected_sha256=verification.sha256,
            )
            return final_path
        os.replace(temporary_path, final_path)
        final_path.chmod(0o600)
        _fsync_directory(self._output_dir)
        return final_path

    def _publish_sidecar(
        self,
        month: MonthRange,
        object_path: Path,
        verification: ArchiveVerification,
    ) -> Path:
        manifest_path = object_path.with_suffix(".manifest.json")
        payload = {
            "datasetType": DATASET_TYPE,
            "schemaVersion": SCHEMA_VERSION,
            "partitionStart": month.start_utc.isoformat(),
            "partitionEnd": month.end_utc.isoformat(),
            "objectUri": object_path.as_uri(),
            "format": "parquet",
            "compression": verification.compression,
            "sha256": verification.sha256,
            "rowCount": verification.row_count,
            "minObservedAt": _iso(verification.min_observed_at),
            "maxObservedAt": _iso(verification.max_observed_at),
            "sampleRowsRead": verification.sample_rows_read,
            "rowGroups": verification.row_groups,
            "verificationStatus": "verified",
        }
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.", suffix=".staging", dir=self._output_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(raw_path).chmod(0o600)
            os.replace(raw_path, manifest_path)
            _fsync_directory(self._output_dir)
        finally:
            Path(raw_path).unlink(missing_ok=True)
        return manifest_path

    def _record_verified_manifest(
        self,
        connection: psycopg.Connection[Any],
        month: MonthRange,
        object_path: Path,
        manifest_path: Path,
        verification: ArchiveVerification,
    ) -> UUID:
        details = {
            "manifestPath": str(manifest_path),
            "sampleRowsRead": verification.sample_rows_read,
            "rowGroups": verification.row_groups,
            "schemaFingerprint": f"mranked-publication-metric-snapshot-v{SCHEMA_VERSION}",
            "verifiedChecks": ["sha256", "rowCount", "schema", "compression", "sampleRead"],
        }
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ops_and_admin.archive_manifest (
                        dataset_type, schema_version, partition_start, partition_end,
                        object_uri, archive_format, compression, sha256, row_count,
                        min_observed_at, max_observed_at, status, verified_at,
                        verification_details
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'parquet', 'zstandard', %s, %s,
                        %s, %s, 'verified', transaction_timestamp(), %s::jsonb
                    )
                    ON CONFLICT (dataset_type, partition_start, partition_end, sha256)
                    DO UPDATE SET
                        object_uri = EXCLUDED.object_uri,
                        row_count = EXCLUDED.row_count,
                        min_observed_at = EXCLUDED.min_observed_at,
                        max_observed_at = EXCLUDED.max_observed_at,
                        status = 'verified',
                        verified_at = transaction_timestamp(),
                        verification_details = EXCLUDED.verification_details
                    RETURNING id
                    """,
                    (
                        DATASET_TYPE,
                        SCHEMA_VERSION,
                        month.start_utc,
                        month.end_utc,
                        object_path.as_uri(),
                        verification.sha256,
                        verification.row_count,
                        verification.min_observed_at,
                        verification.max_observed_at,
                        json.dumps(details, sort_keys=True),
                    ),
                )
                return cursor.fetchone()["id"]

    def _drop(
        self,
        connection: psycopg.Connection[Any],
        month: MonthRange,
        manifest_id: str,
    ) -> None:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ops_and_admin.drop_publication_metric_partition(%s, %s::uuid)",
                    (month.start, manifest_id),
                )


def _file_uri_to_path(raw: str) -> Path | None:
    prefix = "file://"
    if not raw.startswith(prefix):
        return None
    from urllib.parse import unquote, urlparse

    parsed = urlparse(raw)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(unquote(parsed.path))


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
