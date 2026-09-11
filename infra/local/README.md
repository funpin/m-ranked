# Local stand

The local stand contains PostgreSQL 18, FastAPI and Next.js; it has no Redis,
Java runtime or legacy importer.

```bash
make stand
# open http://localhost:3000
```

By default Compose reads the non-production template
`infra/local/compose.env.example`. To use private local values, copy it to an
ignored `.env` file and run:

```bash
MRANKED_COMPOSE_ENV=/absolute/path/local.env make stand
```

A new PostgreSQL volume is bootstrapped from `db/migrations/*.sql`. Existing
volumes are left intact by `make stand-down`; remove a local volume only when
you intentionally want an empty database.
