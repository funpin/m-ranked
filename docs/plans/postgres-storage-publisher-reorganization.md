# PostgreSQL Storage and Publisher Reorganization ExecPlan

Status: final-schema and one-time production transition rehearsed locally; production acceptance pending  
Started: 2026-09-08 (Europe/Moscow)  
Repository: `/Users/funpin/Documents/ChatGPT/TG-monitoring`  
Branch observed: `alpha` (four commits behind `origin/alpha`)  

## Goal and user effect

Keep collectors running continuously while API/web deployments remain independent of projection publication. Replace revision-triggered global history copies with a bounded, diagnosable publication lifecycle; suppress semantically redundant collector writes and revisions; separate projection-control backlog from cache delivery; make readiness mean “a valid serving generation exists”; and prepare, but do not apply to production, a separately reviewable retirement of obsolete `migration.*` objects with recovery evidence and legacy identifier mappings preserved.

The storage target is at least 70% less growth than the supplied 0.9–1.2 GiB/day baseline and preferably no more than 0.35 GiB/day. Code-level estimates are not proof: acceptance requires a production-shaped replay or restored-copy measurement of rows, bytes, WAL, and temporary bytes.

Database delivery has one current contract, `storage-publisher-final-2026-09-08-r3`:

- a new database is created directly from `backend/src/main/resources/db/final-schema.sql`;
- the verified production schema is changed once by `operations/sql/transition-production-to-final.sql`;
- normal deploys and service startup never run or validate a version chain;
- the existing production `flyway.flyway_schema_history` remains untouched but inert;
- the retired migration source files are recoverable from Git history and are not packaged or executed.

## Safety constraints

- Never stop collectors for projection work.
- Never deploy automatically or mutate production.
- Production diagnostics, if credentials are available, are explicitly read-only and exclude heavy `EXPLAIN ANALYZE`.
- Run destructive SQL (`DROP`, bulk `DELETE`, `VACUUM FULL`, `REINDEX`, large rebuilds) only on a disposable restored copy.
- Preserve the user's dirty-tree collector/storage work.
- Never rewrite or remove the existing production `flyway.flyway_schema_history`; it is recovery evidence, not a runtime input.
- Do not commit or push without explicit instruction.

## Baseline (supplied, not independently remeasured)

Observed around 2026-09-08 08:40 MSK:

| Measure | Value |
|---|---:|
| PostgreSQL size | 5.76 GiB |
| Server free space | about 17 GiB |
| Disk used | 42–43% |
| Operational rows | at least 18.6 million |
| `publication_metric_snapshot` | 5.52 million rows |
| `reaction_breakdown` | 10.71 million rows |
| `deletion_observation` | 2.21 million rows |
| Total new rows | about 4.1 million/day |
| Current storage growth | 0.9–1.2 GiB/day |
| Publication/account metric snapshots | about 854 thousand/day |
| Reaction breakdown | about 1.26 million/day |
| Deletion observations | about 1.93 million/day |
| Projection/outbox pending | about 6,282 total events, oldest about 6 hours |

Platform growth supplied: Telegram about 0.03 GiB/day, VK about 0.42 GiB/day, MAX about 0.69 GiB/day, Rutube about 0.05 GiB/day. These figures and the 5→9 GiB incident delta require database/WAL/temp/log evidence before attribution to a specific mechanism.

## Data-flow map

```text
platform collectors
  -> collector_target repository
  -> catalog/ingest rows
  -> analytics.dataset_revision
  -> ops_and_admin.outbox_event: projection.rebuild.requested
  -> projection publisher
  -> analytics.rebuild_serving_projections(revision)
  -> seven serving projections, including publication_history
  -> projection_state / projection publication events
  -> cache outbox worker -> Redis revision invalidation
  -> backend revision provider/readiness -> API
  -> web

admin configuration writes
  -> atomic catalog/rating change + dataset revision + audit
  -> the same projection.rebuild.requested control path
  -> never an inline serving/historical rebuild
```

Initial problematic coupling (now removed in the working tree): normal shadow
target/deploy started Publisher; Publisher required all nine projections at the
newest raw revision; each collector revision could make readiness fail and
trigger a global rebuild including full history and legacy export copies.

## Ownership map (initial; refine during discovery)

| Object/event | Producer/owner | Consumer | Class | Current concern |
|---|---|---|---|---|
| `analytics.dataset_revision` | collectors and admin commands | Publisher, API revision provider, projections | raw change-set | revisions may be created per batch even without semantic change |
| `projection.rebuild.requested` | collector repository/admin flows | projection publisher only | projection control | excluded by cache worker; must be coalesced and acknowledged by waterline |
| `dataset.revision.changed` | Publisher | cache outbox worker/Redis | cache delivery | delivery retry/terminal semantics need audit |
| `projection.published` | Publisher | cache worker records success | projection lifecycle | classification/observability unclear |
| `analytics.projection_state` | rebuild functions | readiness and API query code | serving state | one mutable row/name and exact-latest coupling |
| `ingest.publication_metric_snapshot` | collectors | projection rebuilds/API history | raw evidence/time series | redundant unchanged snapshots; the final contract adds semantic fingerprint/heartbeat |
| `ingest.reaction_breakdown` | collectors | publication history | snapshot child | amplified when unchanged parent snapshots are inserted |
| `ingest.deletion_observation` | collectors | audit/current deletion logic | event history | present-check row per cycle; the final contract introduces current state + meaningful events |
| `analytics.publication_history` | V12 rebuild wrapper | detail API | heavy historical projection | full copy of metric history on every rebuild |
| `analytics.legacy_export_row` | V17 refresh | legacy CSV endpoints | legacy compatibility | full temp snapshot/index plus full replacement |
| `migration.*` | completed bridge/import system | recovery, legacy projection, tests (inventory pending) | migration/recovery | must not remain a hot runtime dependency without proof |
| `catalog.legacy_entity_alias` | migration and native alias allocator | legacy routes/exports | canonical compatibility | preserve if runtime-used |

## Confirmed facts, evidence, risk, proposed change

| Fact | Evidence | Risk | Proposed change |
|---|---|---|---|
| Shadow target required Publisher | initial `m-ranked-shadow.target`/collector unit ordering | API/web deploy inherited heavy work/failure | implemented: Publisher removed from both targets, collectors and deploy |
| Publisher unit performs pre-build and auto-restarts | `ExecStartPre=... --once`, `ExecStart=...`, `Restart=on-failure` | attempt bound resets at the systemd boundary; restart-from-zero loop | implemented: explicit bounded serving oneshot; historical bootstrap remains a maintenance/recovery-only SQL entry point |
| Publisher targeted exact latest revision and all nine projections | initial script/readiness contract | collectors continuously invalidated readiness | implemented: seven serving states, including revision-bound publication history; previous valid generation remains readable, raw/published lag exposed |
| Publisher called one global rebuild | initial `analytics.rebuild_core_projections(revision)` call in script | large transaction, no durable checkpoint | implemented partially: normal publication calls the seven-projection serving entry point; its internal replacement remains global and needs incremental follow-up |
| Publication history is fully recopied | V12 deletes and reinserts `analytics.publication_history` from active snapshots | heap/index/WAL multiplication | serve bounded publication history from raw indexed data or incrementally materialize dirty publications |
| Legacy export is fully rebuilt through temp tables | V17 builds indexed temp relations, deletes and recreates `legacy_export_row` | temp/WAL/heap growth and runtime dependence on migration data | remove from core readiness/publication; retain only explicit legacy export path if still required |
| Cache worker intentionally excludes projection requests | `event_type <> 'projection.rebuild.requested'` | aggregate backlog is ambiguous, but zero attempts alone does not prove cache-worker failure | class-specific metrics/queries and consumers |
| Working tree contains unfinished collector/storage work | `git status` and diff | accidental overwrite/regression | preserve it and consolidate the database result into the final contract |

## Hypotheses requiring verification

- Account semantic fingerprints include observation timestamps or other transport-only fields, causing unchanged account batches to create snapshots/revisions.
- Dataset revision is committed per account batch rather than per completed collector run/change set.
- Full V12/V17 rebuilds contributed materially to the 5→9 GiB incident through copied heap/index data, WAL, temp files, or failed-transaction residue. The mechanism is plausible; its share is not measured.
- The seven serving projections still use global replacement internally; their
  cost and lock behavior require a production-shaped measurement before this
  can be called incremental publication.
- Legacy CSV/export endpoints are no longer a supported runtime requirement after the SQLite→PostgreSQL cutover.
- A schema-only disposable copy is sufficient for DDL/dependency rehearsal but not for bytes/WAL/temp or runtime-performance acceptance.

## Milestones and progress

- [x] M0. Read repository/root instructions and capture initial git state.
- [x] M0. Confirm initial Publisher/deploy/heavy projection causal chain from source.
- [x] M0. Create this living ExecPlan before application changes.
- [x] M0. Complete source-level call graph, ownership, migration, recovery, readiness, bootstrap, and deploy inventory.
- [x] P0. Decouple API/web deploy, targets and collectors from Publisher.
- [x] P0. Make Publisher an explicit locked/capacity-guarded oneshot with bounded failure; add lifecycle tests.
- [ ] P1 (partial). Suppress unchanged account/publication snapshots and revisions with a 24h heartbeat. Revisions remain per meaningful account batch, not coalesced once per whole run.
- [x] P1. Replace per-poll present history with current availability plus meaningful transition events; retain retry/replay guards.
- [ ] P2 (partial). Introduce a stable seven-projection serving watermark and readiness-vs-freshness semantics. Serving rebuild itself is still global, not incremental.
- [x] P2. Remove publication history/content/legacy export from normal publication and readiness.
- [x] P3. Split outbox classes, bounded delivery terminal state, hourly storage sampling and honest approximate row metrics.
- [x] P4. Produce usage matrix and three lifecycle tiers; make no retention or physical rewrite.
- [x] P5a. Remove hot runtime coupling from `migration.*`; verify the final bootstrap contains no `migration` or `flyway` schema.
- [x] P5b. Prepare and successfully rehearse the separate fail-closed `RESTRICT` migration-schema drop on a disposable copy; do not apply it to production.
- [x] Schema delivery. Replace the active migration chain with one final schema plus one guarded production transition; remove Flyway from runtime and normal deploy.
- [ ] Validation (partial). Unit/static suites and schema-only PostgreSQL rehearsals pass; production-shaped replay/storage measurements remain pending.

## Acceptance criteria

1. Standard API/web deploy does not start Publisher or stop collectors.
2. A valid previously published generation keeps API ready while newer raw changes/builds exist.
3. Publisher has one active instance, bounded failures, a terminal diagnostic state, and no automatic global restart loop.
4. Projection requests coalesce to a high-water mark.
5. Meaningfully unchanged publication/account metrics do not create snapshots before the configured heartbeat; unchanged child reactions do not insert.
6. Present checks update current availability without appending deletion history each cycle; state transitions remain auditable and idempotent.
7. Dataset revisions represent semantic committed change sets, preferably one per completed collector run.
8. Outbox metrics and retry policies distinguish projection control from cache/integration delivery.
9. Health no longer represents snapshot rows as all database rows; large-table counts use cheap/clearly approximate statistics.
10. A production-shaped replay/restored copy demonstrates rows/day, bytes/day, WAL, and temp before/after. Target is ≥70% storage-growth reduction and ≤0.35 GiB/day; otherwise record the residual source and exact product retention/semantics decision needed.
11. Legacy identifier mappings, immutable recovery evidence, reports, source manifests/checksums, and tested restore instructions survive migration-schema retirement; existing production bootstrap metadata is audit-only.
12. Migration-object drop remains separate and unapplied to production until explicit approval.

## Rollback by phase

- P0: restore unit/target/deploy files from the prior release; keep Publisher disabled if capacity is uncertain. This is operational rollback only and does not revert collected data.
- P1: disable semantic suppression through a documented configuration fallback only if API temporal invariants fail; forward-fix the final contract. Current-state/event rows remain additive.
- P2: atomically select the last known-valid serving generation; never delete it during build or activation. Drop no old projection until consumers are verified.
- P3: retain old metric fields during a compatibility window if external consumers require them; worker class changes must be independently reversible.
- P4: no retention/partition drop without approved policy, archived manifests, and restore rehearsal.
- P5: restore from the verified recovery pack on a disposable copy first; production rollback requires the predeclared recovery procedure and preserved mappings. Never attempt a blind down-migration.

## Decision log

- 2026-09-08: Treat supplied production measurements as baseline evidence supplied by the operator, not locally reproduced facts.
- 2026-09-08: Preserve all pre-existing dirty-tree changes and build P0 independently of the unfinished V31 collector work.
- 2026-09-08: Do not attribute the 5→9 GiB incident to one mechanism without PostgreSQL/WAL/temp/log evidence.
- 2026-09-08: Keep projection control events out of Redis delivery; fix observability/classification rather than publishing them merely to lower a combined backlog.
- 2026-09-08: Decommission `migration.*` only after runtime dependency removal and restored-copy rehearsal, as a separate reviewable change.
- 2026-09-08: Define the public consistency boundary as seven serving projections, including `publication_history`. `publication_content` and `legacy_exports` keep independent watermarks and cannot make API readiness fail.
- 2026-09-08: Keep publication explicit. No timer/target/deploy automatically starts Publisher; a failed oneshot terminates and requires operator review before another invocation.
- 2026-09-08: Configuration/admin writes must share the projection-control queue. The final contract patches the existing audited SQL commands and the Java admin repository queues the request in the same transaction instead of invoking the maintenance/recovery-only historical bootstrap.
- 2026-09-08: Do not implement retention, repartitioning, index removal, packed reactions or a physical rewrite without production-shaped plans and a product-approved lifecycle policy.
- 2026-09-08: Do not couple the migration-schema drop to schema installation. The prepared SQL accepts only an explicitly guarded disposable database name and uses `RESTRICT`, never `CASCADE`.
- 2026-09-08: Production inspection showed V1–V30 were installed in one initial 193-second bootstrap, not through operational upgrades. Per user decision, the source version chain is retired in favor of one final schema and one production transition.
- 2026-09-08: Normal deploy and service runtime validate `ops_and_admin.schema_contract`; no service reads Flyway history. Existing production Flyway rows remain unchanged solely as historical recovery evidence.

## Discovery log

- 2026-09-08: Only repository `AGENTS.md` found is under `frontend/`; it applies when frontend work occurs and requires reading the installed Next.js guide before changes there. Root instruction includes `/Users/funpin/.codex/RTK.md`; shell commands must be prefixed with `rtk`.
- 2026-09-08: Git branch is `alpha`, behind remote by four commits, with 19 modified tracked files and untracked V31/database audit artifacts. No rebase/pull is attempted because it could disrupt user work.
- 2026-09-08: `m-ranked-shadow.target` requires API, web, and Publisher. The Publisher unit is ordered before collectors and uses preflight `--once`, daemon execution, and `Restart=on-failure`.
- 2026-09-08: `projection-publisher.sh` expects exactly nine ready projection-state rows at latest raw revision and runs the global rebuild otherwise.
- 2026-09-08: V12 fully deletes/reinserts publication history. V17 creates multiple indexed temp snapshots and fully deletes/reinserts legacy export rows.
- 2026-09-08: Cache outbox worker explicitly excludes projection rebuild requests, so combined unpublished count and zero attempts are not sufficient evidence of cache delivery failure.
- 2026-09-08: V9's base serving function took a table-level SHARE lock on `analytics.dataset_revision` and rejected any newer revision, so collectors could block or invalidate an in-progress build. V32 retains the transaction advisory lock but builds the captured watermark while later raw revisions continue.
- 2026-09-08: `JdbcDatasetRevisionProvider` already had the right fallback shape (newest fully published revision), but its required set included the three heavy compatibility projections. It now selects the newest complete six-state generation.
- 2026-09-08: The runtime repository contained no `databaseRows` field. V34 exposes `databaseSizeBytes` and explicitly named approximate `rowEstimates` sampled hourly instead of inventing an exact all-database row count.
- 2026-09-08: Runtime SQL dependencies on `migration.*` existed in serving legacy-error logic, official rating context, publication content/history reaction refresh and legacy account presentation. The final contract redirects those to canonical data; bridge/reverse-sync tooling remains classified recovery/transition code.
- 2026-09-08: Read-only production inspection found PostgreSQL 18.6, database size 6,388 MB, exactly successful Flyway V1–V30, and installation timestamps spanning only 193 seconds. New storage/publisher objects were absent; all collectors were active and Publisher was inactive.
- 2026-09-08: The production `postgres:18.6` image was transferred to a local disposable Docker environment. A schema-only production copy (no data) accepted the guarded transition atomically; a second application failed closed as designed.
- 2026-09-08: A separate empty database accepted `final-schema.sql` directly and exposed the same contract to API/admin/collector/maintenance roles. It contains neither `migration` nor `flyway` schemas.
- 2026-09-08: The guarded migration-schema retirement succeeded on a disposable clone while preserving `flyway.flyway_schema_history`, `catalog.legacy_entity_alias`, and the final contract.
- 2026-09-08: Source inventory found that Java account enable/disable and the SQL `catalog_command`/`import_official_rating` functions still rebuilt projections synchronously. They now atomically enqueue `projection.rebuild.requested`; static/Java tests guard against restoring the inline call.

## Before/after estimate (not acceptance evidence)

The supplied daily row baseline is about 4.04 million for the three dominant
families: 1.93 million deletion observations, 0.854 million metric snapshots
and 1.26 million reaction rows. Suppressing the reported 99.99% no-op present
history removes about 1.93 million candidate inserts/day. If the supplied 55%
unchanged share applies to both parent snapshots and their reaction children,
semantic suppression removes another approximately 0.47 million snapshots and
0.69 million reaction rows/day outside heartbeat. That is roughly 3.09 million
of 4.04 million rows, or 76%, leaving about 0.95 million rows/day plus heartbeat
and rare transition events.

This extrapolation is useful for prioritization but does **not** prove a 70%
byte/WAL reduction: row widths and indexes differ, current-state updates create
WAL/dead tuples, heartbeat distribution is unknown, and an explicit serving
rebuild still globally replaces six tables. The supplied 0.67 GB/day attributed
to deletion history is the only byte component with a direct estimate. The
target of <=0.35 GiB/day remains unverified; exact residual bytes/day require
the staged replay and hourly samples introduced here.

## Validation commands and results

All commands are local/read-only unless a later entry explicitly says otherwise.

| Command | Result |
|---|---|
| `rtk git status --short --branch` | `alpha`, behind 4; dirty tree described above |
| `rtk rg --files -g AGENTS.md ...` | only `frontend/AGENTS.md` in repository |
| source inspection of target/unit/publisher/V12/V17 | causal chain confirmed as recorded above |
| `rtk bash -n` on changed operational scripts | pass |
| focused Python lifecycle/collector/manifest/decommission tests | 130 passed, 96 DSN-dependent skipped in the broad focused run; final checksum/tamper/lifecycle subset: 113 passed |
| full Python `.venv/bin/pytest -q` | 530 passed, 167 skipped |
| `rtk ./mvnw test -q` in `backend` | 219 tests, 0 failures/errors, 48 PostgreSQL/Redis-dependent skipped |
| transition on schema-only production copy | pass; repeat application rejected by source-contract guard |
| empty-database final-schema bootstrap | pass through both raw `psql` and the actual Compose/Java CI paths; contract readable by API/admin/collector/maintenance; no `migration`/`flyway` schema |
| disposable migration-schema retirement | pass with explicit object list and `RESTRICT`; protected Flyway table and canonical aliases remained |
| database physical/WAL/temp/outbox queries | production read-only baseline inspected; before/after performance remains pending because the copy is schema-only |

## Open questions

- Can a data-bearing production-shaped restore be provided for rows/bytes/WAL/temp acceptance without risking production?
- Which legacy CSV/export endpoints remain contractually supported after cutover?
- What is the approved retention/detail policy for high-frequency raw metrics, reaction breakdown, and deletion evidence?
- What freshness SLO/alert threshold is acceptable while API serves a previous generation?
- Which degraded provider fields are unknown/unsupported versus true zero/reset? This does not block P0/P1.
- Can a production-shaped data restore be provided for publisher/collector concurrency and storage-growth rehearsal?

## Exact implementation state at last update

Working-tree implementation now contains P0-P3, the P4 analysis, P5 runtime
decoupling, one declarative final schema and one guarded production transition.
The retired migration files and unreleased split drafts are absent from the active schema
source. Normal deploy does not invoke or validate Flyway. No commit, push, deploy, production write,
retention action, data deletion, or production migration-schema drop occurred.

The implementation is not production-accepted. Remaining hard gates are a
data-bearing rehearsal of the single production transition; concurrent collector
and Publisher crash/restart tests; production-shaped before/after replay measuring
rows/bytes/WAL/temp and rebuild duration; catalog dependency inventory; and the
restored-copy recovery/drop rehearsal. P2's serving rebuild remains global, and
P1 revisions remain per meaningful account batch. Those are explicit residual
risks rather than claimed completion.
