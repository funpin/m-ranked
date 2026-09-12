# Rehearsed cutover

Migration lead owns the go/no-go decision. The application operator executes
systemd/Nginx steps, database operator owns backup/WAL/standby, data owner signs
reconciliation, and product owner accepts visual/functional parity. One person
must not self-approve every gate.

The default rollback window is 72 hours and cannot be shortened below 24 hours
without a separately recorded product/data decision. No new formula, metric
semantics, retention change or target-only feature enters this window.

## Gates

`cutover-preflight.sh` is read-only, runs in the approved root operator context
so it can take the mode-`0600` transition lock, and fails closed. Required evidence:

- legacy, target API and target Web are healthy;
- the checksummed shadow deploy report proves schema contract
  `storage-publisher-final-2026-09-08-r3` and records SHA-256 for the final schema
  plus the one-time production transition,
  `releaseId` and `releaseManifestSha256=SHA256(SHA256SUMS)`, and its
  `releasePath`/ID/hash equal the resolved `MRANKED_CURRENT_LINK` tree after two
  exact-coverage manifest checks. Each check also recomputes the canonical
  `SYMLINKS.sha256` path/raw-target inventory and rejects any unlisted,
  retargeted, broken or escaping link;
- contract, visual and performance JSON reports expose `status: "pass"`;
- newest reconciliation is at most 30 minutes old, `gate.status=pass` and has
  zero critical mismatches, including NULL/zero, identities and time ranges;
- S_final includes the mandatory `projection_verification` proof: all four
  platforms and UI periods, all five comparison horizons and both partial
  history modes, with the exact source SHA and published revision. A report
  carrying only `gate.status=pass` is rejected. Owner-preserved source rows
  require the verified prior artifacts (`--preserved-source`) described in
  [the independent oracle contract](../../migration/bridge/PROJECTION_RECONCILIATION.md);
- S_final also includes `identity_history_verification`, independently replayed
  from every original accepted account-stream SQLite artifact, including closed
  presentation/native-ID intervals. Supply each earlier artifact explicitly with
  repeatable `--historical-source`; a current snapshot cannot substitute for
  missing history. See [the history authority contract](../../migration/IDENTITY_HISTORY_RECONCILIATION.md).
  Missing non-migration command/collector authority fails closed and requires an
  accepted receipt protocol before a later post-cutover re-release can pass;
- every committed original receipt is readable by the actual reverse user and
  recovery reader, using the `2750`/`0440` writer-owned reader-group layout in
  [IDENTITY_RECEIPTS.md](IDENTITY_RECEIPTS.md). API, collectors, bridge and reverse
  must use the same explicit `MRANKED_IDENTITY_RECEIPT_DIR`; writers must not
  belong to `m-ranked-identity-readers`;
- exactly these seven serving projections are ready at one coherent published revision:
  `publication_latest`, `publication_hourly`, `institution_daily_metrics`,
  `institution_monthly_metrics`, `institution_period_metrics`, `comparison` and
  `publication_history`; raw revision may be newer and is reported as lag,
  while content/legacy-export watermarks are non-serving diagnostics;
- oldest pending outbox event is at most 60 seconds old;
- WAL archive and streaming-standby replay are at most 15 minutes behind;
- a successful isolated restore report is no older than 24 hours, met RTO and
  proves the exact final schema contract;
- database filesystem is below 70%;
- writer cutover additionally has the shipped PG-to-legacy adapter, a passing
  production-like reverse-sync rehearsal report in the strict v5 Gate W
  schema and its valid sibling `.sha256`. The JSON mtime, sidecar mtime and
  `generatedAt` age must each be within
  `0..REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS`; neither evidence file may be
  group/world writable;
- writer cutover has a fresh checksummed collector-parity report sealed and
  reverified from the active release. It binds the exact deploy/schema/symlink
  identity, dedicated external approval, protected raw captures and all four
  platforms' historical refresh, confirmed-deletion, transient-failure,
  projection and idempotent-resume invariants;

The generic release-gate report contract is `{ "status": "pass", ... }`.
Writer Gate W is deliberately stricter and does not use that generic parser.
The rehearsal report proves state-v3 behavior; after S-final, the adapter's
own `preflight` verifies the live journal and its exact S-final binding before
target writers can start.
Evidence paths and thresholds live in `/etc/m-ranked/cutover.env`; passwords do
not. Load it only after entering the approved privileged shell; this avoids
`sudo` environment filtering and never prints it. Resolve the active release
before the kernel opens the entrypoint, while the entrypoint rechecks the same
link after acquiring FD 8:

```bash
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  set -a
  source /etc/m-ranked/cutover.env
  set +a
  release_path="$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK")"
  exec "$release_path/operations/scripts/cutover-preflight.sh" --mode public-read
'
```

## Strangler phases

Unmatched URLs always go to FastAPI. Nginx never automatically masks a target
5xx with a legacy response; rollback is an explicit atomic route-file change.

1. `legacy`: all public traffic remains legacy; target is visible only on
   loopback port 18090.
2. `overview`: `/`, `/_next/**` and only `/api/v1/overview` move after overview
   parity; every other API remains legacy.
3. `public-read`: only public pages whose individual parity evidence has been
   accepted move. The current route file contains overview/rating/compare;
   entity detail pages, `/manage`, `/health`, `/emoji`, `/export` and
   `/platform-accounts` remain on legacy until their separate gates pass.
4. `writer-freeze`: public reads are unchanged, legacy `/manage` mutations are
   denied and legacy collection is stopped for S-final.
5. `rollback-freeze`: public GET/HEAD reads return to legacy, all public mutations
   are denied and the modern admin API is closed. Target API/collectors stop and
   reverse synchronization drains/verifies before the normal legacy route
   reopens administrative writes. This emergency phase uses the existing
   protected transition lock and route-file checks; it does not require passing
   a forward cutover preflight while recovering from an incident.

Each public route change is separately approved and reversible:

```bash
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  set -a; source /etc/m-ranked/cutover.env; set +a
  release_path="$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK")"
  exec "$release_path/operations/scripts/switch-routing.sh" \
    --phase overview --confirm ROUTE:overview:CHANGE
'
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  set -a; source /etc/m-ranked/cutover.env; set +a
  release_path="$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK")"
  exec "$release_path/operations/scripts/switch-routing.sh" \
    --phase public-read --confirm ROUTE:public-read:CHANGE
'
```

For forward phases the script reruns preflight, installs one route file atomically, executes
`nginx -t`, reloads Nginx, and restores the preceding route file on failure. It
does not change DNS or HAProxy. Every successful switch writes a mode-`0600`
operator/ticket report with old and new route SHA-256 under
`/var/lib/m-ranked/cutover`; `writer-freeze` always runs the stricter writer
preflight.

Both freeze phases also wait for the pre-reload Nginx worker PID/start-time
generation to exit under the same verified master. Existing keepalive or
in-flight requests cannot outlive a successful freeze admission. The default
30-second bounded barrier sends no kill signals; inability to verify/drain the
generation fails closed and retains the freeze file without advancing writers.
See [ROLLBACK.md](ROLLBACK.md) for timeout and recovery behavior.

## Writer cutover Gate W

The adapter described in `operations/interfaces/pg-to-legacy-sync.md` is now
implemented and packaged as `operations/bin/pg-to-legacy-sync`. Gate W is still
an evidence gate: it passes only when this exact release has both a valid
production-like reverse-sync rehearsal report and the four-provider
refresh/deletion report from `COLLECTOR_PARITY.md`. Do not substitute a no-op,
self-assert parity, reuse an old journal/report, or set
`COMPATIBILITY_SYNC_READY=true` without both approvals. The old unversioned
four-boolean collector JSON is explicitly rejected. The current report is
sealed and verified by the active release's
`operations/bin/collector-parity-evidence`; it has exact object shapes,
freshness/sidecar/raw-file checks and active release, deploy/schema contract, namespace,
operator and dedicated `COLLECTOR_PARITY_APPROVAL_TICKET` bindings.

The collector verifier validates integrity and declared invariants; it does not
contact providers or PostgreSQL and its unkeyed SHA-256 is not authentication.
An independent reviewer must validate the live-provider and SQL captures in the
external approval system. Trusted evidence storage, host clock and approval
workflow are part of the operational boundary; local validator tests are never
production acceptance evidence.

The reverse rehearsal report contract is documented in
`operations/interfaces/pg-to-legacy-sync.md`. Contract v4 has exact object
shapes and machine-enforces the production-like environment, active release ID,
SHA-256 of that release's `SHA256SUMS`, operator, dedicated
`REVERSE_SYNC_APPROVAL_TICKET`, source namespace, the exact final schema contract,
all duplicate/preservation zeros, both S-final source/revision-bound
independent proofs, the second batch's zero-write repeat, original-input fault
probes, real HTTP/admin/collector writer ownership, and state-v3 baseline/fixed
counts and hashes plus the canonical plan hash.
`REVERSE_SYNC_APPROVAL_TICKET` is never inferred from `CHANGE_TICKET`; local
policy may point both variables at one umbrella ticket only when that ticket
contains the independent Gate W approval.

The repository retains the current local V29 proof at
`operations/http_transition/evidence/local-v29-final-r1/reverse-http.json`, plus
historical V8/V27 and failed V28 evidence. The V29 artifact demonstrates the
complete second S-final and real HTTP/admin/collector round trip, but its
`environment=disposable-postgresql-integration` is not production approval and
cannot pass the hardcoded production-like predicate regardless of its path.
Do not install either that report or its sidecar as
`REVERSE_SYNC_REHEARSAL_REPORT` for a real cutover.

Set `MRANKED_INSTALL_ROOT` and `MRANKED_CURRENT_LINK` to the same canonical
release directory/link pair used by deploy. Generate each rehearsal at a new
approval- and release-scoped report path; the example intentionally leaves
`REVERSE_SYNC_REHEARSAL_REPORT` and `REVERSE_SYNC_APPROVAL_TICKET` blank. The
producer must run from the canonical installed release root with its own
`.venv`, verifies the complete manifest, and derives the release ID/hash rather
than accepting them as labels. Password-bearing production-like test DSNs and
`replace-with-*` operator/ticket values are rejected.

Deploy, preflight, route switching, writer cutover and rollback all take the
same exclusive `/run/lock/m-ranked-transition.lock` for their complete check
and mutation window. The root-owned mode-`0600` inode is opened on FD 8 and is
inherited and revalidated by nested active-release scripts, so writer cutover
can call preflight/route switching without deadlock. A competing or forged
descriptor fails closed with exit 75. Do not replace/delete the inode, close
FD 8, invoke a checkout/stale release copy, or add an unlocked emergency path;
the global FD 8 lock is always acquired before the Nginx FD 9 lock.
After rolling out this guard, prohibit every previously installed entrypoint
that predates it: an old copy cannot be retrofitted into the lock by the new
release and must never be used for a transition.

Every post-activation entrypoint verifies that its physical script, helper and
nested sibling belong to the canonical release selected by
`MRANKED_CURRENT_LINK`. Therefore invoke the absolute active-link path shown in
this runbook, never `operations/scripts/...` from a checkout.

Only after every required gate above has passed—including
strict collector evidence and a production-like v4 reverse report for the
active final-schema release—the rehearsed command is:

```bash
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  set -a; source /etc/m-ranked/cutover.env; set +a
  release_path="$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK")"
  exec "$release_path/operations/scripts/writer-cutover.sh" \
    --confirm WRITER-CUTOVER:CHANGE \
    --historical-source /var/lib/m-ranked/migration-snapshots/S0.sqlite3 \
    --historical-source /var/lib/m-ranked/migration-snapshots/catch-up.sqlite3
'
```

The named historical files are examples: enumerate every original accepted
artifact for the actual namespace. Files must be protected, root-owned regular
direct children of `MIGRATION_SNAPSHOT_DIR`, without SQLite sidecars. Path checks
run before writer freeze; the SHA must also match the recorded accepted import.
The script does not discover or approve unlisted files.

It freezes admin mutations, stops only the legacy collector, creates a verified
SQLite Backup API S-final, and performs the final idempotent
import/reconciliation. Reverse-sync preflight must echo that new S-final batch
ID and SHA-256. `start` then binds the state-v3 journal to that S-final, the
complete baseline revision set and the inode of the live legacy SQLite file
before the systemd worker or any target collector starts. The script starts the
four target collector units only after reverse sync is active; it does not start
or require Publisher.

The post-start gate requires raw dataset revision advancement, an in-window
successful run from every platform, a complete seven-projection serving
generation, the API readiness response `UP` at that published revision, zero
duplicate idempotency keys and reverse-sync lag zero. Both raw and published
watermarks are recorded in the cutover state JSON. Publisher may run later as
an explicit bounded maintenance action while collectors continue. The process preserves the legacy
web, SQLite file, v3 journal, reports and all PostgreSQL data.

If backup/import/reconciliation fails before reverse-sync start is attempted,
the script immediately restores the legacy route and starts the legacy
collector. From the instant a reverse-sync start has been attempted, recovery
is deliberately fail-closed and requires `ROLLBACK.md`; a command may have
partially started even when it returns non-zero.

During the 72-hour window alert/rollback on any correctness mismatch, public 5xx
above 1%, overview p95 above 1 second on bounded miss or 300 ms on hit, freshness
or WAL/replica lag above 15 minutes, any duplicate ingestion, cache visibility
leak, outbox lag above 60 seconds, disk at 85%, or independent collector failure
that violates last-known-data behavior.

Monitor `pg-to-legacy-sync status`; non-zero/exit 75, any positive
`lagRevisionCount`, `windowExpired=true`, a changed S-final/legacy binding, or
`unchangedSinceDrain=false` is a rollback condition. Do not rotate or replace
the bound SQLite file during the window: state v3 deliberately treats a changed
path/device/inode as a different target.

Final acceptance requires a second full reconciliation and successful backup
restore after the window. Taking legacy offline or deleting SQLite/bridge data
is a later, explicitly authorized change and is not performed here.
