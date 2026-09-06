# Production migration preflight — 2026-09-06

Current result: **initial production import running; writer cutover remains pending**.
The original stopped preflight and its findings are retained below as history.

At 18:40:29 UTC the public endpoint reported 21,240 committed source rows;
the next database check had 22,240. At 18:42:42 UTC the committed count was
52,240. The exact batch is `e832c733-8416-5f15-8649-b11405e49528`, namespace
`m-ranked-production`, source SHA-256 as recorded below, bridge 1.3.1.
Counters are real batch checkpoints, not elapsed-time estimates.

Changes since the initial stopped attempt:

- Additive V30 retains legacy forced-history/baseline combinations. Collector
  refresh preserves the original baseline and resolves presence/deletion probes
  to the stored publication UUID after matching imported identities.
- Official rating values pass through Decimal to preserve the exact legacy
  decimal representation in PostgreSQL.
- The latest complete isolated integration run
  `migration/reports/integration-v30-production-20260906-r3/integration.json`
  passed all 33 steps. Separate actual-source verification imported all 229
  affected publications, matched independent source/projection/history oracles,
  repeated without writes, added 229 collector observations across 24 accounts
  without duplicate retries, and rebuilt all nine projections. These remain
  test evidence, not production acceptance.
- Offloaded and SHA-256 verified 17 old backup/duplicate files totalling
  3,937,078,302 bytes before exact server deletion. Also cleared download caches.
  Disk usage fell from about 13 GiB to 9.3 GiB before adding target infrastructure.
  Source snapshots, archived publication files and authentication sessions remain.
- New `mranked-production-postgres-1` runs PostgreSQL 18.6 on localhost with
  512 MiB memory limit, checksums, fsync and a bounded WAL configuration.
  Actual Flyway 11.14.1 installed and validated exact V1–V30 at 18:27 UTC.
- `m-ranked-backfill.service` runs the immutable bridge source under its own
  UID in a read-only Python 3.13 container, with a 384 MiB memory limit and a
  three-GiB disk reserve checked before transaction batches. Its first start
  failed before any insert because the image's home directory was private to
  the build UID. Runtime r2 fixes directory traversal; it was verified under a
  different UID before restarting. The source snapshot is mounted read-only.
- `m-ranked-migration-status.service` now uses a separate UID and a PostgreSQL
  role with SELECT access only to the batch and checkpoint tables. The private
  `m-ranked-backfill-progress.service` binds the exact batch, tracks preparation,
  import, stop/failure and completed-initial-snapshot states.

Legacy collector/web units remain active and fresh. Full source reconciliation,
catch-up/S-final, production backup/restore, shadow application checks, writer
cutover and old-stack retirement are still outstanding. Do not treat the
running import or these local test results as permission to retire legacy.

## Original preflight record

Requested source release: branch `alpha`, commit
`6e10107` (`Unify history chart metrics and reveal selected observations`).
Two pre-existing modified runtime log files were left untouched.

## Verified preservation

Created a separate online SQLite Backup API snapshot while legacy collectors
continued running:

`/opt/telegram-reaction-monitor/data/backups/cutover-20260906/reactions-20260906T172657Z.db`

- 1,833,836,544 bytes; SQLite quick check passed; zero foreign-key violations.
- SHA-256: `4061e900f6f2700498795e39d8fa70a076a9f191e3c30b143cb455371c26f80e`.
- 4,175,064 source rows across all ten bridge streams.
- 4,153,824 metric snapshots: Telegram 1,081,624; VK 1,642,117;
  MAX 1,380,353; Rutube 49,730.
- 66 institutions, 261 platform accounts, 2,489 Telegram publications and
  15,827 platform publications.
- All 62 files under the separate archives tree (225,099,595 uncompressed
  bytes) have individual verified hashes.

Compressed SQLite, archives, inventory and SHA256SUMS were also copied off the
server into the ignored local directory `data/production-cutover-20260906/`.
Local verification hashed both compressed files, streamed and hashed the entire
uncompressed SQLite, and matched every archive member's size/hash against the
server inventory. `backup-verification.json` records a pass at
2026-09-06T17:40:15Z. This is a verified source backup, not a PostgreSQL restore
or a completed migration.

## Reproduced incompatibility

Exactly **229** source Telegram publications simultaneously have
`history_forced_incomplete=1` and `baseline_from_publication=1`. Example source
IDs: 206–210. Both are original stored facts and must be retained.

1. `backend/src/main/resources/db/migration/V1__target_baseline.sql:317`
   rejects this combination after the bridge maps it to
   `history_completeness=forced_incomplete` and
   `synthetic_baseline_allowed=true`.
2. `collector_target/repository.py:828` independently resets the baseline to
   false on the next collector refresh of a forced-incomplete publication.
   Relaxing only the constraint would therefore fail to preserve the imported
   decision during continued collection. V9 period projections consume this
   stored baseline, so the issue can affect historical results.

The exact constraint and collector CASE expression were extracted from the
current source and executed in a temporary table/read query on local PostgreSQL
with a final ROLLBACK. Output:

```text
PASS: current release rejects forced_incomplete + preserved baseline
{"currentBaseline": true, "collectorRefreshBaseline": false,
 "forcedIncompletePreserved": true}
```

The reproduction and source hashes are saved as
`data/production-cutover-20260906/baseline-reproduction.sql` and
`baseline-source-hashes.json`. No production schema constraint was dropped and
no SQLite values were edited. The existing local sample has an explicit local
constraint exception; it is not evidence that the unmodified release can import
production.

## Required corrective release

- Add an additive schema migration that preserves the independent imported
  baseline decision without rewriting frozen V1–V29.
- Preserve that imported decision across collector refresh and replay, while
  continuing to prohibit invention of new synthetic baselines for native
  forced-incomplete publications. Update both the UPDATE expression and its
  change-detection expression together.
- Verify the actual import → collector refresh → projection rebuild → reverse
  projection path for affected original records and native records. A constraint
  relaxation alone is insufficient; the corrective implementation has not been
  made or accepted in this run.
- Update release-bound schema manifests and produce fresh integration,
  collector parity, reconciliation, reverse-sync and restore evidence for that
  corrective release. Do not relabel the existing V29 reports as approval.

The production host currently has no target installation/PostgreSQL or target
backup/standby setup. It has approximately 2 GiB RAM and almost fully occupied
512 MiB swap while running other services. Capacity and independent PostgreSQL
recovery need validation before bringing up the shadow target. The repository
cutover procedure additionally requires independently accepted production-like
collector/reverse-sync proofs, a tested restore and the rollback observation
window. Those artifacts were not present on the host and were not fabricated.

## Production changes and current behavior

The user subsequently requested live progress on the homepage. Installed the
temporary exact `/` route and `/migration-status.json`, with a ten-second status
publisher. It honestly reports `blocked`, 0 transferred, 4,175,064 remaining,
and explains that import has not started. Other routes retain the legacy
upstream. The publisher reads current legacy health and confirms continued
collection when `collector_fresh=true`.

During page activation, an immediate reload check first saw the previous Nginx
worker's 404 and correctly restored the prior configuration. The next activation
exposed a file-alias/index handling error: the homepage briefly returned HTTP
500, observed from 17:41 UTC. Replaced the file alias with root plus try_files,
verified public HTML and JSON, and visually confirmed the live page by 17:42
UTC. Collector and legacy web units remained active throughout these route
changes. This transient homepage incident is not omitted from acceptance.

No legacy services, source database, archives, sessions, credentials or code
were removed. Target writers were not started. The requested application
deployment, full PostgreSQL migration and old-stack removal remain incomplete.
