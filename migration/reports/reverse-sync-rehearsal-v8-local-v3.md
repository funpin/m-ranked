# Reverse-sync V8 strict-v3 local rehearsal

This report records a disposable local PostgreSQL integration rehearsal of the
strict Writer Gate W v3 contract. It is engineering evidence only and does not
approve a production writer cutover, route switch or data deletion.

## Result

- Evidence time: `2026-09-04T22:21:53.529199+00:00` (`2026-09-05` in
  `Europe/Moscow`).
- Database: fresh PostgreSQL `18.6` database
  `mranked_reverse_gate_v3_it`, with the exact successful Flyway V1-V8
  version/script/checksum manifest and the allowed Flyway 12 rank-0 schema
  marker.
- Before the reverse rehearsal, the full backend suite ran against this database:
  `123 tests`, `0 failures`, `0 errors`, `0 skipped`. Its first clean-room run
  exposed and fixed an activity-rating grant test that assumed a pre-existing
  dataset revision; the successful rerun left the four reverse precondition
  tables empty.
- `tests/test_reverse_sync_postgres.py`: `10 passed`, including the real
  four-platform PostgreSQL round trip.
- Machine-readable evidence:
  `migration/reports/reverse-sync-rehearsal-v8-local-v3.json`.
- Sidecar:
  `migration/reports/reverse-sync-rehearsal-v8-local-v3.json.sha256`.
- Evidence SHA-256:
  `c342ced8922c62a4a42e864c9667ebcf5a8f6a607939a955f4f9bd85bd2a0f8d`.
- Both evidence files were created without overwrite with mode `0600`;
  `sha256sum --check` passed from the report directory.

The rehearsal reconciled S-final, exercised Telegram, VK, MAX and RUTUBE,
replayed the same reverse plan, drained a fixed four-revision set, verified and
stopped the state-v3 journal, exported through the SQLite Backup API, then ran
the forward bridge and its idempotent replay. Publication, identity, snapshot
and alias state survived the round trip. Every duplicate and preservation
mismatch counter is zero, and forward reconciliation has zero critical
mismatches.

## V3 provenance meaning

Contract v3 invalidates label-only v2 reports. In a production-like run, the
test must execute from a canonical immutable release root with its own `.venv`,
verified module origins, bytecode writes disabled and exact `SHA256SUMS`
coverage. Release ID and manifest SHA-256 are derived from that tree rather than
accepted as caller labels. Cutover preflight separately re-verifies the active
release symlink/tree and binds the deploy and rehearsal reports to it.

This local JSON deliberately uses
`environment=disposable-postgresql-integration`, `release.id=local-unbound` and
test-only operator/ticket values. The real production predicate rejects it;
copying or renaming the files cannot promote the evidence.

Production Writer Gate W remains closed until the exact installed release has a
fresh production-like v3 report plus independently accepted live four-provider
collector evidence, restore/WAL/standby, contract, performance, visual and
operator gates. Post-rehearsal hardening now implements the shared root-owned
transition lock documented by the runbook and passes local contention,
nested-call, stale-copy and hostile-environment tests. That does not promote
this report: the lock/ownership contract still needs a production-like Linux
host rehearsal, and previously installed guardless entrypoints must not be
invoked because they cannot join the lock retroactively.

## Cleanup

After the report and sidecar were validated, PostgreSQL reported zero sessions
for the disposable database. Only `mranked_reverse_gate_v3_it` was dropped. A
post-drop catalog query confirmed that the primary local `mranked` database
remained present.
