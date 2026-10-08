# Account Findings: shift, in-day regularity, night reactions, compare — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account-level findings that catch ЮЗГУ/Куинджи-style engagement (ER step without audience growth, in-day uniform reactions, night reactions) and surface findings on `/compare` with an exclusion toggle.

**Architecture:** Everything is computed by the nightly `account_tail_job` from per-post `tail_ledger` summaries (no raw reads). The ledger gains an hourly late-growth layout (v4; v3 stays readable). New kinds are added in `account_findings.py`, a migration widens the kind check, the compare dashboard API returns findings per institution, the frontend shows a badge and a toggle.

**Tech Stack:** Python 3 (numpy-free stdlib math in findings), PostgreSQL 18, FastAPI, Next.js/React + openapi-typescript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-10-08-account-cohort-anomaly-design.md`

## Global Constraints

- No server changes; all runs on local copy `mranked_prod_20261008`. Release only on explicit «делай».
- No addresses/ports/keys in the repo. No `Co-Authored-By: Claude` in commits.
- Findings are statistical unusualness vs the platform cohort, never a claim of fraud (ADR-006); every kind has alternatives text.
- Post levels are unchanged by account findings.
- Thresholds (verbatim from spec): shift `ratio ≥ 2`, `separation ≥ 0,8`, `0,5 ≤ viewsRatio ≤ 2`, before-median R72 ≥ 5, before ≥ 12 posts in 14 d, after ≥ 8 posts in 10 d; status 2: `separation ≥ 0,9` and last-7-days ER ≥ 1,5 × before. Corroboration: same institution, best cut within ±3 d, `ratio ≥ 1,5`.
- In-day regularity: days with ≥ 3 posts, ≥ 8 such days, median R72 ≥ 20, `min(extra, dayExtra) ≤ 0,08`; status 2 also on sub-Poisson χ² below the 1st percentile.
- Night: hourly ΔV/ΔR for ages 24 h–14 d from exact neighbouring points ≤ 1 h apart; audience night = 6 consecutive hours with least ΔV; abstain if ΔV share there > 12 %; finding: ΣΔR ≥ 200, night ΔR share ≥ 10 % and ≥ 4 × night ΔV share; status 2 in both halves; members night ΔR ≥ 5; note when shifted > 2 h from 01–07 МСК.
- Compare toggle default off, in URL; criterion — status 2 on the selected platform (any platform in «all»); hidden with `ANOMALY_REPORT_VISIBLE=false`.

## Review Focus

- Mixed ledger versions during rollout (v3 rows with no `hours`): findings must still be computed for A/B and night must simply see fewer posts, never crash. → test in Task 1.
- Account with a single post per day: in-day measure must abstain (fall back to window measure), not divide by zero. → test in Task 2.
- Views collapsing (ER rises because V falls ×10): must not become a shift finding. → test in Task 3.
- Account with no diurnal trough (views flat around the clock): night must abstain. → test in Task 4.
- Institution with findings only on another platform than the one selected on `/compare`: toggle must not hide it. → test in Task 6 (frontend unit test).

---

### Task 1: Tail ledger v4 — hourly late growth

**Files:**
- Modify: `anomaly_analysis/v2/tail_ledger.py`
- Modify: `anomaly_analysis/v2/store.py` (ledger readers accept versions 3 and 4)
- Test: `tests/test_tail_ledger.py`

**Interfaces:**
- Produces: `VERSION = 4`; `READABLE_VERSIONS = (3, 4)`; `TailLedger.hours: tuple[tuple[int, ...], tuple[int, ...]] | None` — `(views[24], reactions[24])` by UTC hour of the later reading; payload key `"hours": [[...24], [...24]]`; `ledger_from_payload` accepts v3 (hours None) and v4.
- Constants: `HOURLY_FROM = DAY`, `HOURLY_UNTIL = LATE_UNTIL`, `HOURLY_MAX_GAP = HOUR`.

- [ ] Write failing tests: hourly layout sums ΔV/ΔR into the UTC hour of the later point; pairs > 1 h apart skipped; decreases clipped to 0; points < 24 h ignored; rounded/uncertain readings excluded; v3 payload still parses with `hours is None`; reposts get no hours.
- [ ] Implement `_hours(points)` over exact joint points and wire into `build_ledger` / `payload` / `ledger_from_payload`.
- [ ] Store: `tail_ledger_version = ANY(%s)` with `list(READABLE_VERSIONS)` in `read_tail_ledgers` and `read_finding_ledgers`; worker staleness unchanged (`!= VERSION`, so v3 rows are recomputed).
- [ ] Run `pytest tests/test_tail_ledger.py tests/test_account_tail.py tests/test_account_findings.py -q`; commit.

### Task 2: `regular_reactions` — in-day spread and sub-Poisson

**Files:**
- Modify: `anomaly_analysis/v2/account_findings.py` (`_regular_stats`, findings branch, texts)
- Test: `tests/test_account_findings.py`

**Interfaces:**
- Produces in `_regular_stats` result: `dayExtra: float | None`, `days: int`, `measure: "window" | "day"`, `chi2: float | None`, `chi2Df: int | None`, `subPoisson: bool`.
- Constants: `REGULAR_DAY_MIN_POSTS = 3`, `REGULAR_MIN_DAYS = 8`, `SUBPOISSON_Z = -2.326`.

Day residuals: for each Moscow day with ≥ 3 posts, `log R − log median_day`; `Var_pool = Σ resid² / Σ(n_d − 1)`; `dayExtra = sqrt(max(Var_pool − mean(1/R), 0))`. χ² = Σ_d Σ (R − m_d)² / m_d with m_d the day mean, df = Σ(n_d − 1); critical value by Wilson–Hilferty `df·(1 − 2/(9df) + z·sqrt(2/(9df)))³`.

- [ ] Failing tests: (a) account whose daily level steps from 95 to 250 but posts in a day are Poisson around the day level → found, `measure == "day"`; (b) sub-Poisson posts (constant ±2) → status 2 and `subPoisson`; (c) one post per day → `dayExtra is None`, falls back to window measure; (d) organic cohort not found.
- [ ] Implement; summary text says which measure fired and names sub-Poisson explicitly.
- [ ] Run tests; commit.

### Task 3: `engagement_shift` with corroboration

**Files:**
- Modify: `anomaly_analysis/v2/account_findings.py`, `anomaly_analysis/account_tail_job.py`, `anomaly_analysis/v2/store.py` (`read_finding_ledgers` returns `institution_id`)
- Test: `tests/test_account_findings.py`

**Interfaces:**
- `LedgerPost.institution_id: UUID | None = None` (new last field with default).
- `_shift_stats(items) -> dict | None` with keys `cut` (ISO date), `ratio`, `separation`, `viewsRatio`, `erBefore`, `erAfter`, `erRecent`, `before`, `after`, `medianReactionsBefore`, `medianReactionsAfter`, `members`.
- Finding metrics add `corroboration: [{platform, ratio, cut}]`.

- [ ] Failing tests: step ×2,5 with flat views → status 2 with members; step that fades in the last week → status 1; views ÷10 → no finding; smooth gradual growth ×1,5 → none; same institution on VK with step ±2 d → corroboration listed; another institution → not listed.
- [ ] Implement cut scan over Moscow dates, texts (title «Отклик вырос без роста аудитории», alternatives from spec), figure (`ratio` vs cohort median of best ratios, `times`, `higher`).
- [ ] Job + store pass `institution_id`; run tests; commit.

### Task 4: `night_reactions`

**Files:**
- Modify: `anomaly_analysis/v2/account_findings.py`
- Test: `tests/test_account_findings.py`

**Interfaces:**
- `_night_stats(items) -> dict | None`: `nightStartUtc`, `nightStartMsk`, `shiftHours`, `viewShare`, `reactionShare`, `reactions`, `views`, `posts`, `halves`, `abstain` (`"no_trough"`), `members`.

- [ ] Failing tests: Moscow audience with 35 % night reactions → found status 2; same pattern shifted +6 h (Irkutsk audience) with reactions following views → none; flat views around the clock → none (abstain); night reactions only in one half → status 1; posts without hours (v3) ignored.
- [ ] Implement, texts with night window in МСК and the timezone note.
- [ ] Run tests; commit.

### Task 5: Migration, contract, account card

**Files:**
- Create: `db/migrations/0075_account_finding_kinds.sql`
- Modify: `anomaly_analysis/v2/account_findings.py` (`METHOD_VERSION = "account-findings-v3"`), `contracts/openapi/m-ranked-v1.yaml` (kind enum, `maxItems: 7`), regenerated `contracts/openapi/m-ranked-v1-client.ts` + `frontend/lib/api-reference.generated.json`, `frontend/components/account-analysis-card.tsx` (icons `ArrowUpFromLine`, `Moon`).
- [ ] Write migration (same shape as 0074); apply to local copy; `npm run generate:api`; `npm run typecheck`; commit.

### Task 6: Findings on `/compare`

**Files:**
- Modify: `api/sql/compare.py` (`DASHBOARD_FINDINGS`), `api/routes/compare.py` (`dashboard_body(..., findings=())`), `contracts/openapi/m-ranked-v1.yaml` (`institutions[].accountFindings`), `frontend/lib/compare-dashboard.ts` (`InstitutionRow.findings`, `hasPersistentFinding(row, platform)`), `frontend/components/compare/compare-dashboard.tsx` (badge, toggle `?clean=1`).
- Test: `tests/test_compare_dashboard_postgres.py` or unit test of `dashboard_body`; `frontend/tests/compare-dashboard.test.ts`.

- [ ] Failing tests: `dashboard_body` attaches `accountFindings` per institution; frontend `hasPersistentFinding` true only for status 2 on the selected platform (any in «all»); toggle filters rows.
- [ ] Implement SQL (visible enabled accounts joined to findings, grouped by institution), body, schema, UI; hide when anomaly report is not visible.
- [ ] Run pytest + vitest + typecheck; commit.

### Task 7: Local calibration and docs

- [ ] Recompute ledgers on local copy (`python -m anomaly_analysis.backfill --days 35` against local DSN, worker logic only), run `account_tail_job` against local DB; list findings by kind/platform.
- [ ] Adjust thresholds only if the list shows obvious false positives; record calibration numbers in module docstring.
- [ ] Update `docs/features/anomaly-analysis.md`, ADR-017 table, runbook section «account-findings-v3» (migration 0075 → release → backfill → tail job → checks; rollback); commit.
