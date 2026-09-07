# Production verification and compressed source preservation — 2026-09-07

## Actual import state

At 01:12 UTC all 4,175,064 initial-source stream rows were committed, but the
import process was still building projections. The report directory was empty;
100% of stream checkpoints was not completion of reconciliation.

At approximately 01:17 UTC the projection transaction rolled back because
the bridge's fixed five-minute statement timeout expired while creating
`pg_temp.mranked_projection_snapshot` from
`analytics.usable_publication_snapshot`. The batch became `failed`, with that
specific error. Previously committed source rows remained in PostgreSQL.

An independent read-only aggregate check subsequently confirmed exactly:

| Platform | PostgreSQL snapshots / S0 expected |
|---|---:|
| Telegram | 1,081,624 |
| VK | 1,642,117 |
| MAX | 1,380,353 |
| Rutube | 49,730 |

There were zero invalid PostgreSQL indexes and zero unvalidated constraints in
`ingest`, `migration` and `catalog`. These are preliminary checks, not a claim
that canonical values, projections and identity-history reconciliation passed.

## Unimported live changes

`/var/lib/m-ranked-migration-status/live-delta-20260907.json` records a bounded
read-only comparison of S0 with the still-running legacy SQLite. Short reads
release SQLite locks between chunks; this is an observed live delta, not an
immutable catch-up artifact or a single consistent point in time.

- All 4,153,824 original metric snapshots remained present and byte-value equal
  at the SQLite row level. At least 47,476 new Telegram snapshots and 171,940
  other-platform snapshots were observed: 219,416 new metric rows in total.
- Two original `posts` and two `post_messages` rows were absent in the live
  database. The live database therefore is not a full replacement for S0.
- New rows: 19 posts, 19 post-message associations, 14 platform posts.
- Changed rows: 66 channels, 261 platform accounts, 14,891 platform posts and
  15 app-state rows. These changes also need catch-up handling.
- Live SQLite, archives, platform sessions and the verified recent scheduled
  gzip backup remain on the host. No unimported live row was removed.

## Space recovery while retaining the exact S0

Installed Debian `squashfs-tools` and its `liblzo2-2` dependency (645 kB installed).
Created a single-threaded zstd level-3 read-only image with 128 KiB blocks:

`/var/lib/m-ranked/source-images/s0-20260906.squashfs`

The image occupies approximately 390 MiB instead of the 1.8 GiB uncompressed
source directory. Every file's full SHA-256 matched before removing the raw
duplicate. SQLite `quick_check` passed, and `foreign_key_check` returned no rows.
S0 remains byte-identical, including its original hash
`4061e900f6f2700498795e39d8fa70a076a9f191e3c30b143cb455371c26f80e`.

The image is mounted read-only with `nodev,nosuid,noexec` at the original
`/opt/telegram-reaction-monitor/data/backups/cutover-20260906` directory through
an enabled systemd mount unit. The backfill service requires and starts after
that mount. The mount switch used the existing transition lock while backfill
was stopped, with a rollback path before any raw source removal. Full hashes
were rechecked through the final mount. The original three uncompressed files
were then removed, recovering 1,833,861,120 allocated bytes before subtracting
the image size. Mounted files are regular files, not substituted source rows.

Because a Squashfs mount reports no writable free space, the backfill reserve
check now checks `/work` (the actual PostgreSQL host filesystem), instead of
`/source/s0.sqlite`. The independent guard still checks host `/`. Both retain
the 3 GiB threshold. Do not revert this path while using the compressed mount.

Two unused August SQLite backups were also losslessly compressed and verified,
recovering about 53.5 MB. Package download/index caches were removed after
installation. Net source/old-backup compression saved approximately 1.48 GB.
At 01:23 UTC the root filesystem had 5,705,756,672 bytes available, 82% used.
Detailed compression receipts remain under `/var/lib/m-ranked-migration-status/`.

## Verification retry

Sealed source `alpha-v30-bridge-20260907-r5` keeps all data mapping unchanged.
Its manifest SHA-256 is
`f42746e59d9b4158cc3087605196c165afed411c012faf69e7de0a1d096c0e7c`.
Only the operational wrapper adds a configurable statement timeout, bounded
between 300 and 1800 seconds and defaulting to the old 300 seconds. The
production retry selects 1800 seconds. A real connection under migration UID
confirmed `SHOW statement_timeout = 30min`; 299 seconds was rejected before
connecting. Memory, CPU, lock and reserve protections remain enabled.

The resumed service revalidates the entire source before retrying projection
building and the existing canonical/projection/identity-history checks. The
current independent guard is
`m-ranked-backfill-progress-r5b-20260907.service`. Its status logic distinguishes
source preparation and all-streams-loaded verification from completed import.

Do not declare final acceptance, remove S0 authority, or retire live legacy
SQLite based on this file. Final reconciliation and catch-up remain pending
until their actual reports pass.

## Physical index compaction

Page-level `pgstatindex` diagnostics (temporary extension/schema created and
rolled back) found the two largest indexes only 52.39% and 53.60% full, plus
nine other indexes larger than 150 MiB with 52–69% leaf density. No index was
dropped as supposedly unnecessary. Instead, paused the backfill, explicitly
canceled its remaining PostgreSQL query, and rebuilt these indexes sequentially
under the transition lock while legacy continued collecting into SQLite.

The first rebuild hit the existing 512 MiB temporary-file limit and rolled back.
The successful maintenance sessions used 128 MiB maintenance memory, a 1 GiB
temporary-file limit, zero parallel maintenance workers, a three-second lock
timeout and a fifteen-minute statement timeout. A separate two-second host
free-space check canceled only the maintenance session if it reached 3 GiB.
These were session settings, not widened database-wide limits.

All eleven rebuilt indexes remained valid/ready. Actual physical index sizes
decreased by **2,528,428,032 bytes** in total. The detailed before/after receipt
is `/var/lib/m-ranked-migration-status/index-compaction-20260907.json`.
Post-compaction checks found zero invalid/not-ready indexes, and all 4,175,064
committed checkpoint rows with all streams complete. Together with lossless
source/old-backup compression, this turn reclaimed approximately **4.01 GB**.
The filesystem then had **8,230,846,464 bytes available**, 74% used.

Full verification was restarted after compaction with the same sealed r5 source
and batch. The current independent guard is now
`m-ranked-backfill-progress-r5c-20260907.service`. The longer SQL timeout and
both 3 GiB reserve checks remain enabled. The aggregate/source checks above
passed; the final projection/identity reconciliation report is still required.

At 01:51:07 UTC, the retried projection build was still active and the final
report directory remained empty. Available space was 6,948,233,216 bytes (78%
used) as the build allocated working data. The backfill and r5c disk guard were
active, public phase was `verifying`, and legacy health was `ok` with fresh
collection (latest completed poll 01:49:38 UTC). No full reconciliation success
or catch-up completion is claimed at this observation.
