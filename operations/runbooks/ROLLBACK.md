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

## Phase scheduler rollback

The phase scheduler has no schema migration. To roll back scheduler behaviour
without changing the release, set `COLLECTOR_SCHEDULE_MODE=legacy` in
`collector-common.env` and restart the four collector instances one by one.
Existing `collector.phase.v1` checkpoints are inert in legacy mode and may be
kept for investigation. Do not delete running `collection_run` rows: a newer
worker can resume them by their deterministic logical slot.

The process-local public response cache is deliberately empty after rollback.
Cold reads repopulate it from the authoritative revision endpoint. Keep the
version-independent `m-ranked-target-web-cache-gc.timer` active: it bounds the
writable active cache even when an older release still uses Next.js filesystem
fetch entries. Cache eviction never requires copying a newer entry into the
older release.

Do not use a retired cache as rollback state. The preserved
`/var/lib/m-ranked/web-cache-b66ad66-retired-20260921` directory is evidence,
not an application input, and requires separate explicit approval for any
mutation.

If the incident includes an incompatible schema change or database corruption,
do not start an older binary. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) and
restore PostgreSQL on an isolated host to the selected recovery point. Retain
the failed release, logs, outbox state and restore evidence for investigation.
