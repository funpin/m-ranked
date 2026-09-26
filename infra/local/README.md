# Local stand

The local stand contains PostgreSQL 18, FastAPI and Next.js; it has no Redis,
Java runtime or legacy importer.

```bash
make stand
# Open the loopback web port declared in infra/compose.local.yaml.
```

On an ARM Mac, the checked-in Python wheel hashes target Linux x86_64. Use
`DOCKER_DEFAULT_PLATFORM=linux/amd64 make stand` so Docker Desktop builds the
local API and web images under emulation. `make stand` then starts the stack
without that platform override, so PostgreSQL can use its native ARM image.
This does not change the production hosts.

By default Compose reads the non-production template
`infra/local/compose.env.example`. To use private local values, copy it to an
ignored `.env` file and run:

```bash
MRANKED_COMPOSE_ENV=/absolute/path/local.env make stand
```

To compare the current UI against **public live data** without copying the
production database, use an operator-managed, read-only tunnel. Keep the
connection details and its local URL in private operator notes or an ignored
local environment file; never commit them to this public repository. Then run:

```bash
MRANKED_COMPOSE_PROJECT=mranked-current \
MRANKED_LOCAL_PUBLIC_API_BASE_URL="$MRANKED_OPERATOR_PUBLIC_READ_URL" \
DOCKER_DEFAULT_PLATFORM=linux/amd64 make stand
```

Only public GET endpoints are used by the public page client. `API_BASE_URL`
continues to point at the disposable local API for the admin panel; the local
admin cannot modify production. This mode depends on the tunnel and is not an
offline database copy. Stop the previous project before using the same ports.
To stop this isolated stack while preserving its volume, run
`MRANKED_COMPOSE_PROJECT=mranked-current make stand-down`.

A new PostgreSQL volume is bootstrapped from `db/migrations/*.sql`. Existing
volumes are left intact by `make stand-down`; remove a local volume only when
you intentionally want an empty database.

The local web stand uses HTTP on a loopback port. Its CSP must not include
`upgrade-insecure-requests` on this origin: Safari otherwise upgrades CSS and
JavaScript to HTTPS and renders an unstyled page. The directive remains enabled
when the browser reaches the production site through HTTPS.

An empty local database has no dataset revision, so `/api/v1/health/ready`
returns `DOWN` until a fixture or collector creates the first revision. The
web process and `/api/v1/health/live` can still be healthy. For a schema-only
local review, insert a single `migration` revision in the disposable local
database; this does not copy any production publications.
