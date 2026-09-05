# Target schema verification

`V1__target_baseline.sql` is the authoritative first Flyway migration for the
PostgreSQL target. It expects the roles and the `flyway` schema created by
`infra/postgres/init/001-create-roles.sh`.

The local containers are pinned to PostgreSQL `18.6` and Redis `8.10.0`. Copy
`infra/postgres/compose.env.example` to a private environment file, replace all
secrets, and start only the dependencies:

```bash
rtk docker compose --env-file /private/path/m-ranked-compose.env \
  -f infra/compose.yaml up -d postgres redis
```

Apply Flyway as `migration_owner` through the backend build. The Flyway default
schema must be `flyway`; the application schemas are created by V1. Do not run
Flyway with any runtime role.

After committing source facts and a new `analytics.dataset_revision`, invoke
the idempotent core publisher (the V8 wrapper around the retained V6/V5/V2
chain) as
`migration_bridge` or `maintenance`:

```sql
SELECT analytics.rebuild_core_projections(:dataset_revision_id);
```

Continuous collector operation does this through
`operations/scripts/projection-publisher.sh`: ingestion commits only an
idempotent `projection.rebuild.requested` outbox event, the maintenance worker
coalesces a burst to the newest revision, rebuilds and verifies all six states
in one transaction, then records `dataset.revision.changed` and
`projection.published`. A stale-revision race or verification failure rolls the
transaction back and is retried; the Redis relay never exposes a rebuild
request as a published dataset.

It accepts only the newest revision, serializes publishers, and marks all six
projection states `ready` atomically: latest publication values, publication-
relative hourly points, daily/monthly/`3h|1d|7d|30d` institution aggregates,
complete/partial fixed-cohort comparison curves for 24/48/72/168/336 hours,
the V6 latest-valid-per-metric comparison input, and the V8 legacy overview
cards/accounts read model.
Complete cohorts require hour 0 and the horizon; partial cohorts require hour 1
and the horizon, and the selected membership remains fixed across the curve.
Hourly output is bounded by the configured publication hot window (never below
70 days), never uses a future observation, and never extrapolates a history
past its last real observation.
These rebuildable tables keep only one fully committed revision; PostgreSQL
MVCC lets readers retain the preceding revision until the replacement and its
six `ready` states commit together, avoiding revision-by-revision row growth.
V5 replaces only the V2 period calculation through a forward-only wrapper;
V6 preserves valid per-metric observations and same-snapshot engagement ratios,
and V8 materializes the complete legacy overview card. Every retained wrapper
is private to runtime roles. For each publication the period calculation
uses the first and last valid, non-synthetic observation in the open-left
window `(window_start, window_end]`, including publications released before the
window. A publication released inside the window may use zero only after its
platform-specific completeness gate: Telegram requires the imported explicit
`baseline_from_publication` decision or the equivalent explicit decision stored
by timely target public-web collection, while the other legacy collectors
encode their first-observation-age decision in
`history_completeness = 'complete'`. Target public-web collection persists one
age-zero synthetic snapshot plus the actual first snapshot only inside the
configured completeness threshold; V5 never uses the synthetic row as an
endpoint and instead consults that stored decision. Telegram MTProto never
creates this baseline. `forced_incomplete` is monotonic and clears/blocks the
decision even if a later input claims complete history or carries a synthetic
row.
Otherwise two real in-window observations are required. NULL endpoints remain
NULL, negative deltas are preserved, and medians use the legacy Python rule
`floor(median + 0.5)` with exact numeric arithmetic.

`platform IS NULL` period rows intentionally contain no metric value and keep
metric `sample_size = 0`; account count is not mislabeled as a publication
sample. `coverage` is the enabled-platform ratio, because views/reactions from
different platforms are not comparable without an approved normalized formula.
Active institutions without an enabled account remain present with zero
coverage.
V8 persists current and previous values, trend deltas, publication counts,
account metadata/status, enabled and connected-platform counts, and official
platform-specific rating fields. The `/api/v1/overview` read path performs its
global legacy sort and missing-last pagination directly over this model; HTTP
requests do not scan ingestion snapshots.

V3 adds explicit scheduler/collector receipt instants and only the catalog
identity-history writes needed by `collector_ingest`; it does not broaden that
role to administrative account fields.

V4 adds the minimum read privilege needed by the authenticated Spring admin
run-status endpoints: `api_write_admin` receives `USAGE` on `ingest` and
`SELECT` on `collection_run` plus `collection_account_result`. It receives no
access to observations, deletion evidence or raw payload, and `api_read`
remains unable to inspect run status. V4 also grants only `EXECUTE` on the
existing `SECURITY DEFINER` projection rebuild function. An account
configuration mutation therefore rebuilds and publishes the new ready dataset
revision in the same transaction before its outbox/audit records; a rebuild
failure or a race with a newer revision rolls the entire command back.

After Flyway has applied V1 through V8, run the structural, privilege, partition
and rollback-only data smoke checks as the local bootstrap user:

```bash
PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/smoke.sql
```

The smoke script deliberately rejects any PostgreSQL version other than 18.6.
It also proves that an explicit legacy snapshot ID can be inserted, MAX comments
remain nullable, `platform IS NULL` represents the precomputed all-platform
period projection, collectors cannot mutate append-only observations, the
collector has only narrow identity-versioning privileges, and the public read
role cannot access run status, raw payload, audit, or migration evidence. It
also proves that the administrative role can read only the two operational
run-status relations within `ingest`, and that no runtime role can bypass the
current wrapper by executing a retained implementation directly.

Run the rollback-only activity golden fixture separately against the same
schema:

```bash
PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/period-activity-golden.sql
```

It covers activity on an old publication, the open-left boundary, exclusion of
an old one-point history, allowed and denied publication-time baselines, NULL
metrics, an entirely empty platform remaining NULL, a negative delta, exact
half-up rounding of an even median, forced-incomplete history, exclusion of
synthetic/invalid endpoints, coverage-only all-platform rows, least-privilege
dispatch, and idempotent rebuild output. It also proves the V8 current/previous
overview values and trend deltas, exact account/rating/status mapping,
no-account cards, and exclusion of invalid, late-collected, and
future-completing account facts.

Run the independent rollback-only V6 comparison golden fixture as well:

```bash
PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/comparison-golden.sql
```

It proves latest-valid-per-metric carry-forward when a later same-hour snapshot
contains NULL, `collected_at` revision cutoffs, invalid exclusion, no future
observation at hour zero, same-snapshot engagement percentages, separate fixed
primary/engagement cohorts, complete versus partial membership, exact `.5`
medians, idempotence, least privilege, and the unchanged six-state contract.

## Partition contract

`ingest.publication_metric_snapshot` and its `reaction_breakdown` child use
matching monthly partitions. The snapshot table uses the composite primary key
`(published_month, id)` and unique idempotency key
`(published_month, publication_id, sampling_bucket)`. V1 creates recent monthly
partitions and a default partition so an old SQLite row never fails merely
because its source month was not pre-created. Import and collector code should
still call:

```sql
SELECT ops_and_admin.ensure_publication_metric_partition(:published_month);
```

before each month batch. Rows accidentally placed in the default partition must
be moved into the monthly partition before archival. A monthly hot partition can
only be dropped through `drop_publication_metric_partition`, after a verified
manifest and after the 70-day parity floor for the entire publication month.
The partition helper reapplies direct read grants for `migration_bridge` and
`maintenance`, which are needed by reconciliation/archive jobs that address a
child partition explicitly; it does not grant DDL to either role.
Expired raw payload is deleted in bounded, lock-safe batches only through
`purge_expired_raw_payload`; the maintenance role has no direct raw-payload read
or delete grant.

## Migration bridge contract

- `migration.import_batch` records source identity/hash/schema, tool version,
  run status and counts. Its replay key is `(source_name, source_sha256,
  snapshot_kind, tool_version, dry_run)`, so equal bytes from different source
  namespaces cannot collide.
- `migration.legacy_identity_map` permanently maps a source namespace/table/PK
  to exactly one UUID or bigint target.
- `migration.checkpoint` records resumable stream watermarks.
- `migration.legacy_evidence` preserves sanitized source fields and hashes that
  do not have a canonical target.
- `migration.reconciliation_result` is the machine-readable cutover gate.
- `migration.source_change_event` records monotonically ordered catch-up events.
- `catalog.legacy_entity_alias` preserves integer public URL identifiers after
  the temporary migration schema is retired.
- `ops_and_admin.operational_checkpoint` receives only allowlisted legacy
  `app_state`, `last_seen` and `last_checked` values; unknown keys belong in
  `migration.legacy_evidence`.

The default partition is a safety net, not an archival unit. Reconciliation must
report it as empty before cutover acceptance.
