# Application rollback

Rollback means activating the previous immutable Python/Next.js release against
the same compatible PostgreSQL contract. It does not recreate the retired
SQLite/Java stack and never copies data back to another database.

1. Stop `m-ranked-target.target`.
2. Point `/opt/m-ranked/current` atomically to the previous verified release.
3. Confirm that release accepts the current
   `ops_and_admin.schema_contract.contract_id`.
4. Start `m-ranked-target.target`.
5. Verify health, one bounded public read, admin authentication and collector
   leases before reopening external traffic.

If the incident includes an incompatible schema change or database corruption,
do not start an older binary. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) and
restore PostgreSQL on an isolated host to the selected recovery point. Retain
the failed release, logs, outbox state and restore evidence for investigation.
