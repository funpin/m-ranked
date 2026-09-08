# Final database schema verification

The repository supports one database contract:
`storage-publisher-final-2026-09-08-r3`.

For a new database, provision roles with
`infra/postgres/init/001-create-roles.sh` and apply
`backend/src/main/resources/db/final-schema.sql` exactly once. Docker Compose
does this through `/docker-entrypoint-initdb.d/002-final-schema.sql` on an empty
PostgreSQL volume. There is no Flyway schema and no ordered migration chain.

For the existing production database, use only
`operations/sql/transition-production-to-final.sql` under the separately
approved database cutover procedure. The transition validates the observed
source objects, executes atomically and refuses an unknown or already-final
database. Normal deploys and application processes never execute schema DDL.

Every database-dependent process validates the same contract before work:

```sql
SELECT contract_id
FROM ops_and_admin.schema_contract;
```

The only accepted value is `storage-publisher-final-2026-09-08-r3`. The API checks
it as part of readiness; collectors, the explicit Publisher and the outbox
worker fail closed before processing.

## Local bootstrap

Copy `infra/postgres/compose.env.example` to a private environment file, replace
all secrets, then start the dependencies:

```bash
rtk docker compose --env-file /private/path/m-ranked-compose.env \
  -f infra/compose.yaml up -d postgres redis
```

Verify that the final contract exists and retired schemas do not:

```sql
SELECT contract_id FROM ops_and_admin.schema_contract;
SELECT to_regnamespace('flyway'), to_regnamespace('migration');
```

The first query must return the exact contract above. Both values in the second
query must be `NULL` on a fresh database.

## Structural and semantic checks

Run the structural, privilege, partition and rollback-only data smoke checks as
the local bootstrap user:

```bash
PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/smoke.sql
```

Run the rollback-only activity and comparison fixtures against the same schema:

```bash
PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/period-activity-golden.sql

PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" rtk psql \
  --host 127.0.0.1 --port "${POSTGRES_PORT:-5432}" \
  --username mranked_bootstrap --dbname mranked \
  --file migration/schema/comparison-golden.sql
```

These fixtures validate projection semantics and least-privilege boundaries;
they roll back their data.

## Runtime publication contract

Collectors write canonical catalog/ingest facts and an idempotent
`projection.rebuild.requested` event. They do not start or require the
Publisher. The Publisher is an explicit bounded oneshot that coalesces requests
to a high-water mark and publishes the seven serving projections, including
`publication_history`. A previously
valid generation remains readable while raw ingestion advances.

The cache outbox worker does not claim projection-control events. After a
successful publication it delivers cache-invalidation events such as
`dataset.revision.changed` to Redis.

The two dominant append-only metric families use monthly partitions. Collector
imports call `ops_and_admin.ensure_publication_metric_partition(...)` before a
month batch. The default partition is a safety net, not an archival unit.
Partition drops and raw-payload purges remain separate, explicitly approved
maintenance operations and are not part of schema installation.
