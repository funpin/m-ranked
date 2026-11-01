# Contributing

## Layout

| Path | Content |
|---|---|
| `api/` | FastAPI public/admin API |
| `collector_target/` | PostgreSQL ingestion pipeline |
| `collector_runtime/` | provider clients and parsers used by collectors |
| `anomaly_analysis/` | anomaly worker |
| `db/migrations/` | ordered declarative PostgreSQL bootstrap |
| `frontend/` | Next.js application and browser tests |
| `contracts/` | frozen OpenAPI specification and generated client |
| `infra/` | Compose and local images |
| `operations/` | systemd units, backup, maintenance and runbooks |
| `tests/` | Python unit, contract and PostgreSQL tests |

## Toolchain and gates

Use Python 3.13+, Node 24 with pnpm, and Docker:

```bash
make venv
make test
```

A change to `contracts/openapi/m-ranked-v1.yaml` must be followed by
`cd frontend && pnpm generate:api`. The generated client checksum is enforced.

PostgreSQL is bootstrapped by applying `db/migrations/*.sql` in lexical order.
Applications never run DDL at startup. `ops_and_admin.schema_contract` must
contain `live-read-2026-09-13`.

Files ending in `.env.example` are templates and may be tracked. Real `.env`
files, private keys, dumps, SQLite files and provider sessions must never be
committed; `tests/test_repository_hygiene.py` enforces this.

Commits should explain why a change exists and keep one coherent concern.

## Branches and pull requests

```
<type>/<task>  ──PR, squash──▶  develop  ──PR «release: vYYYY.M.N», merge──▶  main
                                                     │
                                  Release: tag, GitHub Release, artifact
                                                     │
                                  Deploy: approval in «production» → Server 2
```

- **`main`** — production. Accepts PRs only from `develop`, titled
  `release: vYYYY.M.N`, with one approval and a merge commit, so `develop`
  and `main` keep one history.
- **`develop`** — integration, the default branch. Accepts PRs only from task
  branches `<type>/<name>` (`feat fix perf refactor docs test ci build chore
  deps data revert`, plus `dependabot/*`), squash-merged.
- Direct pushes, force pushes and deletion of either branch are blocked by
  rulesets; `v*` tags cannot be moved or deleted.
- PR titles follow Conventional Commits: they become the squash commit and
  the release notes.

The ruleset cannot say *from which* branch a PR may come, so
`.github/workflows/policy.yml` checks it. A PR could edit that check, or any
workflow, to judge itself more leniently, so `.github/`, `operations/deploy/`
and `operations/github/` are listed in `.github/CODEOWNERS` and both rulesets
require code-owner approval for them; ordinary task PRs need no review.
(`pull_request_target` is not an option: it always runs the default branch's
workflow, and GitHub disables it for public repositories by default.)

## Checks

Each protected branch requires one aggregate check; the list of jobs behind
it changes in the workflow, not in the repository settings.

| Check | Workflow | Runs on | Contents |
|---|---|---|---|
| `branch-policy` | `policy.yml` | every PR | source/target branch and title |
| `develop-gate` | `ci.yml` | PRs into `develop` and `main`, pushes | schema and migrations on PostgreSQL, all Python tests, frontend lint/types/unit/build, secrets in new commits |
| `release-gate` | `release-gates.yml` | PRs into `main`, pushes to `main`, nightly, manual | browser e2e and the packaged site, Python 3.11 production environments, built images with Trivy, dependency audit, SAST, secrets across history, SBOM |

The two tiers are separate workflows on purpose: GitHub counts a skipped job
as passed, so a light run must never be able to satisfy the release check.
The nightly `release-gates` run on `develop` surfaces new CVEs before a
release PR is blocked by them.

## Releases and deployment

1. When `develop` is ready, open `develop → main` titled `release: vYYYY.M.N`
   (the next version after the latest tag; N counts from 0 within the month).
2. Merging it runs `release.yml`: the version comes from the PR title, the
   artifact is the commit tree plus the standalone site built in the
   production Node image, with build provenance; then the tag and the GitHub
   Release with generated notes.
3. `deploy.yml` waits for a reviewer in the `production` environment, checks
   the provenance and SHA-256, and calls `deploy-release` on Server 2 through a
   forced SSH command. The server script refuses, before switching, a release
   with unapplied migrations or changed systemd/nginx/env files unless the
   run says they were reviewed (`apply_migrations`, `config_reviewed`); after
   switching it checks health and the new build id and rolls back on failure.
4. Rollback: run `Deploy` with the previous version. Migrations are never
   rolled back, so they must be expand-only: the previous code keeps working
   on the new schema. A migration that needs manual steps carries a line
   `-- deploy: manual` and is applied by the operator per
   `operations/runbooks/DEPLOY.md`.

Server 1 (collectors) is still deployed by hand per `DEPLOY.md`.
One-time setup: `operations/github/setup-repository.sh` (rulesets, default
branch, `production` environment; needs admin) and
`operations/deploy/README.md` (server user, forced command, secrets).
