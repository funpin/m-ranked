# V5 positive UI/API rehearsal verification

Verified on 2026-09-03 against the local PostgreSQL 18.6 container. The only
database dropped and recreated was the explicitly disposable
`mranked_ui_rehearsal`; `mranked` and every other database were left intact.

## Clean migration result

The packaged Spring application and the repository source contained identical
V1--V5 migration bytes. Starting that JAR against the empty rehearsal database
reported:

```text
Successfully validated 5 migrations
Current version of schema "flyway": << Empty Schema >>
Successfully applied 5 migrations to schema "flyway", now at version v5
```

The resulting exact history was:

| Rank | Version | Description | Type | Flyway checksum | Installed by | Success | Source SHA-256 |
| ---: | ---: | --- | --- | ---: | --- | --- | --- |
| 1 | 1 | target baseline | SQL | `-1636077697` | `migration_owner` | true | `dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1` |
| 2 | 2 | rebuild core projections | SQL | `839607018` | `migration_owner` | true | `113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd` |
| 3 | 3 | collector observation times and identity grants | SQL | `-1456658399` | `migration_owner` | true | `5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1` |
| 4 | 4 | admin collection run status grants | SQL | `1318350062` | `migration_owner` | true | `d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82` |
| 5 | 5 | legacy activity period projection | SQL | `-1313754193` | `migration_owner` | true | `d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41` |

The fixture preflight now checks this complete matrix, including the exact row
count, descriptions, type, checksums, installer and success status. It also
proved that `api_write_admin` may execute the V5 wrapper while
`api_write_admin`, `migration_bridge` and `maintenance` cannot execute the
private retained `rebuild_core_projections_v2(bigint)` implementation.

## Fixture and replay result

`002-positive-ui-fixture.sql` completed twice with `ON_ERROR_STOP=1`. Each pass
invoked the projection publisher twice and compared normalized V5 period rows.
Both calls returned `institution_period_semantics_version = 2` and exactly 128
period rows. On the second full fixture pass, all source and rating INSERTs
reported `INSERT 0 0`, while output remained:

```text
comparison: revision 9003001, 2 institutions, 50 reaction-median points,
            hour offsets 0 through 24
rating:     910001 / Альфа Институт / rank 1 / 87.50 / exact
            910002 / Бета Академия  / rank 2 / 72.25 / exact
period 1d:  910001 / channel 920001 / reactions 115 / sample 1 / coverage 1
            910002 / channel 920002 / reactions 69  / sample 1 / coverage 1
```

The 64 all-platform period rows all have NULL values, sample size `0`, coverage
`0.25` and quality `unknown`, matching the V5 coverage-only contract.

## Shared verification scripts

Both repository checks passed against the populated rehearsal database:

```text
M-Ranked PostgreSQL 18.6 schema smoke assertions passed.
M-Ranked V5 period activity golden assertions passed.
```

Both scripts rolled their writes back. The final audit found no golden-fixture
institutions and retained the following persistent state:

| Item | Value |
| --- | ---: |
| Dataset revision | `9003001` |
| Institutions / accounts / publications | `2 / 2 / 2` |
| Publication snapshots | `50` |
| Rating results | `2` |
| Publication latest / hourly | `2 / 50` |
| Daily / monthly / period rows | `32 / 32 / 128` |
| Comparison projection rows | `784` |
| Ready projection states | `6` |

An `api_read` connection independently observed revision `9003001`, all 128
period rows, and 50 selected 24-hour comparison points for institutions
`910001` and `910002`.

## Commands used

The clean run used only the guarded database creation script, the packaged
Spring/Flyway application, the deterministic fixture and the shared rollback-
only checks:

```bash
rtk docker exec -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 dropdb --host 127.0.0.1 \
  --username mranked_bootstrap --if-exists --force mranked_ui_rehearsal

rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql --host 127.0.0.1 \
  --username mranked_bootstrap --dbname postgres --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/rehearsal/001-create-database.sql

rtk env \
  SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:55433/mranked_ui_rehearsal \
  SPRING_DATASOURCE_USERNAME=api_read \
  SPRING_DATASOURCE_PASSWORD="$API_READ_DB_PASSWORD" \
  SPRING_FLYWAY_URL=jdbc:postgresql://127.0.0.1:55433/mranked_ui_rehearsal \
  SPRING_FLYWAY_USER=migration_owner \
  SPRING_FLYWAY_PASSWORD="$MIGRATION_DB_PASSWORD" \
  SPRING_FLYWAY_DEFAULT_SCHEMA=flyway SPRING_FLYWAY_SCHEMAS=flyway \
  MRANKED_CACHE_REDIS_ENABLED=false SERVER_PORT=0 \
  java -jar backend/target/m-ranked-backend-0.1.0-SNAPSHOT.jar

rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql --host 127.0.0.1 \
  --username mranked_bootstrap --dbname mranked_ui_rehearsal --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/rehearsal/002-positive-ui-fixture.sql

# The preceding fixture command was executed a second time for replay proof.
# The same psql form then ran migration/schema/smoke.sql and
# migration/schema/period-activity-golden.sql.
```

## Stable IDs for final API/browser QA

| Kind | Alpha | Beta |
| --- | ---: | ---: |
| Institution | `910001` | `910002` |
| Channel | `920001` | `920002` |
| Platform account | `930001` | `930002` |
| Post | `940001` | `940002` |
| Platform post | `950001` | `950002` |

Use revision `9003001`, `/channels/920001`, `/channels/920002`, and repeated
comparison parameters `channels=920001&channels=920002` for the final
target API and browser checks.
