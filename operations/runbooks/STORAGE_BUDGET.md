# Storage optimization handoff — 2026-09-24

## Status and authority

**Stage A1 executed after owner approval; application changes remain undeployed.**
At 03:50 UTC, the validated abandoned log follower on S1 was stopped and the old
migration dump inside the S2 database container was removed. Released object
allocations total **1,617,346,560 bytes across two hosts**. The verified nightly
backup remains. No database rows, partitions or nightly backups were deleted.

The owner's latest approval answers the package's first two actions (A1).
Release/image rollback assets (A2), backup-count reduction (B), application rollout
and restarts (C), first partition drop and product retention remain separate
approval boundaries. The original request authorizes local implementation and
push to `fixin`. Copying the existing dump for local restore was separately
approved. A passed test or this document is not production authorization.

Start here when continuing storage work. The private evidence/approval package is
outside Git. Host addresses, access paths and raw output belong there. Refresh
candidates before execution; historical PID, release names and image IDs are not
an allowlist. Use one multiplexed SSH connection; preserve key-only/fail2ban.

Baseline: `origin/main` 9ef39a6 and `origin/alpha` bf9ee05 have identical trees;
production uses analytics code through 3be4723, verified from ExecStart, real cwd,
mounts and SHA256. The implementation worktree starts from that production branch,
merges remote `fixin` history for fast-forward publication, and preserves the three
local storage/cache/access fixes. Duplicate legacy migration and old analyzer
resurrected by the merge were removed. The original local worktree is preserved.

## Executed stage A1 — 03:50 UTC

| Measurement (bytes) | S1 | S2 |
|---|---:|---:|
| Released object allocation | 138,108,928 | 1,479,237,632 |
| Filesystem available immediately before | 6,004,211,712 | 10,963,927,040 |
| Filesystem available immediately after | 6,142,324,736 | 12,443,164,672 |
| Observed available-space increase | 138,113,024 | 1,479,237,632 |
| Available share of filesystem | 19.43% | 23.64% |

The S1 extra 4,096 bytes in the filesystem delta are not attributed to the log.
Its two open file descriptors referenced one deleted inode, counted once; the
exact validated reader process exited after TERM. On S2, size/inode/mtime and
absence of open file descriptors were rechecked immediately before removing only
the old migration dump. The newer full dump that passed local restore remained
present. No PostgreSQL internal page reuse is included in these figures.

Before/after checks found healthy database containers and no database lock
waiters. Collectors, sender, receiver and serving processes remained running.
The latest-row freshness probe was about 4s on S1 and 14s on S2 after cleanup;
it is a limited probe, not a full ingestion SLA measurement. S1 outstanding
transport envelopes changed from 7 to 14 while ingestion continued; S2's 40 old
restored transfer rows were unchanged and are not its receiver backlog.
The pre-existing failed S1 storage-guard unit remains unresolved until rollout.
S1 is still below the 20% available-space target; A1 alone does not bound growth.

## Baseline and conditional budget (decimal GB)

Read-only baseline at 03:02 UTC, before A1; candidates rechecked 03:14–03:15.
The measured post-A1 values above supersede this baseline for current free space.
No full snapshot MIN/MAX, VACUUM FULL, DB rewrite or production restart.

| Item | S1 | S2 |
|---|---:|---:|
| Filesystem capacity | 31.619 | 52.626 |
| Used | 24.950 | 41.576 |
| Available (df, not capacity minus used) | 6.008 | 10.981 |
| Database | 16.495 | 16.885 |
| WAL allocated, approximately | 0.168 | 0.218 |
| Completed full dumps | 0 | 8.331 (3 files) |
| Root available after **proposed** artifact cleanup | 7.143 | 18.380 |
| After additionally keeping latest full dump only | 7.143 | 23.005 |
| New allowed dump peak (hard cap) | not assigned | 5.000 |
| Available after that peak | 7.143 | 18.005 |
| Extra pinned verified dump during delayed verification | not assigned | up to 3.706 currently |
| Available at conservative 3-copy transition peak | 7.143 | 14.299 |
| 20% operating reserve | 6.324 | 10.525 |

These are conditional arithmetic, not measured freed bytes. S1 cleanup includes
one unused release's exclusive inode blocks (0.997 GB) and one deleted-open file
(0.138 GB, counted once despite two FDs). S2 cleanup includes the old container
migration dump (1.479 GB) and candidate exclusive Docker layers (5.920 GB).
Docker reclaim is an estimate, excludes retained current/rollback/shared layers;
build cache references can reduce the result. No volume deletion is proposed.
Two old dump physical allocations total 4,624,936,960 bytes. Index staging reserves
another 0.25 GB, one concurrent build at a time. SQL purge reuses pages and does
**not** promise filesystem free space. No bloat savings enter the budget.

S2 history shows +0.428 GB/day over 6 hours and +1.467 GB/day over about 25 hours.
S1 only has short measurements (~0.26–0.31 GB/day): no valid daily baseline yet.
At those S2 rates, the 7.48 GB margin above 20% **after a 5 GB peak** lasts only
about 5–17 days if nothing else changes. Dump growth can shorten this. An
unbounded full history with positive inflow cannot fit indefinitely on fixed
30/50 GB disks. The prepared pressure gate prevents exhaustion by pausing work;
it does not turn an unbounded product into a sustainable service.

## Recovery choices

| Scheme | Additional storage / peak | CPU, I/O, network | Recovery and decision |
|---|---|---|---|
| One verified full S2 dump | current 3.706 GB; old+new 7.412 GB; cap new at 5 GB; with delayed verifier reserve one additional pinned copy | one daily read/compression, full decode; restore verification has its own destination budget | Preferred first stage. RPO up to successful dump interval (~24h plus failures); Local full restore was <=353s after transfer; host RTO is unmeasured. S2 host loss also loses its local dump. |
| Stream compressed dump to S1 | zero source staging; S1 needs old+new ~7.412 GB plus 6.324 GB reserve, before its DB grows | same source read/CPU, plus ~3.7 GB network per dump and receiver writes | Rejected **now**: S1 has only 6.008 GB free, or 7.143 after proposed artifacts. Its reserve plus peak requires ~13.736 GB free. |
| No full dumps; S1 replay + compact unique-state copy | full dump space saved, but unique-state size and independent copy have not been proved | lower backup I/O; expensive reconstruction/replay | Not accepted: loses S2 history outside S1 window and misses unique state. Requires explicit product/recovery concession and proved completeness. |

Existing auxiliary backup on S2 is a local tar under its local backup directory;
no external destination was found in checked pgBackRest/rclone/project config.
Absence from those locations is not proof that no operator-held copy exists.
No paid storage, cold archive or WAL archive has been enabled.

S1 is not a backup of S2. It can provide retained canonical observations and
some catalog/identity state, but not a proved complete copy of administrative
commands, sessions/audit, accepted methodology versions, rating inputs, analytical
review decisions, receiver receipts/cursors or old S2 history. Generated
projections/anomaly scores can be recomputed only when source observations and
the exact accepted method/norm version survive. Treat those versions as unique.

| Failure | Consequence with the proposed local full dump |
|---|---|
| Lose S1 | S2 has delivered facts; undelivered observations and S1 session/identity files may be lost. Restore S1 baseline/credentials separately. |
| Lose S2 host/disk | Local dump is lost with it. S1 only offers its retained subset; full recovery is not guaranteed. |
| Accidental S2 logical deletion | Restore retained verified dump to isolated target; reconcile/replay only within proved window. No PITR. |
| Bad ingest reaches both nodes | Two live DBs do not help; retain an independent pre-error dump. One rotating dump has a limited detection window. |

Replay must cover **snapshot start → next successful backup + outage + restore +
safety margin**, not merely time since backup completion. Current 26h ACK envelope
retention and 24h applied inbox payload remain unchanged: 26h is already marginal
for a daily backup plus ~10m dump and any material outage. Do not claim zero-loss
recovery for a longer outage. A safe expanded transport window also needs its
own bytes (current payload about 1.85 GB/26h); do not enlarge blindly.

## S1 working-set decision

Keep tracking at 720 hours. Do not equate tracking horizon with retained
observations or transport ACK age. Prefer **30 days by observed_at** as the next
model to validate; 21 days is not selected for deployment. In a 0.3% block sample,
August snapshots: 10,134 sampled / 8,142 within 21d / all within 30d; September:
25,618 / 24,051 / all. Weighted snapshot-byte reduction for 21d is roughly 1.07 GB
before reaction tables, index packing and required scheduler/correction state.
This is a page-correlated estimate, not exact savings or steady-state evidence.
Old publication months also contain fresh observations: the small oldest month
has 2,493 observations from September 7–23, not years of observation history.

| Layout | Retained horizon and resource implications |
|---|---|
| Current monthly published_month | 30d tracking can retain nearly 60d of publications and all their observations; today only ~0.610 GB is eligible by time, August ~3.844 GB no earlier than Oct 1. No exact rolling observed window. |
| Weekly published_at partitions | At most ~37d publications, still wrong observation axis. Requires FK/UNIQUE and routing migration. |
| Daily observed_at partitions + compact scheduler | Exact 21/30d observations + up to one day; requires separate per-publication last-24 observations with NULL/zero semantics, correction lineage, identity and scheduling state. Current published_month identity/FKs make this a real model migration. |

No full second copy of the 16.5 GB S1 DB fits. Migration must proceed one bounded
partition/range at a time, with measured WAL and index amplification on a restored
copy first. Illustrative 1-day chunk at 0.55 GB/day and 2x WAL plus 1x index/temp
can require ~2.2 GB extra; this is **not** a measured migration peak. At 7.14 GB
free after artifacts it leaves less than 20%, so first reclaim proved closed
months or reduce chunk size (e.g. 0.1 GB with measured peak below 0.8 GB).
No daily-partition rewrite is authorized or implemented in this change.

### Delivery proof before any partition drop

Global ACK recency does not prove historical dump coverage. Prepared pending
migration `0041_collector_retention_coverage.sql` introduces a persistent per-month
certificate and a `retiring` fence. Existing shared advisory writer locks drain
before fencing; both snapshots/reactions then refuse new writes. A streaming
comparison of source and target normalizes local IDs, preserves counters, NULL,
quality, fingerprints, evidence and correction parent keys, and includes reactions.
`compare-retention-month.py` emits a certificate only for matching hashes/counts;
operator installs it after review. Certificate generation never deletes data.

Drop requires matching fence generation, 720h minimum tracking cutoff, profile B,
and no pending transfer envelopes. Certificate survives transport ACK purge;
unfreeze/re-fence invalidates it. Drop uses 1s lock timeout. Keep this migration
pending and retention **off** until comparison has passed on historical months,
restore policy is accepted and the specific first drop is approved. An empty
month is not an exception. Cold archive and retirement share the existing fence;
never let two jobs own the same month.

## Data inventory and owner budgets

Sizes are current allocated relation/storage bytes rounded, not additive across
parent/child/shared file layers. Proposed ceilings are alerts/admission budgets,
**not authorization to drop unique data when a ceiling is reached**.

| Class / owner | S1 / S2 GB | Retention condition | Working cleanup / next decision | Budget |
|---|---:|---|---|---|
| Publication + reaction observations / data owner | ~12.84 / ~11.61 | S2 product history; S1 720h tracking currently monthly | S1 off; covered-month drop pending. S2 no effective history purge | S1 proposed 12 GB observation ceiling needs daily model validation; S2 total DB soft 20 GB |
| Account snapshots / collector | .096 / .076 | exact historical requirement not decided; policy row says 40d | no proved automatic pruning | .15 GB each alert, do not delete |
| Runs/results / collector | .247 / .215 | resumable run, FK lineage and audit dependencies | no blanket TTL safe | .30 GB each alert |
| Dataset revisions / analytics | .351 / .341 | referenced revision/API lineage must survive | FK-aware compaction not implemented | .50 GB each alert |
| S1 transfer envelopes / transport | 2.094 / .031 restored residue | ACK +26h on S1, pending indefinitely until delivered | sender bounded purge works; S2 stale pending separately investigate | S1 2.5 GB working budget; stop collection on pressure |
| S2 inbox payload / receiver | 0 / 1.993 incl receipts | applied +24h | receiver bounded payload nulling works | 2.5 GB alert |
| Inbox/event receipts / receiver | 0 / .028 event table + receipt heap/index within above | retry contract has no hard maximum | keep dedup receipts; no tombstone TTL authorized | .10 GB metadata alert; ongoing growth |
| Cache outbox / API | .490 / 1.093 | delivered/terminal +1d | new maintenance 1000-row batches, 20 batches/20s hourly; pending preserved | .15 GB live target; old allocation reused |
| Raw evidence + metadata / ingest | small / 1.315 files + .175 metadata | per-object purge_after, orphan grace ≥7d | new durable sweep cursor; requires external_ref index | .25 GB metadata +2 GB files alert; default raw persistence off |
| Identity receipts/files / identity owner | .350 + .193 collector state / unmeasured | dedup and provider session state | no deletion before identity/retry contract | .75 GB S1 alert; independent encrypted copy needed |
| Catalog, admin audit, commands, method/norm versions / product owner | catalog+rating ~.025 / ~.020; other unique tables separate | unique state, logically indefinite | retain; compact backup inventory remains to be proved | .25 GB alert, not hard cap |
| Checkpoints / collector+analytics | small | latest scheduling state and lineage refs | upsert by identity; stale identities need explicit ownership decision | .10 GB alert |
| Projections/availability/anomaly state / analytics | latest .095 / .196; availability .024 / .750; anomaly S2 .097 | derived but may encode review decisions | unchanged writes already suppressed in several paths; no VACUUM FULL | 1.5 GB combined S2 alert |
| Aggregates/rating / analytics | institutional .081 / .032 + other tables | source window/method version governs reproducibility | no approved historic aggregate cutoff | .25 GB alert |
| Quarantine / receiver | not separately measured | diagnose/resolve before expiration | no automated deletion proposed | .10 GB alert; operator review |
| Full dumps / DR owner | 0 / 8.331 | proposed KEEP=1 + pinned verified copy | bounded stream/rotation prepared; real restore required | 5 GB per new dump, peak with old/new and possible pinned copy |
| Releases/images / operator | ~2.18 +1.37 / .559 + images | current, next-start refs, one agreed rollback, protected forensic | one reviewed host GC; no blanket Docker pruning | release budget 1.2 GB S1 after cleanup, Docker explicitly inventoried |
| Logs / operator | .126 / .086 at audit | journald 7d/128MiB S1; 14d/256MiB S2 | existing rotation; Docker 10MiB×3 per active container | existing caps |
| Disk metrics / operator | tiny | host ≤600 samples (~49h), DB 31d | atomic bounded JSON/textfile; existing DB observation purge | <1 MB host history; <20 MB DB observations |
| Temporary dumps/worklists / operator | no partial at refresh | partial ≥24h under backup lock; worklist one sweep | helper partial expiry; evidence list ~22 MB at 312k files | 5 GB partial cap + .025 GB worklist; failed jobs still count in admission |
| CSV / none | 0 / 0 | retired | absent; no restoration | 0 |

Unresolved rows are intentionally visible. This is **not** a completed bounded
system until unique-state ownership/retention and the product-history decision
are resolved. Tombstones/watermarks cannot safely replace per-batch receipts
without a producer epoch, monotonic contiguous cursor contract, out-of-order
handling and proof that old epochs cannot return. UUID batches can retry late;
receipts remain.

## Prepared implementation and controls

- Delivered cache outbox purge with eligibility indexes, per-batch commit,
  SKIP LOCKED, lock 1s / statement 5s, total budget 20s (+ one in-flight query).
  Delivered and terminal candidates use separate indexed paths; historical
  pending rows are never relabeled. Index builds live in `operations/sql/storage-indexes.sql`
  outside migration transactions; check `indisvalid` after interruption.
- Evidence GC worklist/cursor progresses across non-expired objects and process
  restarts, uses bounded DB lookups and per-hash transaction locks, retains young
  orphans. One full directory enumeration per sweep, constant RAM; <=10s query
  budget plus one query and initial inventory I/O. No blanket directory rm.
- Collector admission before phase acquisition and recheck after acquisition;
  finish existing work, release lease before waiting, sender continues. Pause
  below max(2 GB,10%), resume above max(3 GB,15%); inode pause 5% / resume 10%.
  Unknown filesystem fails closed; startup in hysteresis band remains paused.
- Backfill checks 20% reserve +1 GB before start and each chunk. Heavy backup
  checks 20% +5 GB and configured 11 GB reserve; stream stops before consuming
  its reserve or cap. Active builds/archive jobs still require operator preflight
  with `storage_guard.py check --peak-bytes <measured>`; no claim of transparent
  interception of arbitrary shell commands.
- `storage-guard.sh` now exists; five-minute timer observes only. It is not a
  competing GC. It records bytes/inodes, 6h/24h growth availability and forecast.
  Database/partition/queue/WAL counters stay in existing hourly maintenance and
  existing exporter. Use existing alert channel only; no new monitoring stack.
- Host GC protects current/one rollback/process cwd/exe/all container mounts and
  systemd next-start references; application requires explicit reviewed release
  names. GC and deployment must share `/run/lock/m-ranked-release.lock`.

Existing fingerprint dedup already skips unchanged metrics except the 24h
heartbeat. Further thinning changes observation semantics and was not done.
Production source fingerprints are text, not bytea despite the old README.
Converting 64-hex to 32-byte keys could save roughly 31 bytes per row plus index
entry (~0.45–1 GB for ~15m rows and one large index), but rewrite/WAL/UNIQUE/FK and
client contract costs need measurement. No constraint index was removed, no
weaker hash substituted, no trigger disabled. No unconditional ever_positive
flag was introduced; the last-24 logic remains intact.

## Approval and rollout sequence

1. A1 is complete: migration dump and helper log follower removed after approval
   and fresh checks. Do not replay historical PID/path commands. For A2, review
   current exact obsolete image/release candidates and agree rollback assets
   before deletion; preserve unrelated services. Measure `df` after each action.
2. Verify the full dump on an isolated destination with enough space, including
   roles/ACL, schema contract, indexes/constraints, representative API queries and
   receipts/identity inventory. Approve reduction of completed dump count only
   after that evidence. Pin the known-good copy until its successor passes restore.
3. Approve code rollout: deploy one coherent release; point current and all
   ExecStart/WorkingDirectory/drop-ins at it; restart one layer at a time, keep
   sender/receiver delivery available. Preserve every still-active old release.
   Install storage helper files and timer, not an additional cleanup daemon.
4. On S2 build the three small indexes sequentially, then migration 0040; enable
   maintenance purge. Validate plan/latency/backlog after the first 1000 rows.
   Rollback: disable purge, restore previous function; index removal separately.
5. On S1 approve pending 0041 and one old-month fence/comparison/certificate/drop
   separately. Default mode remains off. Restore dropped facts from S2 or backup;
   configuration rollback alone cannot restore a dropped partition.
6. Observe a complete successful backup/retention cycle and at least 24 hours of
   growth/load. Stop the affected operation if freshness, backlog, lock waits,
   latency or resource pressure deteriorate. Ten-minute samples are preliminary.

### Routine commands (host-local; no access details)

```bash
python3 operations/scripts/storage_guard.py check --path /var/lib/m-ranked --peak-bytes 5000000000 --reserve-bytes 11000000000
python3 operations/scripts/gc_host_storage.py          # dry-run
systemctl status m-ranked-target-storage-guard.timer m-ranked-target-maintenance.timer
journalctl -u m-ranked-target-maintenance -u m-ranked-target-dump-backup --since '24 hours ago' --no-pager
```

Before installing the observation unit, create its state/textfile directories.
Before release GC, set explicit protected/approved basenames in its env and
recheck units and container mounts. GC is not a deployment tool.

The minimal unresolved product concession is a finite S2 detailed-observation
horizon or finite total collection volume. At .43–1.47 GB/day even a 30d extension
costs ~13–44 GB of DB growth plus dump amplification. A 90d target cannot be
promised on these disks. Select a concrete horizon only after daily-partition
model and replay/unique-state recovery are measured on the restored copy;
keeping unlimited user-visible full history requires storage that grows with it.

## Verification record (updated during this task)

- Full Python regression: 636 passed, 108 skipped (separate DB/external fixtures
  were not configured for that run), 2 pre-existing deprecation warnings.
- Isolated PostgreSQL 18.6 schema bootstrapped from every active migration,
  including 0040. Thirteen existing real-DB transfer/retention tests passed.
- Pending 0041 applied transactionally in an isolated test and rolled back:
  absent coverage refuses drop; frozen writes refuse; certificate survives ACK
  removal; fence-generation mismatch refuses; eligible verified empty month drops.
  Streaming comparison query ran against populated synthetic transfer fixtures.
- Ten focused evidence/backup/purge/coverage tests passed with PostgreSQL;
  26 final admission/GC/operations tests passed. New tests cover cursor progress
  after restart, orphan grace, stream cap, pinned-backup integrity mismatch,
  real pause/resume, inode pressure and backfill refusal before opening a DB.
- Runtime configuration and local documentation link checks passed. Host observer
  dry-run writes bounded JSON and textfile metrics on the local test filesystem.
- Full production nightly dump (3,705,949,100 bytes) restored locally with
  original roles/ACL after separate owner approval. Transfer took about 14 minutes
  including a failed SCP attempt/reconnection. Three-phase restore completed in
  **at most 353 seconds** on the Mac; this is not a production RTO guarantee.
  Result: 14,711,150,271 bytes database before test indexes, zero invalid indexes,
  revision 606901, 2,493 oldest-month snapshots, 151,991 inbox receipts, 70,802
  publications readable under api_read. Schema contract matches, CSV absent,
  collector capability membership and finalizer EXECUTE verified. Limited amcheck
  passed for oldest snapshot partition, inbox and account catalog (not every table).
  130 constraints remain NOT VALID, matching a fresh S2 catalog check; this drill does not prove every historical FK.
- The restored DB has 297,437 external raw-evidence references. A database dump
  contains metadata, not those files, provider sessions or service credentials.
  Full **database** recovery was exercised; complete host/service recovery still
  requires that separate inventory/copy. No claim of complete S2 disaster recovery.
- Plain parallel restore failed because an insert trigger reached an anomaly
  UNIQUE constraint before it existed. Successful procedure separates pre-data,
  data and post-data. Restoring role grants also required the original bootstrap
  superuser identity in the isolated cluster. Keep both findings in DR procedure.
- Measured on restored production data: three new indexes occupy **83,378,176
  bytes** combined (32,309,248 +65,536 +51,003,392); construction took 2.67s locally,
  observed WAL delta ~75.4 MB. The proposed 0.25 GB index/staging allowance is
  provisional for slower production disks; create one at a time and stop on
  pressure. One rollback-only 1000-row purge took 0.010s locally. No production
  SQL purge or index build occurred; artifact filesystem reclaim is recorded in A1 above.

No production backup/retention cycle or 24h post-rollout observation exists yet.
No claim of stable operation or reclaimed PostgreSQL filesystem bytes is made.

## Follow-up preflight — 04:00 UTC

A1 remains the only executed production cleanup. A fresh S2 filesystem probe
shows 77% used and 12.440 GB available; a provider panel still showing 80% is not
the authoritative filesystem measurement. S1 shows 81% used and 6.132 GB available.
The former 5.7G → 5.8G display change is consistent with the small S1 log reclaim.

The next private review package expands the S1 candidate set to four inactive
releases, with 1,178,886,144 combined exclusive file/symlink blocks (directory
blocks excluded). Fresh process cwd/exe/FD, container mounts and unit references
do not use them. Current and the running collector/sender release remain protected.
S2 has 227 candidate Docker images after preserving runtime images, an explicit
Backspace 1.4.0 rollback, and their ancestor image IDs. Four stopped build
containers have no mounts. The former 5.920 GB exclusive-layer estimate is still
an estimate, not additional measured reclaimed bytes. Download caches add about
0.092 GB on S1 and 0.301 GB on S2. These are candidates awaiting the new package
approval, not permission to delete by category.

Preflight found and fixed two deployment defects before rollout:
- Uninstantiated systemd templates cause `systemctl show` to fail. Release GC now
  reads unit fragments and drop-ins with `systemctl cat`, preserving next-start
  references and permitting safe dry-run on the actual S1 unit inventory.
- Atomic observer output inherited mode 0600. Exporter metrics now use 0644 so
  the separate node-exporter account can read them; private history remains 0600.

Nine focused GC/observer/backup tests pass. The observer test exercises two real
atomic writes and verifies permissions; S1 release-GC dry-run completed without
mutating production. No application rollout, new backup policy, SQL purge or
additional file/image deletion has occurred at this point.
