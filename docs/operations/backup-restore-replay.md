# Backup, restore and replay

Дата: 2026-09-16 · commit `b242378` · статус `draft; local dump observed, production restore not verified`

Measured production has three local dumps; latest completed 2026-09-15 02:46 UTC. WAL archive,
replica and a restore report were absent. File existence is not restore evidence.

Target: encrypted backup outside the primary failure domain, continuous WAL with ≤15 min
archive timeout, daily verification on an isolated host, RPO ≤15 min and RTO ≤2 h (proposals
already present in `operations/runbooks/BACKUP_RESTORE.md`, still requiring production drill).

## Drill acceptance

1. Restore to a new private path/host with no public listener.
2. Verify backup manifest/checksums, PostgreSQL 18.6, schema contract and `pg_amcheck`.
3. Record restored latest dataset revision and transfer applied cursor.
4. Start DataAdapter against a replay namespace from that safe cursor.
5. Require zero unexplained missing/duplicate events and equal canonical aggregate hashes.
6. Measure RPO from latest durable source event and RTO through API readiness; retain signed
   report. Destroy only the disposable restore after success.

Never prune raw events, WAL or the previous ReadyDB until the restore+replay ledger reconciles.

