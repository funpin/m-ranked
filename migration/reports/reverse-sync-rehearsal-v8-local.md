# Reverse-sync V8 local rehearsal

> Superseded as Gate W contract evidence by the strict-v3 rehearsal documented
> in `reverse-sync-rehearsal-v8-local-v3.md`. Both this v1 artifact and the
> intermediate v2 artifact are retained as historical engineering evidence
> only; current preflight rejects them.

This report records a disposable local integration rehearsal. It is engineering
evidence for the PG-to-legacy compatibility adapter; it is not production
approval and does not authorize a route switch, writer cutover, or data removal.

## Result

- Time: `2026-09-04T20:53:45Z`
- Database: fresh PostgreSQL `18.6` database with exactly successful Flyway
  `V1` through `V8`
- Test: `tests/test_reverse_sync_postgres.py`
- Result: `1 passed`
- Machine-readable historical v1 artifact:
  `migration/reports/reverse-sync-rehearsal-v8-local.json`
- SHA-256 sidecar:
  `migration/reports/reverse-sync-rehearsal-v8-local.json.sha256`

The rehearsal created and reconciled `S-final`, ingested one post-S-final
revision for each of Telegram, VK, MAX, and RUTUBE, projected the first two
revisions, replayed that projection, drained a fixed four-revision set, replayed
the drain, verified twice, and stopped twice. It then made a SQLite Backup API
copy, imported that copy through the forward bridge, repeated the import, and
compared the target state before and after the round trip.

The assertions proved:

- four exact platform collectors contributed post-S-final revisions;
- replay, drain, verify, stop, and the repeated forward import were idempotent;
- publication UUIDs, primary and secondary identities, identity roles,
  publication metric snapshot IDs, buckets, timestamps, quality, and legacy
  aliases were unchanged after the round trip;
- positive snapshot aliases remained visible to the forward bridge's
  `rowid > checkpoint` pagination;
- duplicate identities, duplicate primary identities, and duplicate snapshots
  were all zero;
- final forward reconciliation was `pass` with zero critical mismatches;
- the reverse-sync journal reached `stopped` after a fixed set of four target
  revisions.

The disposable database was dropped after the evidence file was written and
validated against the then-current v1 predicate. Current cutover preflight uses
the strict-v3 contract and rejects this artifact. The primary local `mranked`
database was not modified by this cleanup.

## Reproduction contract

Provision an empty disposable database with the frozen V1-V8 migration set,
provide separate migration-bridge, collector, and evidence-reader DSNs through
the `MRANKED_TEST_REVERSE_SYNC_*` environment variables, and set
`MRANKED_TEST_REVERSE_SYNC_REPORT_PATH` to the protected destination. The test
refuses a non-empty database and writes the JSON atomically with mode `0600`
only after every round-trip assertion passes.

For production-like acceptance use the current strict-v3 procedure in
`operations/interfaces/pg-to-legacy-sync.md`; do not repeat or relabel this
historical v1 procedure. Independent collector parity, restore, WAL/standby,
performance, visual, and operator-approval gates must also pass.
