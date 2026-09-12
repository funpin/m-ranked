# Contributing

## Layout

| Path | What lives there |
|---|---|
| `app/`, `collector_target/` | Python collectors and the Telegram/VK/MAX/Rutube adapters |
| `anomaly_analysis/` | The independent anomaly-dynamics worker |
| `backend/` | Spring Boot 4 API, and the declarative schema in `src/main/resources/db` |
| `frontend/` | Next.js application, its Playwright suite and the local chart renderer |
| `contracts/` | The OpenAPI specification and the generated client |
| `infra/` | Compose files and the local stand |
| `operations/` | systemd units, nginx configuration, deploy scripts, runbooks, SQL |
| `migration/` | The integration runner and the release manifest |
| `tests/` | Python tests for everything outside the frontend |
| `docs/` | Architecture, ADRs, database notes, feature documents |

## Toolchain

JDK 21, Node 24 with pnpm, Python 3.13 or newer, Docker. `make venv` builds the
Python environment; the frontend uses `pnpm install --frozen-lockfile`.

## Checks

`make test` runs the three fast suites. `make gates` adds the backend jar and the
full integration runner, which builds disposable PostgreSQL databases from
`backend/src/main/resources/db/final-schema.sql`. Everything must be green before
a change is pushed.

A change to `contracts/openapi/m-ranked-v1.yaml` must be followed by
`pnpm generate:api`; the contract test compares the checksum of the generated
client against the specification.

## Database

There are no incremental migrations. `final-schema.sql` is the single
declarative contract, and `ops_and_admin.schema_contract` carries its identifier,
which the readiness probe, the collectors and the publisher all validate. An
existing production database is moved forward by
`operations/sql/transition-production-to-final.sql`, applied through the cutover
procedure and never by application startup.

## Run artefacts

Reports, logs, screenshots and evidence from local runs stay out of the
repository; `.gitignore` enforces that. The only tracked evidence file is
`frontend/evidence/bundle-budget.json`, the budget `pnpm check:bundle` compares
the built bundle against.

## Branches and commits

`alpha` is the integration branch, `beta` and `main` follow it. Write commit
messages that say what changed and why, in prose, and keep a change reviewable:
one concern per commit.
