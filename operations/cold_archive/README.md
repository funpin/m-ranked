# Verified cold archive

The maintenance-only job exports a single monthly
`ingest.publication_metric_snapshot` partition across Telegram, VK, MAX and
Rutube. It uses a named PostgreSQL cursor, a fixed non-secret schema and bounded
Arrow row groups. The resulting object is Parquet with Zstandard compression.
Schema version 2 preserves `published_at`, the platform's `observed_at`, the
collector receipt time `collected_at`, and the database `created_at` as separate
UTC instants.

The job refuses to proceed when the exact child partition is absent or the
local staging capacity is below twice the PostgreSQL relation size plus the
configured reserve. It then verifies SHA-256, row count, schema metadata,
compression and a sample read before atomically publishing the object and JSON
sidecar. Only then is a `verified` row committed to
`ops_and_admin.archive_manifest`.

Archive-only is the default and safe operating mode:

```bash
python -m operations.cold_archive \
  --dsn "$MAINTENANCE_DATABASE_URL" \
  --month 2026-01 \
  --output-dir /srv/m-ranked/archive-spool
```

Dropping hot data requires both `--drop-hot-partition` and the literal
`--confirm DROP_HOT_PARTITION`. PostgreSQL independently rejects a drop before
the retention floor or without a matching verified manifest. Never use the
drop option until the sidecar and Parquet object have reached the configured
off-primary failure domain and the operator has completed the cutover checklist.

The command emits only a sanitized JSON result. It never prints the DSN. A
second archive run re-verifies and reuses the existing immutable object.


## V9 consistency and v3 Parquet format

V9 replaces the export-to-DROP trust model. `begin_publication_archive(month)`
obtains an exclusive transaction advisory lock also used in shared mode by
snapshot and reaction INSERT triggers. It waits for in-flight writers and
persists `archiving`; every later writer receives SQLSTATE `55000`. A crash
leaves this fence closed. Use `abort_publication_archive(month)` only to reopen
an unfinished export deliberately. Successful export-only operations reopen it;
every reuse compares current count/min/max/canonical digest, so reopened ranges
cannot reuse stale spool objects. `archived` ranges remain permanently fenced.

The v3 Parquet file contains all corrections, their sequence/predecessor/reason,
per-metric quality and evidence, and a PostgreSQL canonical record for each row.
Verification reads all rows in bounded batches, cross-checks typed columns
against their canonical record, preserves reaction keys/NULL/zero/UTC, and
computes the same ordered SHA-256 chain as the database. It verifies exact
schema, Zstandard compression, SHA-256, row count, time bounds and sample reads.

A local `file://` object is explicitly a spool. It cannot authorize hot DROP.
Before any separately authorized production removal, an independent privileged
verifier must copy and read back the object in another failure domain, verify
provider object version and retention lock, and record the exact remote URI,
version, file/canonical hashes, count, failure domain, immutable-until timestamp
and verifier subject in `ops_and_admin.archive_object_attestation`. Maintenance
has SELECT only and cannot self-attest its local spool. Remote retrieval must
use the attestation's object URI/version. No production attestation is produced
by local tests; synthetic attestations exist only in disposable test databases.

`drop_publication_metric_partition()` itself requires the closed fence, exact
month boundaries and schema version 3, verified manifest, independent immutable
attestation and retention floor. In the same protected transaction it locks
relations/catalog dimensions, recalculates the complete canonical digest and
count/time bounds, rejects drift, drops the reaction child, detaches and drops
the snapshot child without CASCADE, and marks the fence `archived`.
Backup/PITR, standby and product archives remain separate mechanisms.

Production off-primary upload/readback/retention-lock acceptance remains an
external gate. The checked-in tests exercise a paused export vs concurrent
correction, later committed backfill vs stale manifest, explicit attestation
rejection, synthetic-attestation DROP only in disposable databases, empty
partitions and Parquet sample recovery.
