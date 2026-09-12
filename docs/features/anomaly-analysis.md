# Anomaly-dynamics analysis

Publication-level anomaly-dynamics signals for Telegram, VK, MAX and Rutube.
An independent worker analyses the published metric history of each publication
and stores versioned findings; the API and the publication page expose them as a
heuristic signal strength, never as proof of artificial activity.

## 1. Implemented

Publication-level anomaly-dynamics analysis for Telegram, VK, MAX and Rutube
publications over the cumulative metrics `views`, `reactions`, `comments` and
`shares` where the seeded capability matrix supports them. A new Python worker
package `anomaly_analysis/` evaluates a fixed, fully published source dataset
revision with three pure detectors, publishes results atomically under an
independent monotonic analysis revision, and Spring/Next expose them through a
dedicated bounded resource on the publication detail page. Two ADMIN-only
commands create manual signals and append reviews. Nothing in rating,
overview, exports, `/manage`, legacy SQLite, bridge or reverse sync changed.

## 2. Architecture mapping

| Approved stage | Implementation |
|---|---|
| Canonical observations | Unchanged: collectors keep writing `ingest.publication_metric_snapshot`. |
| Candidate | V31 `AFTER INSERT` trigger `anomaly_candidate_after_effective_snapshot` → SECURITY DEFINER coalescing upsert into `ops_and_admin.anomaly_analysis_candidate` (dirty generation, eligibility ≥ published_at + 15 min with age bands, priority 100; config backfill priority 10). Exact replay never reaches the AFTER trigger (V9 BEFORE trigger returns NULL). |
| Worker | `anomaly_analysis/coordinator.py` (`AnalysisCoordinator.run_once`): pin latest fully published core revision (seven-projection barrier) (`ops_and_admin.pin_latest_anomaly_source_revision`), rate-limited bounded backfill seeding, `FOR UPDATE SKIP LOCKED` claim with lease/expiry recovery, one set-based as-of extraction per batch (`analytics.extract_publication_history_as_of`), deterministic input hash, unchanged-input no-op, complete detector set, aggregation, atomic success/failure publication with bounded retry backoff. |
| Preprocessing | `anomaly_analysis/preprocessing.py` (`PREPROCESSING_VERSION 1.0.0`): chronological ordering, duplicate suppression, NULL/invalid/reset masking, synthetic exclusion, time-normalised segments with negative-delta breaks, trusted-interval flags, coverage, gaps, robust median/MAD, linear fit. Bound exceeded is a typed state, never truncation. |
| Detectors | `delayed_spike_after_plateau`, `suspiciously_linear_growth`, `periodic_large_jumps` (each `1.0.0`), pure functions over `PublicationHistory` + `PreparedSeries`, explicit registry `DetectorRegistry`, typed frozen configs hashed into the manifest (`AnalysisManifest.sha256`). |
| Aggregation | `anomaly_analysis/aggregation.py` (`AGGREGATOR_VERSION 1.0.0`): maximum active automatic score; clean evaluated → `0`, all abstained → `NULL`, exception → attempt failure. Manual severities never enter the numeric score. |
| Persistence | Delivered inside the single declarative contract `backend/src/main/resources/db/final-schema.sql` (contract `storage-publisher-final-2026-09-08-r4`) and, for the existing production database, the same block inside `operations/sql/transition-production-to-final.sql`; no Flyway migration exists any more. Objects: `analytics.anomaly_analysis_revision`, `anomaly_source_revision`, `publication_analysis_attempt`, `publication_analysis_state`, `publication_anomaly_finding` (stable `finding_key`), `publication_anomaly_review` (append-only, keyed by `finding_key`), `ops_and_admin.anomaly_analysis_candidate`, `anomaly_command_receipt`; safe public views `publication_analysis_state_public`, `publication_anomaly_finding_public`; seeded `metric_semantic_definition` v1 and `platform_metric_capability` v1. |
| Analysis revision | Independent identity sequence per publication event (`automatic_success`, `automatic_failure`, `manual_signal`, `review`); never touches `dataset_revision`, `projection_state`, `rebuild_core_projections`, the publisher or `JdbcDatasetRevisionProvider`. |
| Spring/OpenAPI | `org.mranked.analysis` slice (domain/application/infrastructure/web); `GET /api/v1/publications/{id}/anomaly-analysis` (canonical UUID or legacy id + `legacyType`, limit 1..100, cursor bound to publication+analysis revision+limit, ETag from dataset revision + analysis revision + representation, `Cache-Control: public, max-age=30, must-revalidate`, 304); `POST /api/v1/admin/publications/{id}/anomaly-signals`, `POST /api/v1/admin/anomaly-signals/{findingId}/reviews` (ADMIN, CSRF, Basic, idempotency key + request digest, correlation, no-store, RFC 9457). |
| Frontend | `frontend/app/publications/[id]/page.tsx` loads history and analysis in parallel with one bounded history refetch when the analysis source revision is newer; `components/anomaly-analysis.tsx` renders the neutral block; `publication-measurements.tsx`/`history-data.ts` keep evidence boundary points through 144-point sampling, mark them on both charts and in the table with non-colour cues and screen-reader text. |
| Operations | `operations/systemd/m-ranked-target-anomaly-analysis.service` (hardened, `Wants=` from `m-ranked-target.target`, PGPASSFILE credential, textfile metrics), env example, `analytics_worker` role provisioning, exporter/alerts/runbook, release manifests/checksums, restore verification, integration runner stage on a dedicated `anomaly_it` database. |

## 3. Key files changed

- Python analyzer: `anomaly_analysis/{__init__,domain,preprocessing,config,registry,aggregation,coordinator,postgres,metrics,__main__}.py`, `anomaly_analysis/detectors/{base,delayed_spike,linear_growth,periodic_jumps}.py`.
- Database: `backend/src/main/resources/db/final-schema.sql` (regenerated: `pg_dump --schema-only` of a fresh r2 bootstrap plus the anomaly objects, same manual header/seed conventions as upstream), `operations/sql/transition-production-to-final.sql` (anomaly block + r3 contract), `migration/schema/smoke.sql` (`analytics_worker` in the role checks), contract-id pins in 26 files, `infra/postgres/init/001-create-roles.sh`, `infra/compose.yaml`, `infra/postgres/compose.env.example`.
- Backend: `backend/src/main/java/org/mranked/analysis/**`, `admin/infrastructure/AdminDatabaseConfiguration.java`, `admin/infrastructure/ApiSecurityConfiguration.java`, `admin/web/AdminRfc9457ExceptionHandler.java`.
- OpenAPI: `contracts/openapi/m-ranked-v1.yaml`, regenerated `contracts/openapi/m-ranked-v1-client.ts`.
- Frontend: `frontend/app/publications/[id]/page.tsx`, `frontend/components/{anomaly-analysis,publication-detail,publication-measurements}.tsx`, `frontend/lib/{api,types,history-data}.ts`, `frontend/app/globals.css`.
- Operations: `operations/systemd/m-ranked-target-anomaly-analysis.service`, `operations/systemd/m-ranked-target.target`, `operations/env/anomaly-analysis.env.example`, `operations/observability/{exporter.py,operations-alerts.yml,README.md}`, `operations/runbooks/DEPLOY.md`, `operations/scripts/{deploy-shadow,cutover-preflight,restore-verify}.sh`, `operations/collector_parity_evidence.py`, `migration/integration/run.py`.
- Tests: `tests/test_anomaly_analysis.py`, `tests/test_anomaly_analysis_postgres.py`, `backend/src/test/java/org/mranked/analysis/**`, `ArchitectureTest`, `OpenApiContractTest`, `ApiSecurityConfigurationTest`, `frontend/tests/{api.test.ts,history-data.test.ts,api-fixture.mts,browser/history-interactions.spec.ts}`, `tests/test_collector_parity_evidence.py`, `tests/test_operations_metrics_postgres.py`.
- Docs: this document.

## 4. Detector behaviour

Common abstentions (all detectors): metric not in the platform capability set
(`metric_unavailable`), input bound exceeded, too few real observations, too
short duration, insufficient usable-quality coverage, incomplete/forced
history, excessive sampling gap relative to the observed cadence.

- **Delayed spike after plateau.** Scans trusted non-negative segments; requires
  a preceding plateau of ≥ `minimum_plateau_seconds` built from trusted
  intervals, low plateau growth (≤ 12 % of the pre-jump value), a jump with
  absolute delta ≥ 50, relative delta ≥ 20 % and rate ≥ 8× the robust
  (median + 3·MAD) plateau rate. Interval-censored evidence: endpoint snapshot
  ids/timestamps, delta, duration, rate, baseline median/MAD, ratios, coverage.
  Alternatives: external referral, provider batching, legitimate promotion.
- **Suspiciously linear growth.** Bounded candidate onsets (≤ 24 windows) over
  trusted, certain points; requires ≥ 8 points, ≥ 30 min, growth ≥ 100,
  positive slope, R² ≥ 0.985, normalised RMSE ≤ 0.035, rate CV ≤ 0.18. Rounded
  counters are penalised and flagged. Flat series never qualify (growth floor).
- **Periodic large jumps.** Jump extraction by prominence (delta ≥ 50, rate ≥ 5×
  robust baseline), ≥ 3 repetitions, spacing CV ≤ 0.20, magnitude CV ≤ 0.50;
  midpoint spacing with interval uncertainty; a period explainable by the
  collector cadence (within 8 %) with event uncertainty ≥ cadence abstains as
  `collector_cadence_confounding`.

## 5. Database / revision semantics

- Independent `analytics.anomaly_analysis_revision`; attempts pin
  `source_dataset_revision_id` that must exist in `anomaly_source_revision`
  (only revisions with the seven core projections ready are pinned).
- As-of extraction selects, per logical bucket, the highest correction whose
  `created_at` ≤ the pinned revision's `committed_at`; future corrections are
  invisible (PostgreSQL test).
- Success publication is one SECURITY DEFINER transaction: idempotent by
  `(publication, attempt_key)`, verifies claim token/generation and pinned
  source, inserts attempt + complete finding set, upserts state, switches the
  success pointer, writes a safe tombstone to `ops_and_admin.audit_log`, prunes
  the previous success, and releases the candidate only if no newer generation
  arrived.
- Failure publication keeps the success pointer, replaces the failure slot
  (tombstoned), sets `stale` (success exists) or `failed`, schedules bounded
  retry; only a stable error code is stored.
- Retained per publication: latest success + latest failure. Manual findings,
  reviews and audit rows are never pruned.
- The seven-projection core barrier, `rebuild_core_projections`,
  `projection-publisher.sh`, `JdbcDatasetRevisionProvider` and core Redis
  invalidation are byte-for-byte unchanged; the PostgreSQL test publishes a
  core revision while the analyzer state is failed.

## 6. API / UI

- Public: `GET /api/v1/publications/{id}/anomaly-analysis` returns
  `publicationId`, `datasetRevision`, `analysisRevision`,
  `sourceDatasetRevision`, `analyzedAt`, `status` (pending/ready/partial/stale/
  failed), `sourceRevisionAt`, nullable `suspicionScore`, `overallSeverity`,
  `manualAssessmentPresent`, `affectedMetrics`, `activeFindingCount`, bounded
  `findings`, `nextCursor`, `methodologyVersion`, `disclaimer`. Findings expose
  origin, metric, detector metadata, score/severity, explanation code,
  intervals, snapshot refs, bounded evidence, quality/alternative codes and
  effective `reviewState`; never reviewer, private comment or errors.
- Admin: manual signal (origin `manual`, no detector score) and append-only
  review (`explained | unresolved | data_error | dismissed`); `dismissed` and
  `data_error` drop out of the active set and the public score.
- UI: block «Сигнал аномальной динамики» with heuristic strength (two decimals,
  no percent), severity, status, affected metrics, manual-assessment note,
  stale/pending/failed warnings, expandable findings and the mandatory
  disclaimer; chart/table boundary markers with textual equivalents; stale
  evidence uses timestamp intervals and never snaps to newer points.

## 7. Security

- `analytics_worker` login role: EXECUTE on the V31 worker functions only,
  no table DML on canonical/analysis tables, no `rebuild_core_projections`
  (asserted). `api_read`: SELECT on the two public views only; cannot execute
  claim/extraction/admin functions (asserted). `api_write_admin`: EXECUTE on the
  two command functions only (asserted for api_read/worker denial).
- Spring: route-level and `@PreAuthorize` ADMIN, CSRF, Basic, `Idempotency-Key`
  + SHA-256 request digest, correlation id, `Cache-Control: no-store`, admin
  RFC 9457 advice; VIEWER/EDITOR denied (test).
- Evidence: bounded JSON (≤ 8 KiB, ≤ 32 keys), stable codes only; failures
  persist a `[a-z0-9_]{1,64}` code; metrics labels come from packaged enums;
  tombstones carry hashes/versions, never findings or evidence.

## 8. Verification (exact commands, local macOS, PostgreSQL 18 in Docker)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_anomaly_analysis.py` | PASS — 19 passed |
| `MRANKED_ANOMALY_TEST_{ADMIN,WORKER,API,ADMIN_API}_DSN=…anomaly_it MRANKED_ANOMALY_PLAN_REPORT=… .venv/bin/python -m pytest -q tests/test_anomaly_analysis_postgres.py` | PASS — 11 passed (real roles, fresh Flyway V1–V31) |
| `.venv/bin/python -m pytest -q tests` | FAIL — 586 passed, 128 skipped (PostgreSQL/legacy-gated), 1 failed: pre-existing `test_rollback_ordering` (section 10) |
| `backend: ./mvnw -Pmigration-integration -Dtest='MigrationInstallationTest#cleanInstallationAndFrozenV8UpgradeHaveTheSameManifest' test` | PASS — clean install and V8→V31 upgrade manifests match |
| `backend: MRANKED_REHEARSAL_INSTALL_URL=…anomaly_it ./mvnw -Pmigration-integration -Dtest='MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` | PASS |
| `backend: MRANKED_ADMIN_TEST_POSTGRES_URL=…clean_it MRANKED_ANALYSIS_TEST_POSTGRES_URL=…anomaly_it MRANKED_TEST_REDIS_* … ./mvnw verify` | PASS — 230 tests, 0 failures, 29 skipped (env-gated), jar built (`target/m-ranked-backend-0.1.0-SNAPSHOT.jar`); re-run on the final V31 (attempt tombstones) with freshly re-provisioned `clean_it`/`upgrade_it` |
| `backend: ./mvnw -Dtest=JdbcAnalysisPostgresIntegrationTest test` (after the tombstone change) | PASS |
| `frontend: PATH=node@24 pnpm check` (lint, typecheck, `check:api` drift, unit, Playwright desktop+mobile, build, bundle budget) | PASS — 84 browser tests passed |
| `bash -n` on `cutover-preflight.sh`, `deploy-shadow.sh`, `restore-verify.sh`, `001-create-roles.sh`, `projection-publisher.sh` | PASS |
| `python -m migration.integration.run` | PASS — every stage `exit=0` on a fresh compose stack, including the `anomaly-postgres` stage |
| Query-plan / detector-bound rehearsal (`operations/performance/evidence/anomaly-v31-r1/`, local, gitignored) | PASS — extraction, state, review, claim and finding page plans use the intended indexes; 4096 points × 4 metrics × 3 detectors ≈ 0.22 s |
| `systemd-analyze verify`, backup/restore smoke (`restore-verify.sh` with pgBackRest), deploy-shadow/cutover-preflight dry runs | NOT RUN — Linux/production-host tooling; pins and syntax verified only |

## 9. Deviations from approved design

1. **Finding identity.** The design names a deterministic `findingKey`; the
   implementation stores `finding_key` (publication, origin, metric, detector,
   version, interval) plus a per-attempt row id derived in SQL. Public `id`
   values change when a new success re-fires the same signal, but the effective
   review decision follows the key. Reason: the previous success is pruned
   after the new one is inserted in the same transaction, so row ids must not
   collide; intent (stable reference, review continuity, safe pruning) is kept.
2. **Dormant V1 anomaly tables.** `analytics.anomaly_event` /
   `anomaly_review` were left untouched and new publication-level tables were
   added instead of altering them. Reason: the V1 tables are institution-
   oriented with different keys/enums; additive tables keep V1 semantics and
   grants intact while realising the approved run/attempt/state/finding/review
   model.
3. **Capability applicability.** Read from the seeded
   `analytics.platform_metric_capability` at extraction time (as of the pinned
   revision) instead of a code matrix; seeded data is the single source.
4. **Retry exhaustion.** Instead of a terminal "attempts exhausted" transition,
   retries continue with capped exponential backoff (`retry_count` ≤ 20,
   ≤ `ANOMALY_RETRY_MAX_SECONDS`); public status is already `failed`/`stale`.
   Bounded cost, simpler recovery when a transient cause disappears.
5. **Backfill rate limit.** Added operational `ANOMALY_BACKFILL_INTERVAL_SECONDS`
   (default 300) — operational configuration only; detector mathematics are
   unaffected.
6. **Test isolation.** Anomaly PostgreSQL fixtures (Python and Spring) run on a
   dedicated disposable `anomaly_it` database in the integration runner
   (`MRANKED_ANALYSIS_TEST_POSTGRES_URL`) because retained fixture revisions
   break the exact cleanup of catalog/admin integration tests on `clean_it`.
7. **Runner persistence flags.** `run.py` sets `COLLECTOR_PERSIST_RAW_EVIDENCE=true`
   (collectors stage) and `COLLECTOR_PERSIST_LEGACY_CSV=true` +
   `COLLECTOR_PERSIST_RAW_EVIDENCE=true` (Spring stage) for pre-existing
   fixtures (section 10); no architectural effect.
8. **Chart click handling.** `publication-measurements.tsx` replaces the
   Chart.js `onClick` with a canvas click listener mapping x to the nearest
   sampled row (Codex change while wiring evidence markers); keyboard, tooltip
   and table behaviour are covered by the existing Playwright suite.

## 10. Pre-existing issues (proven unrelated)

- `migration/integration/run.py` stage `collectors`
  (`tests/test_target_collectors_postgres.py::test_real_postgres_account_transaction_is_idempotent_and_atomic[*]`)
  failed with `raw_payload` lineage `0 == 2` on a pristine `git worktree` of
  `HEAD` against a fresh V1–V30 database, i.e. without V31 or any feature code.
  `PostgresCollectorRepository` only writes raw evidence when
  `COLLECTOR_PERSIST_RAW_EVIDENCE` is enabled and nothing in the runner or CI
  set it. By decision the runner now exports `COLLECTOR_PERSIST_RAW_EVIDENCE=true`
  for that stage only (local change to `run.py`; collector code and the test
  are untouched); with it the pristine test passes 4/4.
- Runner stage `spring`: `LegacyCsvPostgresIntegrationTest` and
  `LegacyCsvArchivePostgresIntegrationTest` failed because their Python fixture
  (`migration/integration/legacy_native_csv_fixture.py`) expects eight
  `analytics.legacy_native_export_lexeme` rows while the collector repository
  only writes lexemes when `COLLECTOR_PERSIST_LEGACY_CSV` is enabled. Both
  env-gated defaults were introduced in commit 33f6a11 (before this work);
  fixtures, collector package and the tests are unmodified. By decision `run.py`
  exports `COLLECTOR_PERSIST_LEGACY_CSV=true` and
  `COLLECTOR_PERSIST_RAW_EVIDENCE=true` for the Spring stage as well.

- `tests/test_rollback_ordering.py::test_rollback_freezes_writes_and_stops_every_target_writer_before_drain`
  fails identically on a pristine `git worktree` of `HEAD` (752f445) without
  any feature change; `operations/scripts/rollback.sh` is unmodified. Likely
  macOS `/bin/bash` 3.2 (`bash -p` harness) — not investigated further by
  decision. It is reached by the runner's `python` stage (full `pytest`), so
  the final local runner pass was executed with
  `PYTEST_ADDOPTS="--deselect tests/test_rollback_ordering.py::test_rollback_freezes_writes_and_stops_every_target_writer_before_drain"`
  exported for that run only; no code was changed for it.
- `operations/runbooks/DEPLOY.md` still says "Flyway source migrations V1–V29"
  in the release-directory list (stale before this work; left untouched).
- `.venv` shows as untracked because it is a symlink to
  `/private/tmp/mranked-anomaly-venv` (created by the previous session);
  `.gitignore`'s `.venv/` pattern only matches a directory.

## 11. Remaining issues

- Linux-only rehearsals (`systemd-analyze verify`, pgBackRest restore smoke,
  deploy-shadow/cutover-preflight dry runs) were not executed here; pins and
  syntax are updated and verified.
- Production-scale throughput, batch/concurrency thresholds and detector
  threshold calibration remain to be measured on production-like data, as the
  design itself states.

## Known issues and divergences

- `migration/schema/smoke.sql` used to contradict the grants the current schema
  ships; it was removed rather than repaired.
- `BackendConsistencyPostgresIntegrationTest#rebuiltOverviewKeepsTenViewsCandidatesAndOneRoundedReactionCandidate`
  fails on the final schema because `analytics.usable_publication_snapshot` no
  longer derives the overall snapshot quality from usable per-metric values. It
  is excluded from the integration runner and left for the schema owner.
- Production runs a hand-edited `analytics.rebuild_core_projections_v13` that
  empties `analytics.publication_history` and serves detail history from the
  ingest partitions on demand. The declarative `final-schema.sql` in this
  repository still rebuilds that projection, so the two differ. Anything reading
  publication history must run with `mranked.source-read.enabled=true`, as
  `operations/systemd/m-ranked-target-api-source.service` does.
- A publication whose only samples are newer than the last fully published
  revision is recorded as a failed analysis rather than a pending one, so the
  panel shows a technical error where there is simply no data yet. On a live
  database the next publication clears it; on a frozen copy it stays.

## Operating the worker

`operations/systemd/m-ranked-target-anomaly-analysis.service` runs
`python -m anomaly_analysis` against `ANOMALY_DATABASE_URL` as the
`analytics_worker` role. `operations/env/anomaly-analysis.env.example` lists
every knob. The worker is independent: it never blocks the publisher, and a
failure leaves the previously published findings in place.
