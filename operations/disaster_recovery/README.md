# Disposable physical recovery rehearsal

`rehearse.py` performs a real PostgreSQL 18 physical backup and recovery drill.
It accepts only an explicitly named local integration container and a `*_it`
database. Source access is read-only (`pg_dump` and consistency queries); the
source is never stopped. Every writable volume, recovery server and internal
Docker network receives a generated `mranked-dr-<run-id>` name and ownership
label. Cleanup addresses only resources created by that invocation.

Run after the mandatory integration producer has published a representative
fixture with the final Flyway migrations and ready projections:

```sh
rtk proxy .venv/bin/python -m operations.disaster_recovery.rehearse \
  --source-container mranked-review-it-postgres-1 \
  --source-database admin_review_visual_v7_it \
  --report-dir /private/tmp/mranked-dr-release-rehearsal
```

The source container must permit its explicitly provisioned bootstrap account
to run local `psql`/`pg_dump`. No source credentials are discovered or printed.
The rehearsal generates separate random role passwords in a temporary `0600`
file, creates an isolated clone, and deletes the file on completion. Recovery
configuration containing the replication password stays in the disposable
volume with mode `0600`. Passwords are absent from command arguments and reports.

The producer checks all of the following:

- Frozen source before/after dump and exact canonical partition SHA-256 chains,
  row counts, dataset revision and Flyway versions/checksums after each restore.
- `pg_basebackup` under the existing `backup` role, which has replication and
  monitoring privileges but no superuser, database creation or role creation.
- Physical manifest/WAL verification with `pg_verifybackup`.
- A read-only streaming standby, exact committed-marker catch-up, primary loss,
  promotion and canonical consistency.
- Full restore from the captured base backup; later committed markers must be
  absent from that restore.
- PITR using archived WAL and a named restore point between two committed
  markers; the earlier marker must be present and the later marker absent.
- Full/PITR readiness waits for writable promotion, not merely an available SQL
  connection during hot standby. Standby readiness separately requires recovery
  and read-only transactions. PITR reports retain the exact marker set and state.
- `pg_amcheck` and offline PostgreSQL page checksums on restored clusters.
- A bounded maintenance-role Parquet export, full schema/hash/canonical checks,
  and an archive read while the disposable primary is stopped. The archive
  artifact lives outside the primary volume. This does not attest remote object
  durability and does not permit dropping a hot partition.

JSON and Markdown reports include command descriptions/durations, dataset size,
exact Flyway manifest, checksums, controlled RPO/RTO measurements and remaining
external gates. The Parquet artifact remains beside the report for independent
sample queries. All generated Docker resources are removed, including on a
failed run. Reports are still written on failure; `status=fail` is not acceptance.

The final V1–V27 local run is recorded in
[`local-v27-final-r1/dr-fc5064bf7d2c.json`](evidence/local-v27-final-r1/dr-fc5064bf7d2c.json).
Its schema binding checks every versioned database history row against the
repository Flyway checksum and every SQL file SHA-256 against the frozen
operational pins; the extra unversioned Flyway schema-creation row is recorded
separately in
[`schema-binding.json`](evidence/local-v27-final-r1/schema-binding.json).
The run restored 9,026 snapshots and 824 accounts at revision 30 from an actual
3,952,473,791-byte source database. Local RTO was 5.5501 seconds for standby
promotion, 16.4231 seconds for full restore, and 16.5255 seconds for PITR.
Controlled standby RPO was zero; the PITR marker gap was 0.314674 seconds.
All 12 integrity checks and owned-resource cleanup passed. The earlier passing
[V26 run](evidence/local-v26-final-r2/dr-789ced5873f1.json) remains historical.
The earlier V26 failure
is retained in [`local-v26-r1-failed`](evidence/local-v26-r1-failed/): SQL became
available before recovery completed, so the verifier now checks the required
recovery state before asserting the exact PITR marker boundary. The named-target
boundary itself remains strict.

RTO is measured from simulated primary loss or physical restore start through
the corresponding readiness and integrity checks. Standby RPO is zero for the
explicitly acknowledged catch-up marker only. PITR RPO is the measured time gap
between included and intentionally excluded commits. These are measured local
rehearsal results, not a production capacity or outage claim.

Production acceptance remains separate: encrypted links and physically separate
DR host, capacity/concurrency testing, deployed pgBackRest repository encryption
and retention, immutable provider archive verification, production SLO evidence,
and named operator acceptance. Existing deployment templates and procedures are
in `operations/backup/` and `operations/runbooks/BACKUP_RESTORE.md` and
`DR_STANDBY.md`.
