# Asynchronous modern CSV exports

`POST /api/v1/admin/exports` accepts `{"platform":"vk"}` (or `all`, `telegram`,
`max`, `rutube`) and returns `202`, a job object and its status `Location`.
Every route requires an authenticated EDITOR or ADMIN. POST and DELETE require
the existing admin CSRF token. A job belongs to its creating principal; another
principal receives `404`, including another administrator. Responses use
`Cache-Control: no-store` and bypass public caches.

| Route | Result |
|---|---|
| `GET /api/v1/admin/exports/{id}` | State, fixed revision, row/byte progress, expiry and a sanitized failure code |
| `GET /api/v1/admin/exports/{id}/download` | Completed UTF-8 modern CSV, filename and `X-Dataset-Revision`; otherwise `409` |
| `DELETE /api/v1/admin/exports/{id}` | Idempotent cancellation and artifact cleanup |

The request pins the published revision. The worker validates that revision and
reads all cursor batches in one REPEATABLE READ transaction. A queued revision
that has already been replaced fails with `REVISION_CHANGED`; retrying creates
a new job. Concurrent projection replacement after the worker snapshot does not
change the exported values or revision. The server cursor uses fetch size 500,
stable `(published_at, publication_id)` ordering, and `LIMIT maxRows + 1` so
overflow cannot silently truncate a successful file.

Hard limits per backend process are:

- Two generation workers, four retained artifacts, two retained jobs per owner
  and five creation requests per owner per minute.
- 2,000,000 rows, 512 MiB and five minutes per generation. A failed limit removes
  its incomplete artifact and exposes `MAX_ROWS`, `MAX_BYTES` or `MAX_DURATION`.
- Fifteen-minute TTL from creation. An expired artifact is removed; failed
  deletion retains its quota and is retried. Terminal job metadata is bounded
  to 64 entries and later removed.
- Four simultaneous download handles, 64 KiB copy buffers and five-minute
  download expiry. Disconnect, cancellation and expiry close the file handle;
  downloads hold no database connection.

Cancellation interrupts queued/running work and is checked on every row and
output buffer. A blocked database operation remains bounded by the five-minute
statement/transaction timeout. Quota is retained until that operation actually
releases its worker and partial file. No CSV is accumulated in JVM, Redis or
Next.js memory. Modern spreadsheet-formula neutralization is shared with the
bounded synchronous modern export; legacy CSV formatting remains separate.

Set `mranked.exports.spool-directory` (environment form
`MRANKED_EXPORTS_SPOOL_DIRECTORY`) to private local storage. The default is
`<java.io.tmpdir>/mranked-async-exports`. Its directory is `0700`, files are
`0600`, UUID paths are server-generated, completion is an atomic rename and an
exclusive OS file lock prevents two processes from sharing one spool. Capacity
checks account for outstanding maximum-byte reservations. The maximum artifact
quota is 2 GiB per process, plus negligible metadata.

Jobs are ephemeral and owned by the serving backend instance. After a process
restart, old job IDs return `404`; startup deletes only matching orphan export
files in its dedicated locked spool. Clients must create a new job. Multiple
instances require stable routing to the creating instance and separate spools.
This implementation does not promise durable job resumption across restarts.

Verification lives in `ExportJobServiceTest`, `ExportJobSecurityTest` and
`ExportJobPostgresIntegrationTest`. The latter requires explicit disposable
bootstrap authority through `MRANKED_EXPORT_TEST_ADMIN_URL`,
`MRANKED_EXPORT_TEST_ADMIN_USERNAME`, `MRANKED_EXPORT_TEST_ADMIN_PASSWORD`, and
the read-only role's `MRANKED_QUERY_TEST_PASSWORD`. It accepts only loopback
`*_it` endpoints, creates a UUID-named temporary database, applies the final schema
as `migration_owner`, and drops only that database. Never grant database creation
to a runtime or migration role for this test.

The real PostgreSQL producer exports 150,001 rows beyond the synchronous 32 MiB
limit while another transaction replaces the revision and values. It verifies
each ordered row, the fixed revision, one active connection and cancellation
release. A separate process exports 600,000 rows with `-Xmx64m`. Fresh
`export-postgres.json` and `export-heap.json` reports are written to the configured
Maven build directory; Surefire reports cover quotas, authentication/CSRF,
ownership, disconnect, expiry, partial-file cleanup and orphan recovery.
