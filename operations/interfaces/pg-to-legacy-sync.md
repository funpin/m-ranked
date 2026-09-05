# PostgreSQL-to-legacy rollback projection

The repository ships the executable rollback adapter at
`operations/bin/pg-to-legacy-sync`. It projects target collector commits from
PostgreSQL into the frozen schema-v15 legacy SQLite database during the bounded
rollback window. Its presence does not by itself close Writer Gate W: the
release candidate still needs the production-like four-platform rehearsal and
the evidence consumed by `cutover-preflight.sh`.

The adapter is a compatibility writer, not a second source of truth. PostgreSQL
remains authoritative after writer cutover, and the adapter processes only
dataset revisions committed after its S-final baseline. It never deletes target
data or performs a route change.

## Required binding before start

`preflight` requires all of the following:

- the configured source namespace has a latest successful, non-dry-run
  `s_final` row in `migration.import_batch`;
- the PostgreSQL role can read every source relation used by the projection and
  can `SELECT, INSERT` `catalog.legacy_entity_alias`;
- legacy aliases are one-to-one per entity type and every target publication
  has exactly one `primary` identity;
- the legacy database is a regular, writable, non-symlink SQLite file at schema
  version 15, in WAL mode, with `quick_check=ok`, no foreign-key violations and
  enough free space;
- an existing journal is a private regular file with the exact state-v3 layout,
  valid UTC timestamps and coherent state; and
- an initialized journal remains bound to the same S-final namespace/batch/hash
  and the same legacy file identity.

`writer-cutover.sh` creates a new SQLite Backup API S-final, verifies its
SHA-256 and reconciliation report, and checks that reverse-sync preflight names
that exact batch ID and source SHA-256 before it calls `start`. A later S-final
for the namespace invalidates the binding and all active operations fail closed.

The legacy target identity covers its absolute path, device and inode, schema,
schema migrations, institution baseline and schema definition. Do not replace,
move, restore over or copy back the live SQLite file while its journal is
active. Use a separate online-backup file for post-stop forward reconciliation.

## Commands and state machine

The executable accepts these commands and emits one credential-free JSON object:

- `preflight` performs read-only PostgreSQL/SQLite/journal validation;
- `start --rollback-window-hours HOURS --operator ID --ticket ID` binds the
  S-final and legacy file, records the complete PostgreSQL revision baseline and
  enters `active`;
- `once` builds and applies one repeatable-read plan; it exits 75 if a newer
  revision became visible before the caught-up check;
- `run [--poll-seconds SECONDS]` repeats `once` while state is `active`; this is
  the systemd worker entry point;
- `status` reports visible/applied revision counts, lag, hashes, deadline and,
  after drain, whether the revision set is unchanged; it exits 75 on lag or a
  post-drain change;
- `drain --operator ID --ticket ID` takes the global and every known collector
  advisory lock, fixes the exact post-baseline revision set and canonical plan
  hash, applies it in one SQLite transaction, verifies revision stability and
  performs the WAL/fsync durability barrier;
- `verify` rebuilds that same fixed plan under collector locks and compares
  identities, publications, snapshots, NULL/zero semantics, deletion state,
  duplicates and SQLite integrity before entering `verified`; and
- `stop` is accepted only from `verified` (or idempotently from `stopped`),
  re-verifies the fixed plan, repeats the durability barrier and enters
  `stopped`.

The valid progression is
`uninitialized -> active -> drained -> verified -> stopped`. `start`, `once`,
`drain`, `verify` and `stop` are replay-safe only with the same persisted
bindings. A repeated `start` must have the same operator, ticket and rollback
window; a repeated `drain` must reproduce the exact revision set and plan hash.
Never delete or hand-edit the journal to force a transition.

## State v3 and durability

State v3 is a separate SQLite journal, normally
`/var/lib/m-ranked-reverse-sync/journal.sqlite3`, mode `0600`, WAL with
`synchronous=FULL`. It contains the singleton state, baseline/fixed/applied
revision sets, immutable alias reservations and hashed events. It also stores
the last applied plan hash/time and the legacy target identity.

Journal versions 1 and 2 are not upgraded in place. An old or structurally
different journal is rejected. Before a new rehearsal or a new cutover, retain
the old journal as evidence and provision a fresh path; never reuse an active
journal with another SQLite file.

An OS lock beside the legacy database prevents two adapter processes from
writing the same file. Every projection apply uses `BEGIN IMMEDIATE`, validates
foreign keys before commit, and recalculates Telegram derived deltas in
observation order. `drain` and `stop` require a complete WAL checkpoint and
fsync the database/sidecar and parent directory.

## Identity and round-trip contract

Legacy collection/public parsing, target collector adapters and both migration
directions use the shared canonical functions in `app/telegram_identity.py`:

- `m:<positive-message-id>` identifies one Telegram message;
- `g:<positive-grouped-id>` is the sole primary identity of an album; and
- album members remain `m:` identities with role `album_member`.

Bare or non-canonical Telegram integers are rejected. Every publication on any
platform must have exactly one primary identity. For VK, MAX and RUTUBE the
adapter embeds the complete identity-role set and quality flags in the reserved
`_mranked_reverse_publication` envelope while keeping the representable legacy
columns authoritative. The forward bridge rejects an envelope that disagrees
with those columns. This preserves joint/source/repost identities and VK joint
author metadata instead of manufacturing a new publication on re-import.

Publication aliases are positive legacy IDs in `posts` or `platform_posts` and
are reserved in PostgreSQL plus the journal. Post-S-final snapshots receive
separate positive, monotonically allocated legacy IDs in
`reaction_snapshots` or `platform_snapshots`; the immutable mapping is stored in
the v3 journal. The `_mranked_reverse_sync` snapshot envelope carries the
original target snapshot ID, publication UUID, published month, timestamps,
quality, synthetic/interval flags, semantics/capability versions and source
fingerprint. A forward SQLite-to-PostgreSQL catch-up therefore resolves the
same publication UUID and snapshot ID. Negative or reused snapshot aliases are
not part of state v3 and are rejected.

The writer distinguishes SQL `NULL` from numeric zero. It rejects target-only
states that schema v15 cannot encode, including unsupported quality or semantic
versions, non-Telegram synthetic/uncertain samples, Telegram shares, a missing
Telegram reaction total, invalid identity roles, conflicting sampling buckets,
and administrative account changes that cannot be safely projected.

## Fail-closed behavior

Any binding mismatch, missing baseline revision, non-ingestion delta revision,
missing source-run/account metadata, collector-lock conflict, alias collision,
duplicate key, malformed envelope, unsupported value, SQLite integrity error,
insufficient disk space, expired window or durability failure returns non-zero.
Errors expose only an exception class (`errorCode`), never driver text or a DSN.
Reports are replaced atomically at mode `0600`; report/database/journal paths and
their SQLite sidecars may not overlap or traverse symlinks.

On failure, do not set `COMPATIBILITY_SYNC_READY=true`, do not substitute a
no-op, and do not start either collector set manually. Follow `ROLLBACK.md`; if
drain or verification cannot finish, both writer sets remain stopped.

## Disposable integration proof and production-like Gate W evidence

Run the integration rehearsal against an otherwise empty disposable database
with exactly successful Flyway V1-V8, a schema-v15 SQLite S-final, separate
collector/migration credentials and all four platforms. It covers repeated
application of the same plan, fixed drain, verify, stop, a SQLite Backup API
export, and a forward bridge catch-up/replay proving stable publication,
identity, snapshot and alias state.

The reporter deliberately defaults to
`environment=disposable-postgresql-integration`. Host names and DSNs never
promote a run. The ordinary local entry point is:

```bash
rtk env \
  PGPASSFILE="/etc/m-ranked/credentials/rehearsal-pgpass" \
  MRANKED_TEST_REVERSE_SYNC_POSTGRES_DSN="postgresql://migration_bridge@HOST/DISPOSABLE_DB" \
  MRANKED_TEST_REVERSE_SYNC_BRIDGE_DSN="postgresql://migration_bridge@HOST/DISPOSABLE_DB" \
  MRANKED_TEST_REVERSE_SYNC_COLLECTOR_DSN="postgresql://collector_ingest@HOST/DISPOSABLE_DB" \
  MRANKED_TEST_REVERSE_SYNC_ADMIN_DSN="postgresql://TEST_OWNER@HOST/DISPOSABLE_DB" \
  MRANKED_TEST_REVERSE_SYNC_REPORT_PATH="/NEW/IMMUTABLE/PATH/reverse-sync.json" \
  .venv/bin/python -m pytest -q tests/test_reverse_sync_postgres.py
```

A production-like run is possible only from the installed immutable release
itself. Run its own `.venv/bin/python` with bytecode writes disabled and set
these explicit bindings:

```text
MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT=production-like
MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT=/opt/m-ranked/releases/<release-id>
MRANKED_TEST_REVERSE_SYNC_OPERATOR=<cutover OPERATOR_ID>
MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET=<dedicated Gate W approval>
MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE=<cutover MIGRATION_SOURCE_NAMESPACE>
```

For example, after copying `/etc/m-ranked/cutover.env` values into the approved
operator environment without printing credentials:

```bash
release_root=/opt/m-ranked/releases/RELEASE
cd -- "$release_root"
rtk env \
  PYTHONDONTWRITEBYTECODE=1 \
  PGPASSFILE=/etc/m-ranked/credentials/rehearsal-pgpass \
  MRANKED_TEST_REVERSE_SYNC_ENVIRONMENT=production-like \
  MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT="$release_root" \
  MRANKED_TEST_REVERSE_SYNC_OPERATOR="$OPERATOR_ID" \
  MRANKED_TEST_REVERSE_SYNC_APPROVAL_TICKET="$REVERSE_SYNC_APPROVAL_TICKET" \
  MRANKED_TEST_REVERSE_SYNC_SOURCE_NAMESPACE="$MIGRATION_SOURCE_NAMESPACE" \
  MRANKED_TEST_REVERSE_SYNC_REPORT_PATH="/var/lib/m-ranked/release-gates/reverse-sync-${release_root##*/}-${REVERSE_SYNC_APPROVAL_TICKET}-UTC.json" \
  "$release_root/.venv/bin/python" -m pytest -q -p no:cacheprovider \
  --basetemp "/var/lib/m-ranked/rehearsal-tmp/${release_root##*/}-${REVERSE_SYNC_APPROVAL_TICKET}-UTC" \
  tests/test_reverse_sync_postgres.py
```

The report path above is illustrative: replace `UTC` with a per-run timestamp,
keep it outside the release tree, and never reuse an existing JSON or sidecar.

Do not pass a `current` symlink as the release root. Use the installed,
manifest-verified release directory. The producer requires its
own resolved test file root to equal that canonical directory, requires
`sys.prefix` to equal `<release-root>/.venv`, and requires the critical
collector/bridge/reverse-sync modules to originate below it. It verifies that
`SHA256SUMS` covers exactly every regular release file (including the required
`SYMLINKS.sha256` inventory), verifies every listed hash, then derives both the
report release ID (directory basename) and
`SHA256(SHA256SUMS)` from those bytes. Neither value is accepted as an operator
label. Set `PYTHONDONTWRITEBYTECODE=1`, disable pytest's cache provider and use
a new external `--basetemp` before Python starts so test artifacts cannot
invalidate the exact release-tree check.

At deploy and cutover consumption time, `SYMLINKS.sha256` is independently
recomputed from every link path and its raw target. Internal pnpm/Next links
must use a relative first hop confined to and resolve below that same release
root; the only permitted external links are the three
`.venv/bin/python{,3,3.13}` launchers pinned to the canonical Python 3.13 paths
documented in the deploy runbook.

Production mode fails before database work if any binding is absent,
placeholder-valued or malformed. All four test DSNs must be password-free and
use pgpass. The namespace and operator/ticket are passed into the actual bridge
and reverse-sync start/drain operations; they are not report-only labels.

All DSNs are password-free and use pgpass. The test refuses a database that is
not otherwise empty or whose complete Flyway history is not the ordered V1-V8
version/script/Flyway-checksum manifest, optionally preceded by the one exact
Flyway 12 rank-0 schema-creation marker. This covers both a pre-created Flyway
schema (no marker) and Flyway-created schema (marker); every other baseline,
repeatable or non-versioned row is rejected. The eight migration file bytes are
verified separately. The caller-provisioned database is single-use; the test
does not create, clean or drop it.

After every assertion passes, the reporter creates a new mode-`0600` JSON file
and a new mode-`0600` sibling `.sha256`. Neither destination may already exist.
Use a new approval-scoped path for every run so a failed attempt cannot make an
older pass artifact look current. Consumer preflight also rejects either file
when it is group/world writable.

`cutover-preflight.sh --mode writer-cutover` accepts only report contract v3.
Every enforced object has an exact key set; missing or additional keys, wrong
JSON types, and unknown manifest entries fail closed. The complete shape is:

```json
{
  "reportType": "reverse-sync-rehearsal",
  "reportVersion": 3,
  "status": "pass",
  "environment": "production-like",
  "generatedAt": "2026-09-05T12:00:00+00:00",
  "release": {
    "id": "release-2026-09-05",
    "sha256SumsSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "operator": "named-operator",
  "changeTicket": "GATE-W-APPROVAL",
  "sourceNamespace": "m-ranked-production",
  "database": "mranked_rehearsal_20260905",
  "flyway": {
    "schemaVersion": 8,
    "migrationCount": 8,
    "fileSha256": {
      "V1__target_baseline.sql": "dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1",
      "V2__rebuild_core_projections.sql": "113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd",
      "V3__collector_observation_times_and_identity_grants.sql": "5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1",
      "V4__admin_collection_run_status_grants.sql": "d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82",
      "V5__legacy_activity_period_projection.sql": "d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41",
      "V6__comparison_valid_observation_hourly_projection.sql": "4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64",
      "V7__activity_rating_read_grants.sql": "95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb",
      "V8__legacy_overview_projection.sql": "dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c"
    },
    "databaseMigrations": [
      {"version": "1", "script": "V1__target_baseline.sql", "checksum": -1636077697, "success": true},
      {"version": "2", "script": "V2__rebuild_core_projections.sql", "checksum": 839607018, "success": true},
      {"version": "3", "script": "V3__collector_observation_times_and_identity_grants.sql", "checksum": -1456658399, "success": true},
      {"version": "4", "script": "V4__admin_collection_run_status_grants.sql", "checksum": 1318350062, "success": true},
      {"version": "5", "script": "V5__legacy_activity_period_projection.sql", "checksum": -1313754193, "success": true},
      {"version": "6", "script": "V6__comparison_valid_observation_hourly_projection.sql", "checksum": -290358219, "success": true},
      {"version": "7", "script": "V7__activity_rating_read_grants.sql", "checksum": -1228913579, "success": true},
      {"version": "8", "script": "V8__legacy_overview_projection.sql", "checksum": -574188650, "success": true}
    ]
  },
  "platforms": ["max", "rutube", "telegram", "vk"],
  "replay": {"runCount": 4, "idempotent": true},
  "duplicates": {
    "observationCount": 0,
    "identityCount": 0,
    "primaryIdentityCount": 0,
    "snapshotCount": 0
  },
  "preservation": {
    "publicationMismatches": 0,
    "identityMismatches": 0,
    "snapshotMismatches": 0,
    "aliasMismatches": 0
  },
  "forwardReconciliation": {
    "status": "pass",
    "criticalMismatches": 0
  },
  "reverseSync": {
    "status": "stopped",
    "journalStateVersion": 3,
    "baselineRevisionCount": 1,
    "baselineRevisionSetSha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "fixedRevisionCount": 4,
    "fixedRevisionSetSha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "planSha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "sFinal": {
    "batchId": "11111111-1111-4111-8111-111111111111",
    "sourceSha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "gate": "pass"
  }
}
```

Before applying the machine predicate, preflight resolves the configured
`MRANKED_CURRENT_LINK`, requires its absolute target to be one direct child of
the canonical `MRANKED_INSTALL_ROOT`, checks exact manifest coverage and every
hash twice, and requires `DEPLOY_REPORT.releasePath`, release ID and manifest
hash to equal that active tree. It rechecks the symlink/file identity around
validation. The predicate then binds `release.id` and
`release.sha256SumsSha256` to that independently verified active release,
`operator` to `OPERATOR_ID`,
`changeTicket` to the separate `REVERSE_SYNC_APPROVAL_TICKET`, and
`sourceNamespace` to `MIGRATION_SOURCE_NAMESPACE`. `database` must be a safe,
credential-free identifier matching `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`.
`generatedAt` must be parseable UTC RFC 3339 ending in `Z` or `+00:00`.

The platform set must be exactly MAX/Rutube/Telegram/VK, `runCount` is an
integer of at least two, both revision counts are positive, and the fixed count
is at least four. All four duplicate counts and all four preservation mismatch
counts are numeric zero. Revision-set, plan, S-final source and manifest hashes
are lowercase 64-hex; the S-final batch is a canonical UUID. The report mtime,
sidecar mtime and `generatedAt` age must each be in
`0..REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS`.

The checked-in
`migration/reports/reverse-sync-rehearsal-v8-local-v3.json` is disposable
regression evidence. Newly generated local reports use the v3 layout but retain
explicit non-production placeholders such as `release.id=local-unbound`; most
importantly, their environment is hardcoded by default to
`disposable-postgresql-integration`. Neither the local report nor its sidecar
can pass the production predicate by being renamed, copied or installed at the
production `REVERSE_SYNC_REHEARSAL_REPORT` path.

Deploy, cutover preflight, routing, writer cutover and rollback now share the
fixed root-owned mode-`0600` `/run/lock/m-ranked-transition.lock`. FD 8 is held
for the complete operation and inherited/revalidated by nested active-release
entrypoints; contention or forged inheritance fails closed. The adapter used
by writer cutover/rollback must be the canonical active release's
`operations/bin/pg-to-legacy-sync`, not an environment-selected external copy.

## Credential boundary and residual risk

Use `REVERSE_SYNC_DATABASE_URL` without a password and `MIGRATION_PGPASSFILE`;
the CLI rejects password-bearing DSNs in argv. The systemd unit loads the pgpass
file as a credential and runs as `telegram-monitor` with a narrow writable path.

The frozen V1-V8 release has no dedicated `reverse_sync` database role. The
deployed adapter therefore uses `migration_bridge`, which has broader catalog,
migration and ingest privileges than the adapter needs. Preflight proves the
required reads and alias insert ability but cannot prove absence of excess
grants. This is a recorded residual least-privilege risk, not a claim that the
role is minimal. Mitigate it with a host-local DSN, private pgpass permissions,
the hardened systemd unit, named operator/ticket evidence and a credential
limited to the rollback window. Creating a narrower role requires a separately
reviewed future migration; do not alter the frozen V1-V8 manifest during this
cutover.
