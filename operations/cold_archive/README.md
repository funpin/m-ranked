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
