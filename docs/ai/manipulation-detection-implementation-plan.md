# Anomaly-dynamics implementation plan

This checklist implements the approved conversation specification against the
current `alpha` tree. Source code remains authoritative for existing details.

## Validated repository facts and adaptations

- Branch `alpha`; working tree was clean at the start of implementation.
- Source documents for the audit live beside this plan:
  `docs/ai/architecture-analysis.md` and `docs/ai/feature-analisys.md`.
- Originally Flyway ended at V30 and the feature shipped as additive V31. After
  the rebase onto `origin/alpha` 34291e9 (Flyway retired, one declarative
  `final-schema.sql` + guarded production transition) the same objects are
  delivered inside `final-schema.sql` and `transition-production-to-final.sql`
  under contract `storage-publisher-final-2026-09-08-r3`; see section 14.
- Publication snapshots are monthly partitioned, append-only facts. V9 suppresses
  exact replay in a `BEFORE INSERT` trigger and represents changed payloads as a
  higher `correction_sequence` with `created_at` and lineage.
- `analytics.usable_publication_snapshot` selects the current global correction
  tip. It cannot be used for a pinned historical revision because it can expose a
  later correction. V31 therefore adds a bounded as-of extraction function that
  selects the latest correction whose `created_at` is no later than the pinned
  dataset revision's `committed_at`.
- Dormant V1 anomaly tables are institution-oriented and do not model attempts,
  independent revisions, atomic current pointers, generated retention, or manual
  origin. V31 evolves them additively and supplies safe read/command functions.
- The core publication barrier is the projection set required by
  `projection-publisher.sh`, `JdbcDatasetRevisionProvider`, and readiness SQL.
  These files and the rebuild function remain unchanged.
- Spring uses package slices, `JdbcClient`, a separate configured admin JDBC
  context, RFC 9457 handlers, method security, CSRF, and no-store admin responses.
- Public Next reads use generated OpenAPI types. Publication history is separately
  loaded and charts sample to 144 points while preserving a selected point.
- Operations use hardened systemd units, environment files, a Prometheus textfile
  exporter, bounded labels, and a shell-driven release layout.

## 1. Semantics and contracts

- [x] **Validate current boundaries and write this plan.** Files/symbols:
  V1/V9/V12/V16/V30 migrations, collector repository insertion path, core
  projection checks, Spring query/admin slices, OpenAPI generator, publication
  detail/history loader, systemd/exporter. Depends on: none. Satisfies: source
  validation, branch safety, invariant baseline. Verification: repository reads,
  `git status`, branch check.
- [x] **Define stable public/internal enums and version identities.** Files:
  `anomaly_analysis/domain.py`, `config.py`, OpenAPI schemas, Spring analysis
  domain. Symbols: outcome/status/origin/severity/review/quality codes. Depends
  on: validation. Satisfies: neutral semantics, NULL vs zero, version identity.
  Verification: Python/Java/OpenAPI tests.

## 2. Pure analytical domain and preprocessing

- [x] **Implement immutable UTC-aware history and observation model.** Files:
  `anomaly_analysis/domain.py`. Symbols: `PublicationHistory`,
  `MetricObservation`, `MetricSegment`. Depends on: semantic codes. Satisfies:
  canonical fact separation and preservation of quality, synthetic, interval,
  correction, and completeness semantics. Verification: domain unit tests.
- [x] **Implement deterministic bounded preprocessing.** Files:
  `anomaly_analysis/preprocessing.py`. Symbols: `prepare_metric`, robust
  median/MAD, linear fit, gap/coverage primitives. Depends on: domain. Satisfies:
  time normalization, reset/negative split, duplicate timestamp safety, input
  bounds, no mutation. Verification: focused and invariant tests.

## 3. Detectors, registry, aggregation

- [x] **Implement explicit detector protocol and typed packaged configuration.**
  Files: `anomaly_analysis/detectors/base.py`, `config.py`, `registry.py`.
  Symbols: `Detector`, `Finding`, `Clean`, `Abstained`, manifest hash. Depends on:
  preprocessing. Satisfies: deterministic extensibility and startup validation.
  Verification: duplicate/config/hash/applicability tests.
- [x] **Implement delayed-spike detector.** Files:
  `anomaly_analysis/detectors/delayed_spike.py`. Depends on: detector protocol.
  Satisfies: plateau, rate, absolute/relative, quality/gap gates and interval
  evidence. Verification: positive/organic/uncertain/reset/sampling tests.
- [x] **Implement linear-growth detector.** Files:
  `anomaly_analysis/detectors/linear_growth.py`. Depends on: shared fit primitive.
  Satisfies: bounded early/delayed windows, non-flat and quality gates.
  Verification: early/delayed/noisy/rounded/density tests.
- [x] **Implement periodic-jump detector.** Files:
  `anomaly_analysis/detectors/periodic_jumps.py`. Depends on: jump primitives.
  Satisfies: repeated prominent interval-censored jumps and cadence confounding.
  Verification: periodic/irregular/single-jump/uncertain tests.
- [x] **Implement separately versioned max-score aggregator.** Files:
  `anomaly_analysis/aggregation.py`. Depends on: typed outcomes. Satisfies:
  clean=0, all-abstained=NULL, exception=failure, manual separation.
  Verification: aggregation tests.

## 4. Persistence and PostgreSQL contracts

- [x] **Add V31 analysis schema and seed metric capabilities.** File:
  `backend/src/main/resources/db/migration/V31__publication_anomaly_analysis.sql`.
  Symbols: candidate, analysis revision, attempt/state, evolved event/review,
  safe public views/functions, constraints/indexes/grants. Depends on: semantic
  contracts. Satisfies: independent derived state, retention, manual separation,
  Flyway ownership. Verification: migration and schema tests on PostgreSQL.
- [x] **Add exact-replay-safe dirty marker and bounded claim/lease functions.**
  File: V31. Symbols: AFTER INSERT marker, claim function. Depends on: schema.
  Satisfies: coalescing generations, concurrency, bounded collector transaction.
  Verification: replay/correction/concurrency/lease PostgreSQL tests.
- [x] **Add pinned-revision set-based as-of extraction.** File: V31 and
  `anomaly_analysis/postgres.py`. Depends on: schema. Satisfies: future-correction
  isolation, NULL/quality/lineage preservation, statement/input bounds.
  Verification: correction visibility and query-plan tests.
- [x] **Add atomic success/failure/manual/review publication functions.** File:
  V31. Depends on: attempt schema. Satisfies: no partial results, last success on
  failure, latest-success/latest-failure retention, idempotency, review audit.
  Verification: real PostgreSQL transition/permission tests.
- [x] **Provision `analytics_worker` least-privilege role.** Files:
  `infra/postgres/init/001-create-roles.sh`, compose/env examples, V31 grants.
  Depends on: SQL functions. Satisfies: dedicated runtime authority.
  Verification: role permission probes.

## 5. Worker orchestration

- [x] **Implement bounded coordinator and composition root.** Files:
  `anomaly_analysis/coordinator.py`, `postgres.py`, `metrics.py`, `__main__.py`.
  Symbols: latest fully published revision, batch claim/extract, input hash,
  preprocess-once, complete detector execution, atomic publish, retry/backoff.
  Depends on: Gate A and DB functions. Satisfies: independent multi-process
  worker, no HTTP/Redis/broker, failure isolation. Verification: worker unit and
  PostgreSQL integration tests.
- [x] **Implement adaptive eligibility and bounded config backfill.** Files:
  coordinator/config/postgres and V31. Depends on: candidate state. Satisfies:
  minimum age, fresh priority, bounded retries/backfill, no silent truncation.
  Verification: scheduling/backfill/new-generation tests.
- [x] **Implement deterministic input no-op.** Files: coordinator/domain/postgres.
  Depends on: extraction identity. Satisfies: no redundant attempts/revisions.
  Verification: unchanged/correction/config identity tests.

## 6. Independent publication and core isolation

- [x] **Verify public state transitions and core independence.** Files: V31 and
  tests only; do not modify core rebuild/publisher/revision/readiness. Depends on:
  persistence. Satisfies: independent analysis revision and core-projection
  barrier. Verification: broken-worker core publication regression test.

## 7. Spring and OpenAPI

- [x] **Specify public and two ADMIN endpoints OpenAPI-first.** Files:
  `contracts/openapi/m-ranked-v1.yaml`, contract tests. Depends on: DB public
  model. Satisfies: generated contract, bounded cursor/evidence and nullable
  score. Verification: OpenAPI tests and generator drift check.
- [x] **Implement `org.mranked.analysis` slice and JDBC safe reads.** Files:
  backend analysis domain/application/infrastructure/web packages. Symbols:
  analysis query service, cursor bound to analysis revision, ETag, public
  controller. Depends on: OpenAPI/DB. Satisfies: no request-time computation/raw
  scans and independent cache axis. Verification: unit/JDBC/controller/304 tests.
- [x] **Implement ADMIN-only manual signal and append-only review commands.**
  Files: analysis admin service/adapter/controller plus security/handler wiring.
  Depends on: DB commands. Satisfies: Basic+CSRF+Origin+ADMIN, idempotency/digest,
  audit, no-store, safe RFC 9457 errors. Verification: role/CSRF/idempotency tests.
- [x] **Update ArchitectureTest and regenerate TypeScript.** Depends on: Spring
  slice and OpenAPI. Satisfies: boundary enforcement and contract authority.
  Verification: Maven architecture/contract tests and `pnpm check:api`.

## 8. Frontend publication detail

- [x] **Load history and analysis independently in parallel with one bounded
  revision-race refetch.** Files: publication page, `detail-data.ts`, `api.ts`,
  generated types. Depends on: generated client. Satisfies: lag-safe independent
  resources. Verification: loader tests.
- [x] **Render accessible neutral anomaly block and evidence.** Files:
  `publication-detail.tsx`, new focused component/styles. Depends on: loader.
  Satisfies: neutral Russian terminology, score/status/manual distinction,
  disclaimer and bounded evidence. Verification: content/unit/browser/axe tests.
- [x] **Preserve all evidence boundaries during chart sampling.** Files:
  `history-data.ts`, `publication-measurements.tsx`. Depends on: analysis model.
  Satisfies: marker/band/text relationship and stale evidence safety.
  Verification: sampling/keyboard/screen-reader tests.

## 9. Operations and deployment

- [x] **Add hardened non-core worker service and environment wiring.** Files:
  `operations/systemd/m-ranked-target-anomaly-analysis.service`, target/env,
  deployment manifests/preflight/checksums. Depends on: runnable worker and role.
  Satisfies: restart/sandbox/credential limits without readiness dependency.
  Verification: unit syntax and operations tests.
- [x] **Add bounded metrics and alerts.** Files: analyzer metrics output,
  observability exporter/alerts/docs. Depends on: worker. Satisfies: backlog,
  lag, outcomes, leases, revisions, failures with bounded labels.
  Verification: exporter and alert-rule tests.
- [x] **Extend backup/restore/schema smoke.** Files: existing validation scripts.
  Depends on: V31. Satisfies: durable state lifecycle. Verification: smoke tests.

## 10. Integration and performance

- [x] **Extend authoritative integration runner.** File:
  `migration/integration/run.py` and focused fixtures. Depends on: all runtime
  boundaries. Satisfies: fresh Flyway, role, worker, reimport safety, core
  independence, API/frontend path. Verification: complete runner, no skipped PG.
- [x] **Add representative EXPLAIN/performance rehearsal.** Files: backend/test or
  migration rehearsal. Depends on: final queries/indexes. Satisfies: bounded
  claim/extraction/current read/pagination and no N+1. Verification: recorded
  accepted plans and large-series detector bound.

## 11. Convergence audit

- [x] **Audit every approved requirement and final diff.** File: this plan gains a
  requirement matrix/status appendix. Depends on: all stages. Satisfies: explicit
  convergence, drift/TODO/stub/disabled-test search. Verification: rerun affected
  gates after safe fixes.
- [x] **Run final layered gates and record exact outcomes.** Commands: focused and
  broad pytest, real PostgreSQL tests, Maven tests, OpenAPI drift, frontend check,
  integration runner, operations/query-plan/backup smoke. Depends on: audit.
  Satisfies: Definition of Done. Verification: exact command/result ledger.

## 12. Convergence audit ledger (2026-09-08)

Independent re-read of the approved analysis against the final diff. Defects
found and fixed in place (all verified by the layered gates listed in
`docs/ai/manipulation-detection-final-report.md`):

- [x] **Reviewed automatic findings blocked retention pruning.** The review
  table carried a hard FK to `publication_anomaly_finding`; the first success
  after an ADMIN review failed on the cascade delete. V31 now keys reviews by a
  stable `finding_key` (publication, origin, metric, detector, version,
  interval) with no FK, per-attempt row ids are derived in SQL, and the effective
  decision follows the key across attempts. Verified:
  `test_reviewed_automatic_finding_is_pruned_safely_and_keeps_effective_state_by_key`.
- [x] **Backfill seeding reset retry backoff and ran every poll.**
  `seed_anomaly_backfill` no longer touches existing candidates and skips
  publications without observations; the coordinator rate-limits seeding
  (`ANOMALY_BACKFILL_INTERVAL_SECONDS`). Verified:
  `test_backfill_seed_is_bounded_and_never_resets_existing_candidates`.
- [x] **`stale` never recovered on unchanged input.** `anomaly_input_is_unchanged`
  only short-circuits `ready`/`partial` states. Verified:
  `test_unchanged_input_never_shortcuts_a_stale_publication`.
- [x] **Public score ignored dismissed/data_error reviews.** The Spring read
  reports the maximum active automatic score (evaluated clean stays `0`,
  abstained/pending stays `null`). Verified: `JdbcAnalysisPostgresIntegrationTest`.
- [x] **Capability matrix duplicated in Python.** Extraction returns the seeded
  `analytics.platform_metric_capability` set as of the pinned revision; the
  coordinator evaluates only supported metrics. Verified: extraction and
  coordinator tests.
- [x] **Failure attempts recorded hard-coded semantic/capability versions.**
  Versions come from the loaded history; named defaults only when no history.
- [x] **Anomaly fixtures polluted `clean_it`.** The runner and the Spring adapter
  test use a dedicated disposable `anomaly_it`
  (`MRANKED_ANALYSIS_TEST_POSTGRES_URL`), so admin/catalog cleanup stays exact.
- [x] **Coverage gaps.** Added ADMIN-function denial for `api_read`/worker,
  extraction/state/review query-plan assertions with optional evidence export,
  a 4096-point detector bound test, Playwright coverage for VK/Rutube/MAX
  capability differences and an axe AA pass on the publication page.
- [x] **Pruned attempts left no audit trace.** `publish_anomaly_success/failure`
  now write a safe tombstone (`ops_and_admin.audit_log`, action
  `anomaly.attempt.prune`: attempt key, status, revision, hashes, versions,
  reason; never findings or evidence) before deleting the superseded slot.
  Verified: `test_reviewed_automatic_finding_is_pruned_safely_and_keeps_effective_state_by_key`.
- [x] **Runner blocked before the feature stages.** The pre-existing
  `collectors` stage needs `COLLECTOR_PERSIST_RAW_EVIDENCE=true`; `run.py` now
  sets it for that stage (proven unrelated on a pristine HEAD/V30 database).
- [x] **Release pins.** V31 sha256/Flyway checksum re-pinned in
  `cutover-preflight.sh`, `deploy-shadow.sh`, `restore-verify.sh` and
  `collector_parity_evidence.py`.

## 13. Requirement matrix (approved design §26 invariants and prompt §61 definition of done)

Status legend: V = implemented and verified (named gate), I = implemented but
not verified locally, N/A = not applicable.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | PostgreSQL canonical authority; Redis optional only | V | no Redis in `anomaly_analysis`; analysis endpoint outside `PublicDtoCache` (ArchitectureTest, controller test) |
| 2 | Raw observations immutable; judgments separate derived facts | V | V31 tables only; collector/V9 untouched; PG trigger test |
| 3 | Collectors do not run detectors / write results | V | `collector_target` unchanged (git diff empty); trigger writes marker only |
| 4 | Core publication and core projections independent | V | publisher/provider/rebuild unchanged; PG core-independence test |
| 5 | Fixed fully published `sourceDatasetRevision` | V | `pin_latest_anomaly_source_revision`; PG as-of test |
| 6 | Findings only from complete successful attempt; no partial set | V | coordinator exception → failure; PG staging invisibility |
| 7 | Public = last success; retained last success + last failure | V | PG retention test; tombstone audit |
| 8 | NULL ≠ 0; timestamp/quality/synthetic/uncertainty/correction semantics | V | preprocessing unit tests; extraction masks invalid/reset |
| 9 | Time-normalised rates; raw delta never sufficient | V | detector tests (density, duplicate, uncertain) |
| 10 | Detectors pure/deterministic, no I/O/clock | V | protocol + determinism/permutation tests; domain imports only stdlib |
| 11 | New detector = implementation + registry + tests | V | registry from manifest; typed configs |
| 12 | Versions/hashes recorded | V | attempt/state columns; manifest sha256 test |
| 13 | Score is heuristic, not probability | V | OpenAPI description, disclaimer, Playwright wording assertions |
| 14 | Abstention ≠ clean ≠ failure | V | aggregation + PG stale/failed tests; UI states |
| 15 | Manual/review ADMIN-only, append-only, audited, idempotent | V | security test, PG denial test, receipts, audit_log |
| 16 | Public API no on-demand analysis, no raw history | V | JDBC reads views only; ArchitectureTest web↛jdbc |
| 17 | All operations bounded | V | SQL bounds, WorkerConfig bounds, evidence caps, 4096-point test |
| 18 | Flyway owns DDL; least-privilege roles | V | V31 only; role probes in PG tests |
| 19 | OpenAPI contract; generated TS untouched | V | `pnpm check:api` drift gate; `OpenApiContractTest` |
| 20 | DB/API changes verified on real PostgreSQL + full runner | V | PG suites, `mvnw verify`, integration runner (see final report §8) |
| 21 | Legacy/bridge/reverse-sync/rating untouched | V | git diff empty for those trees |
| 22 | Logs/metrics/evidence free of secrets/payload/private comments | V | metrics label test; view excludes reviewer/comment; error codes only |
| DoD | Worker service wiring, env, role provisioning | V | unit parsed, `bash -n`, runner role checks; `systemd-analyze` NOT RUN (macOS) |
| DoD | Observability + alerts | V | exporter/alert diff; `test_operations_metrics_postgres` in runner |
| DoD | Frontend detail integration, sampling-safe evidence, neutral wording, axe | V | `pnpm check` (84 browser tests) |
| DoD | Query plans / performance rehearsal | V | `operations/performance/evidence/anomaly-v31-r1` (local) |
| DoD | Backup/restore smoke | I | `restore-verify.sh` pins updated, syntax-checked; pgBackRest run NOT RUN locally |

## 14. Rebase onto `origin/alpha` 34291e9 (2026-09-08)

- [x] **Rebase** `feature/anomaly-analysis` onto 34291e9 (four local `alpha`
  commits not in `origin/alpha` dropped by decision); conflicts in the
  publication page/API client, runner and Flyway-pinned operations scripts
  resolved by keeping upstream and re-applying the anomaly wiring.
- [x] **Schema delivery** through `final-schema.sql` (pg_dump regeneration,
  byte-identical to r2 + former V31) and the production transition (guarded by
  the `analytics_worker` role); contract id r3 re-pinned in 26 files; Flyway
  file and pins removed; `latest_fully_published_dataset_revision` mirrors the
  upstream seven-projection barrier.
- [x] **Upstream tests referencing the retired `migration` schema** rewritten to
  the final contract (`DetailPostgresIntegrationTest`,
  `HistoryReactionDetailsPostgresIntegrationTest`) by decision.
- [x] **Integration runner retargeted to the final contract** (retired
  migration/bridge/reverse stages removed, archive fixture seeded, Spring
  exclusions for retired-fixture suites, plans read from `anomaly_it`); full run
  green (21 stages).
- [x] **Documented upstream defects** (not fixed by decision):
  `BackendConsistencyPostgresIntegrationTest#rebuiltOverviewKeepsTenViewsCandidatesAndOneRoundedReactionCandidate`
  (final schema no longer derives overall snapshot quality from per-metric
  values) and `migration/schema/smoke.sql` (missing `recovery_policy` seed).

## 15. Rebase onto `origin/alpha` c29a8ad (2026-09-08)

- [x] **Rebase** `feature/anomaly-analysis` onto c29a8ad (64c8562 "serve
  production API from canonical sources" + c29a8ad "bound frontend and API
  resource usage"); replayed without conflicts, three files touched by both
  sides verified by hand (`final-schema.sql` keeps the eight new
  `GRANT … TO api_read` lines, `JdbcReadinessProbe` keeps the r3 contract on the
  projection branch, `publication-detail.tsx` keeps `prefetch={false}`).
- [x] **`ingest.reaction_breakdown` is now readable by `api_read`** (upstream
  source-read grant); the section-13 rewrite of
  `HistoryReactionDetailsPostgresIntegrationTest` denies only
  `ingest.raw_payload` and asserts the new grant positively.
- [x] **`QueryPlanEvidenceTest` privilege set corrected** for the same grant;
  the plan-shape assertion that public plans never scan `reaction_breakdown`
  is untouched.
- [x] **Stale-evidence banner guarded against source-backed revisions**: under
  `mranked.source-read.enabled` the dataset revision is an epoch-millis
  watermark, so `AnomalyAnalysis` skips the comparison instead of warning on
  every publication.
- [x] **Gates re-run on the new base**: `pytest tests anomaly_analysis`,
  `mvnw verify` (jar built), `pnpm check`, full integration runner.
- [x] **Newly stale upstream tooling documented, not fixed**:
  `migration/schema/smoke.sql` forbids the `ingest.collection_run` /
  `ingest.collection_account_result` reads that c29a8ad grants.

## 16. Rebase onto `alpha` b6a2875 (2026-09-11)

- [x] **Branch hygiene**: local `alpha` had diverged from `origin/alpha` (one
  local commit against five upstream ones), which made `git pull` refuse to
  reconcile. The two local source-read fixes were replayed on top of
  `origin/alpha`, `pull.rebase` is now set for this repository, and `beta` and
  `main` were reset to their remotes.
- [x] **Rebase** `feature/anomaly-analysis` onto that `alpha`; three conflicts
  (generated OpenAPI client, publication detail, publication measurements)
  resolved by keeping both sides and regenerating the client.
- [x] **Browser tests follow the canonical full-history link** introduced by
  35c1eb3 instead of the removed in-page button.
- [x] **Duplicate `.gitignore` rules dropped**; `alpha` already covers the local
  validation outputs.
- [x] **Schema merge verified value by value** (two-hour rebuild timeouts, the
  two functions upstream keeps at fifteen minutes, the transition script).
- [x] **Gates re-run on the new base**: `pytest tests anomaly_analysis`,
  `mvnw verify` (jar built), `pnpm check`, full integration runner.

## 17. Fixes found by the production-copy review (2026-09-12)

- [x] **Local stand on a restored production copy**: `infra/compose.prodcopy.yaml`,
  `infra/local/prodcopy.sh` and `infra/local/anomaly.Dockerfile`; the API runs in
  the source-read mode production uses, and the worker finally has a container in
  the local stand.
- [x] **Cumulative chart restored**: the local renderer folded a per-sample
  `pointRadius` array into `Math.max` and produced `NaN` geometry, so the line
  chart drew nothing. Per-sample radius, border width and the `rectRot` boundary
  diamond are now supported, with a browser test that fails without the fix.
- [x] **Reaction detail columns under source-read**: the ordered entries, delta
  entries and delta breakdown are derived from `ingest.reaction_breakdown`
  instead of being returned as `NULL`; covered by a new source-backed case in
  `HistoryReactionDetailsPostgresIntegrationTest`.
- [x] **Publication page 12 110 ms to 182 ms**: deltas come from `lag` over one
  extra fetched sample instead of a per-row lateral that re-entered every month
  partition, and `jit = off` is a role default for the read roles.
- [x] **Documented, not fixed**: production runs a hand-edited
  `analytics.rebuild_core_projections_v13` that empties
  `analytics.publication_history`; the repository schema still rebuilds it.
