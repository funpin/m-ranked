# Reverse-sync V8 strict-v2 local rehearsal

> Superseded for Gate W contract testing by strict-v3 evidence, which derives
> provenance from a verified canonical release root. This v2 artifact is kept
> only as historical local evidence and cannot pass the v3 predicate.

This report records a disposable local PostgreSQL integration rehearsal of the
strict Writer Gate W v2 evidence contract. It is engineering evidence only. It
does not approve a production writer cutover, route switch or data deletion.

## Result

- Evidence time: `2026-09-04T21:52:13.171494+00:00` (`2026-09-05` in
  `Europe/Moscow`).
- Database: fresh PostgreSQL `18.6` database
  `mranked_reverse_gate_v2_it` with the exact Flyway V1-V8
  version/script/checksum manifest and the allowed Flyway 12 rank-0 schema
  marker.
- Test: `tests/test_reverse_sync_postgres.py`.
- Result: `7 passed`, including the real four-platform PostgreSQL round trip.
- Machine-readable evidence:
  `migration/reports/reverse-sync-rehearsal-v8-local-v2.json`.
- Sidecar:
  `migration/reports/reverse-sync-rehearsal-v8-local-v2.json.sha256`.
- Evidence SHA-256:
  `778d92d65f6ec98a37f560ab29e8484c2f4a5a1a9ea7d290804aa3af1c16dbb0`.
- Both evidence files were created without overwrite and have mode `0600`;
  `sha256sum --check` passed from the report directory.

The rehearsal reconciled S-final, exercised Telegram, VK, MAX and RUTUBE,
replayed the same reverse plan, drained a fixed four-revision set, verified and
stopped the state-v3 journal, exported through the SQLite Backup API, then ran
the forward bridge and its idempotent replay. Publication, identity, snapshot
and alias state survived the round trip. Every duplicate and preservation
mismatch counter is zero, and forward reconciliation has zero critical
mismatches.

## Gate meaning

The JSON uses `environment=disposable-postgresql-integration`,
`release.id=local-unbound` and test-only operator/ticket values. The production
v2 predicate hardcoded `environment=production-like` and compared caller-provided
release/operator/ticket/namespace labels with deploy values. Those comparisons
did not prove that the rehearsal code executed from the claimed release; this
label-only provenance gap is why v3 superseded v2. The checked-in local JSON
also fails the current v3 predicate regardless of where it is copied or renamed.

The current Gate W no longer accepts v2. It remains closed until the v3
procedure produces a fresh production-like report derived from the exact active
release and all independent collector, restore, WAL/standby, contract,
performance, visual and operator approval gates pass.

## Cleanup

After the report and sidecar were inspected, PostgreSQL reported zero sessions
for the disposable database. Only `mranked_reverse_gate_v2_it` was dropped. A
post-drop catalog query confirmed that the primary local `mranked` database
remained present.
