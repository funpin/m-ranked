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
