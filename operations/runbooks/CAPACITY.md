# Storage capacity: evidence dictionary and index review

The production volume is 30 GB and cannot grow. This runbook covers the two
capacity measures delivered with contract
`storage-publisher-final-2026-09-08-r4`: interning `metric_evidence` into a
dictionary, and reviewing never-scanned indexes. It does not authorize dropping
an index, deleting an observation, reducing collection frequency, or stopping a
collector.

## What r4 changes

`ingest.publication_metric_snapshot` stores `metric_evidence` inline. Two thirds
of the rows carry an empty `{}`; the remaining third carry one of a couple of
dozen quality descriptors that cost about 620 bytes each. PostgreSQL never
compresses them: the tuple is roughly 470 bytes and compression only starts
above the ~2 KB TOAST threshold.

r4 adds `ingest.metric_evidence_dictionary` and a nullable
`metric_evidence_id`. A payload of 256 bytes or more is interned on INSERT by
the `zz_compact_metric_evidence` trigger and the inline column is left NULL;
anything smaller stays inline, because a four-byte key saves nothing against a
five-byte `{}`.

Readers never see the difference. `ingest.publication_metric_snapshot_resolved`
coalesces both shapes, `ingest.publication_metric_snapshot_active` and
`analytics.usable_publication_snapshot` are built on it, and
`ops_and_admin.publication_archive_record` — the record reverse-sync and the
archive compare against — is byte-identical either way.

The expand step performs no table rewrite and no historical UPDATE. It runs in
one transaction in seconds, because the transition adds both new constraints
`NOT VALID` rather than scanning seven million rows while holding ACCESS
EXCLUSIVE. A database created from the declarative contract has them validated
already; an existing one needs one explicit step after the release.

## 0. Validate the new constraints

Every existing row satisfies both — historical rows hold inline evidence and a
NULL key — so this is a scan, not a change. `VALIDATE CONSTRAINT` takes SHARE
UPDATE EXCLUSIVE and does not block collection, but it does block autovacuum on
the table, so run it outside the busiest hour and one partition tree at a time.

```bash
psql "$CAPACITY_DATABASE_URL" -v ON_ERROR_STOP=1 -c "SET lock_timeout='5s'" \
  -c "ALTER TABLE ingest.publication_metric_snapshot
        VALIDATE CONSTRAINT snapshot_evidence_representation" \
  -c "ALTER TABLE ingest.publication_metric_snapshot
        VALIDATE CONSTRAINT snapshot_evidence_dictionary_fk"
```

Confirm none are left:

```sql
SELECT conrelid::regclass, conname FROM pg_constraint
 WHERE connamespace = 'ingest'::regnamespace AND NOT convalidated;
```

## Preconditions

- The release carrying r4 is deployed and `ops_and_admin.schema_contract`
  reports `storage-publisher-final-2026-09-08-r4`.
- A verified backup exists, restored at least once (`restore-verify.sh`).
- The projection publisher is not mid-rebuild. Its transient peak and the
  backfill's WAL do not fit on this volume at the same time.

## 1. Capture the evidence

Read-only; safe at any time. Keep the output — the index review needs two
captures from the same server, at least five days apart.

```bash
CAPACITY_DATABASE_URL="postgresql://migration_owner@HOST/DB" \
  .venv/bin/python -m operations.capacity audit \
  > "capacity-$(date -u +%Y%m%dT%H%M%SZ).json"
```

The report carries relation and index sizes, the settings that decide planner
and WAL behaviour, per-column widths with `null_frac`, and the statistics reset
time that makes two captures comparable.

## 2. Backfill the historical rows

Convert one month at a time, oldest first. The newest partition holds most of
the volume and most of the write traffic, so it goes last.

```bash
CAPACITY_DATABASE_URL="postgresql://migration_owner@HOST/DB" \
  .venv/bin/python -m operations.capacity compact-evidence \
  --month 2021-08-01 --batch-size 1000 --batches 50 \
  --capacity-path /var/lib/postgresql --min-free-bytes 5368709120
```

Each batch runs in its own REPEATABLE READ transaction that takes the archive
record digest of the batch's rows before and after the update and rolls the
batch back if it moved by a single byte. `lock_timeout` is one second and
`statement_timeout` thirty, so a batch yields to collection rather than
blocking it. The runner holds a per-month advisory lock, stops when free space
falls below the reserve, and prints the committed cursor after every batch —
resume with `--after <last committed cursor>`.

The final line reports how many rows in that month still hold inline evidence.
Rows committed below the cursor while the pass was running are picked up by
restarting the month from zero.

**This reclaims space inside the table, not on the filesystem, and it costs
space before it saves any.** An UPDATE writes a compact new row version and
leaves the old, wider one for autovacuum to mark reusable. Converting a whole
partition in one sitting can therefore add up to a partition's worth of new row
versions before autovacuum catches up — on one core at 29% iowait it will not
keep up with an unpaced runner.

Pace the passes and watch the table, not just the volume:

```sql
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum,
       pg_size_pretty(pg_table_size(relid)) AS heap
  FROM pg_stat_user_tables
 WHERE schemaname = 'ingest' AND relname LIKE 'publication_metric_snapshot_%'
 ORDER BY n_dead_tup DESC LIMIT 5;
```

Run a few thousand rows, wait for `n_dead_tup` to fall back and `pg_table_size`
to stop climbing, then continue. The runner's `--min-free-bytes` reserve stops
the volume from filling, but only this check tells you whether the conversion is
actually converging. The newest partition, which holds most of the volume and
all of the write traffic, is the one to pace most carefully.

Returning the reclaimed bytes to the volume needs a separate partition rewrite,
which is a distinct operation with its own maintenance window.

## 3. Review the index candidates

```bash
.venv/bin/python -m operations.capacity index-candidates before.json after.json
```

The comparison refuses to run unless both captures come from the same database
and server, share one statistics reset, and span five days or more. It lists
only non-unique, non-primary, unattached btree indexes that were never scanned
in either capture, skips anything that backs a foreign key, and always excludes
`publication_latest_institution_platform_idx` and
`publication_latest_account_idx` — zero scans on a 17 MB table means the
planner prefers a sequential scan, not that the screen is dead.

It prints a review list and never emits a DROP. Five days of statistics do not
prove a rarely used reporting path is gone; confirm each candidate against the
workload before removing it, and remember that BRIN indexes are attached to
partitioned indexes, cannot be dropped individually, and weigh 3 MB in total.

## Rollback

- **Before the backfill.** `DROP TRIGGER zz_compact_metric_evidence ON
  ingest.publication_metric_snapshot;` returns new inserts to inline storage.
  The dictionary and the column stay and cost nothing.
- **After the backfill.** Nothing needs rolling back for readers: every view
  and the archive record resolve both shapes. Physically restoring inline
  storage would require replacing `ingest.reject_observation_mutation`, which
  only permits the forward direction, and would grow the table back. Restore
  from backup instead if that is ever required.

## What this does not cover

`source_fingerprint` is still a 64-character hex string, 65 bytes per row, and
also the fourth column of the 650 MB unique index. Storing the digest as
`bytea` would save about 0.47 GiB, but unlike the evidence dictionary it cannot
be done without rewriting the table and that index, which needs its own window
with the publisher stopped and roughly 6 GB of transient free space.

`analytics.dataset_revision` is an operational journal, not observations: 88 000
rows in five days and nothing prunes it. Pruning it means deciding what happens
to the projections that reference a revision by foreign key, and the publisher's
readiness rule reads the newest revision — treat it as its own change.
