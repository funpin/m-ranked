# Legacy CSV compatibility

`GET /api/v1/legacy-exports/{snapshots|posts}.csv` implements the original
`/export/snapshots.csv` and `/export/posts.csv` representations. The Next routes
are thin streaming facades. `/export.csv` remains absent, as in the original app.
Production routing remains on the legacy fallback until the release gates pass.

The adapter preserves the original Russian headers, row ordering, same-snapshot
counters, null cells, stored deltas, JSON spelling, Python float spelling, UTF-8
without BOM, CRLF, quoting and attachment names. Platform normalization, aliases,
unknown values and repeated parameters follow the original HTTP implementation.
This compatibility writer deliberately preserves legacy spreadsheet cell bytes;
the modern CSV writer has its separate formula-neutralization policy.

V17 stores only explicitly enumerated legacy presentation lexemes alongside the
authoritative typed facts. An unchanged accepted source artifact can backfill
pre-V17 imports through the normal bridge. Unsafe or unparseable raw JSON is never
copied as plaintext: a hash and classified blocking reason are retained. Requests
that would require these missing bytes return a complete problem response before
CSV headers. They do not silently sanitize and claim byte parity.

New collector publications receive stable legacy aliases and deterministic
`target-generated-v1` lexemes in the same transaction as their durable sanitized
evidence. Their raw representation includes the existing validated reverse-sync
envelope. Real collector-role writes, reverse synchronization, original FastAPI
exports and a second bridge import are checked together in the native round-trip
test. Generated representations are not attributed to an original legacy source.

Generation pins one repeatable-read transaction and one published revision, uses
a forward-only PostgreSQL cursor with fetch size 500, and writes to a private disk
artifact before streaming. Limits are 2,000,000 rows, 512 MiB, 300 seconds,
2 generators, 4 artifacts and 20 requests per minute per instance. Artifacts
expire after five minutes and are removed on success, disconnect, failure and
shutdown. Neither Spring, Next nor Redis holds the complete CSV in memory.

## Evidence and remaining gates

`LegacyCsvPostgresIntegrationTest` provisions and drops its own local database
using explicit disposable bootstrap authority, installs actual Flyway migrations,
and compares original FastAPI bytes through the real Spring MVC adapter. It covers
14 source cases, 10 native round-trip cases, duplicate parameters, empty data,
target tampering, concurrent revision replacement and API raw-table denial.
`LegacyCsvServiceTest` includes a separate 64 MiB JVM exporting 600,000 rows.
`frontend/tests/legacy-csv.test.ts` checks streaming pass-through and error bodies.

V22 retains eleven typed export fields per immutable observation, with correction
tips selected independently of raw partition availability. Its DROP wrapper
compares count and digest under the existing archive fence and stores coverage in
the same transaction as DROP. Normal CSV routes therefore retain full history
after partition removal. `LegacyCsvArchivePostgresIntegrationTest` proves 14 source
and 10 native HTTP byte cases after actual DROP and rebuild, including corrections.
For partitions removed before V22, a verified derived-fact importer restores CSV
coverage without restoring raw observations; see the archive runbook below.

These checks do not authorize a production route switch. Missing historical
coverage remains blocked with `COLD_ARCHIVE_RESTORE_REQUIRED` until the verified
import completes. Unsafe original JSON needs an explicit external compatibility decision;
the application never treats sanitization as byte equality. Representative source
artifacts, archive-history coverage and the remaining release-wide gates must be
approved before switching the legacy fallback.

Test environment: `MRANKED_EXPORT_TEST_ADMIN_URL`,
`MRANKED_EXPORT_TEST_ADMIN_USERNAME`, `MRANKED_EXPORT_TEST_ADMIN_PASSWORD`,
`MRANKED_QUERY_TEST_PASSWORD`, `MRANKED_LEGACY_CSV_COLLECTOR_PASSWORD` and
`MRANKED_LEGACY_CSV_BRIDGE_PASSWORD`. The control URL must be loopback and its
database name must end with `_it`; secrets are supplied only in process environment.

Archive integration tests additionally require `MRANKED_LEGACY_CSV_MAINTENANCE_PASSWORD`.

## Existing cold archives

Use the maintenance role and place the retained objects beneath a private archive
directory. Existing local manifest paths must resolve beneath that directory.
For remote manifest URIs, stage the immutable object as `<sha256>.parquet` there.
The application does not fetch arbitrary remote URLs. Supply the maintenance DSN
in `MRANKED_CSV_RESTORE_DSN`, then run:

```text
python -m operations.cold_archive.legacy_csv_restore --archive-root /private/archive-cache
```

`--manifest UUID` can select particular cold manifests; default processes all
retained cold manifests, at most 2,000 per invocation. Use `--batch-size` (default
64, maximum 1,000) and `--max-seconds` (default 900, maximum 3,600) to bound work.
Run during a maintenance window: publication of revisions is locked during the
transaction. SHA-256, v3 schema, row count, observed bounds and the full canonical
chain are verified before derived facts are accepted. PostgreSQL independently
checks the canonical chain and fact coverage, and a deferred constraint prevents
partial restore commits. On success a new revision is published with the same
observation anchor. Raw partition tables remain absent.

The test rejects corrupted objects, a forged complete canonical stream, partial
transaction commits and mismatched pre-DROP fact coverage. Failures leave the
public route blocked and roll back new facts. Restore output reports the revision
and `rawRowsRestored: 0`; verify the CSV endpoint and preserve that report before
resuming ordinary publication. A missing object or unsafe original JSON must be
resolved from its retained evidence, never by bypassing the gate.
