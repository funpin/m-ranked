# Review remediation checkpoint: V15

This is an intermediate evidence index, not migration acceptance. **Production
NO-GO; Writer Gate W remains CLOSED; all existing legacy routes retain ownership.**
Repository-local admin CRUD, exact legacy CSV adapters, complete visual/mobile
acceptance and isolated HTTP upstream transition still require implementation or
verification. They are not production-only blockers.

The starting checkout was clean `alpha` at
`a7a2f09ff156eb72445f04f40dbe0e93d3378911`. Published V1–V8 bytes remain frozen.
V9–V15 are additive. The operational schema pins currently require the exact V15
file/CRC manifest; arbitrary extra migrations still fail the release gates.

## Verified local evidence

- `integration-review-20260905-r5/integration.json`: all self-provisioned commands
  exited zero; its own PostgreSQL/Redis containers and volumes were cleaned up.
  Actual Flyway clean installation and populated V8→V15 upgrade passed.
- Spring: 161 tests, zero failures/errors, three skipped installer entry points
  that are invoked separately by the runner. The additional query-plan test
  passed separately under `api_read`.
- Python suite: **417 passed, 29 skipped** without integration environment.
  The mandatory runner separately executes real PG bridge (3), preserved-source
  ledger (1), collectors (2), observation integrity (20), archive (1), operations
  metrics (1) and reverse/cutover rehearsal (10), with zero skipped cases.
- Async export: 150,001 rows / 44,700,417 bytes, one connection, repeatable-read
  revision 17 while revision 18 commits, every row verified and cancellation
  releases the connection. A separate `-Xmx64m` process exports 600,000 rows /
  70,800,119 bytes. Reports are in the r5 backend build output.
- `operations/performance/evidence/public-read-review-r1/report.json`: actual
  HTTP p95 21.90 ms cache hit and 46.66 ms bounded miss, respectively one and
  three measured JDBC executions. Counts remain constant for page sizes
  1/10/50/100/200. Same revision/body, cache path and ETag/304 were verified.
  Legacy HTML p95 was 19.28 ms; HTML and JSON rendering scopes differ, so this
  is not a claimed like-for-like speedup.
- `operations/performance/evidence/query-plans-review-r1/`: exact repository SQL
  `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` for overview, Telegram/VK/
  Rutube rating and VK comparison. No raw observation scan; `api_read` lacks
  SELECT on publication/account snapshots and reaction breakdown.
- `operations/disaster_recovery/evidence/dr-c35dcdc2d398.json`: real physical
  recovery with the exact V1–V15 manifest on the representative clone. Full
  restore RTO 9.7962 s; PITR RTO 9.7681 s and controlled RPO 0.164436 s; standby
  promotion RTO 3.6015 s with acknowledged-marker RPO zero; Parquet fallback
  0.5008 s. Physical checksum, manifest, WAL target and canonical checks pass.
- `reverse-review-20260905-r4.json` and r5 `reverse.json`: S0 SQLite Backup API,
  injected interruption after a committed checkpoint, resume, live source
  changes, catch-up, S-final second-writer refusal, all four controlled target
  collectors, target→legacy synchronization, actual legacy application restart,
  repeated forward cutover. Zero canonical/identity/alias/snapshot mismatch or
  duplicate. HTTP upstream transition is explicitly still unverified.
- Frontend has a 170-state lossless PNG/DOM/axe producer. The first full report
  passed 84/170; it is retained as failed evidence. Subsequent corrections and a
  fresh API/Next build are being checked. Latest frontend unit result: 56/56;
  lint, TypeScript, generated OpenAPI check and production build pass. Full
  browser/visual/mobile checks must be rerun after the final implementation.

## Integrity model

An exact observation retry is a no-op. A changed payload creates a new immutable
correction with sequence, predecessor and reason. PostgreSQL triggers protect
facts and history even from direct ingestion SQL. Metric quality is independent
per counter; unusable views do not erase usable reactions. Reverse format v2
preserves metric quality/evidence and reaction keys and still parses the old v1
format. The round trip verifies actual values and identities.

Reconciliation externally sorts independently decoded source facts and actual
canonical target facts, preserving NULL/zero, UTC instants, negative transitions,
reaction keys and per-publication/account ordered series. Source-row hashes only
support provenance; they are not used as substitutes for target data.

Hard-deleted source rows fail by default. `preserve-disappeared` requires a
previously imported immutable SQLite artifact, exact prior row hashes, named
operator/ticket/reason and migration-owner privileges. It derives an append-only
canonical fact ledger from that source, then independently reconciles the entire
target before committing. Runtime bridge privileges cannot self-approve. Later
target corruption or corruption of the ledger's digest fails reconciliation.
No canonical observation is deleted by this operation.

Archive export acquires the database fence, records a canonical manifest and
rechecks the digest before any detach/drop. A local spool never qualifies as an
off-primary immutable archive. Destructive production operations remain barred.

## Remaining work

Complete institution/account CRUD, native-ID and official M-Rating commands and
their full legacy UI; exact legacy snapshot/posts CSV projection and adapters;
full visual/a11y matrix and mobile lab gate; isolated actual HTTP read/writer
transition rehearsal; final health/emoji deployment verifier; final traceability
and route decisions. Repeat applicable schema/integration/DR checks after any
new migration. Keep all failed earlier reports and mark them superseded rather
than rewriting their results.

External acceptance includes live provider credentials/SQL truth review, deployed
Linux ownership and transition locks, physically separate encrypted backup and
standby storage, network/egress enforcement, production capacity/SLO evidence,
named operators and separate permission for production cutover. None is implied
by the local pass results above.
