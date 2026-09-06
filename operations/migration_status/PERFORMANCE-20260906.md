# Production backfill performance correction — 2026-09-06

At 20:08 UTC, the committed-checkpoint estimator reported 148.4 rows/s,
compared with roughly 200–230 earlier in the initial import. The host's only
vCPU was saturated; Docker's database port proxy used about 11% CPU.
The database occupied 3055 MB and the host had about 16 GiB free.

`BridgeService._import_snapshot_stream` invoked the partition helper for every
observation. The helper acquires a transaction lock and runs two GRANTs even
when the partition already exists. Production `pg_stat_sys_tables` showed
2,010,343 updates of `pg_class` before the new importer resumed.

The importer now invokes the helper once per publication month in each batch
transaction. The set is local to the transaction and recreated on every batch
and retry. Partition creation, grants and locks remain in the same transaction
as the affected observations and checkpoint. Data mapping and checkpoint
serialization are unchanged; compatibility version remains 1.3.1.

Verification on a new local V30 database:

- 16 bridge tests passed, including actual PostgreSQL import, independent
  projection and identity verification, repeat, catch-up and rollback.
- A new interruption test writes a third snapshot, raises an exception, proves
  only the preceding two-row batch and its checkpoint persisted, then resumes
  and verifies the complete import and an idempotent repeat.
- This is local verification, not final production acceptance.

The new sealed source is `alpha-v30-bridge-20260906-r4`, manifest SHA-256
`7c947e2536984734f2d8f207ecb06b8ac97af2660d5a753af1a1d240b4557f06`.
The previous sealed package remains available. The new package and direct
private-network PostgreSQL connection were tested under the migration Unix
UID before restart. The importer now uses the existing
`mranked-production_default` network and the `postgres` DNS alias, eliminating
the published-port proxy. Credentials remain in a private passfile.

At 20:15:44 UTC the importer was restarted under the fixed transition lock.
Confirmed checkpoints before and after stopping were both 1,025,240 rows for
batch `e832c733-8416-5f15-8649-b11405e49528`. The old collector remained active.
The source inventory is rechecked before resuming. The independent 3 GiB disk
reserve guard is now `m-ranked-backfill-progress-r4.service`; the transaction
reserve guard remains enabled. The restart receipt and previous/new units are
under `/var/lib/m-ranked-migration-status/` on production.

The importer resumed writing at about 20:20 UTC without resetting checkpoints.
Between 20:20:49.725539 and 20:22:09.767717 UTC, committed rows grew from
1,037,240 to 1,059,240: 22,000 rows in 80.04 seconds, approximately 275 rows/s
versus the preceding estimated 148.4 rows/s. This is a short measured interval,
not a guarantee of the rate for the remaining source streams.

The progress estimator initially included the restart/inventory downtime in
its rolling window, incorrectly lowering the displayed rate to 96.1 rows/s.
The standalone publisher was corrected to reset samples on paused phases,
stalls and status read failures. It waits for sixty seconds of fresh samples
at startup/resume instead of falling back to the whole batch's elapsed time.
This excludes planned downtime while still reflecting sustained slowdowns.
The page markup and other labels were not changed.

At 20:25:27 UTC the corrected public JSON reported 1,109,240 transferred,
231.5 rows/s and 13,244 seconds estimated for the remaining initial snapshot.
The phase was importing and legacy health confirmed collector freshness.
This fresh window shows about 56% improvement over 148.4 rows/s; the earlier
275 rows/s interval was faster. Remaining-time estimates still vary with the
actual data and workload. The host retained about 15 GiB free.

Full migration, catch-up, acceptance and retirement remain pending.
