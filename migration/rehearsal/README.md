# Positive target UI/API rehearsal

The latest executed evidence is in `V5-verification-report.md`.

This fixture exists only to exercise a non-empty target comparison curve and a
published rating result without changing `mranked` or
`mranked_bridge_v3_verify`.  Both SQL files fail closed on the exact database
name.  Database creation is one-shot and never replaces an existing database.
The data fixture is deterministic and may be replayed only while the dedicated
database contains no source rows other than its fixed fixture IDs.

The fixed clock is `2026-09-03T12:05:00Z`, the fixed dataset revision is
`9003001`, and each of two Telegram institutions has one complete publication
with 25 exact hourly points from hour 0 through hour 24.  The expected complete
24-hour reaction-median cohort has two members and 50 points.  The published
`m-ranked-rehearsal` rating has two positive, ranked results. Under V5's
open-left `(window_start, window_end]` activity semantics, the 1-day Telegram
reaction sums/medians are `115` for Alpha and `69` for Beta; each has sample
size `1` and coverage `1`. The two all-platform dimensions are coverage-only:
their metric values are NULL, sample size is `0`, and coverage is `0.25`.

## Create and migrate

Against the local `mranked-flyway-it-postgres-1` container:

```bash
rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql \
  --username mranked_bootstrap --dbname postgres --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/rehearsal/001-create-database.sql
```

Apply the repository's Flyway V1 through V5 migrations as
`migration_owner`.  One convenient local path is to start the packaged Spring
application against `jdbc:postgresql://127.0.0.1:55433/mranked_ui_rehearsal`
with its normal Flyway credentials, wait for Flyway to report schema version 5,
then stop it before loading the fixture.  The fixture accepts exactly the five
successful rows below and rejects a missing, failed, extra, renamed, differently
owned, or checksum-mismatched migration. It also verifies V4's narrow run-status
reads and V5's public-wrapper/private-V2 publisher boundary.

| Version | Flyway checksum | Source SHA-256 |
| --- | ---: | --- |
| V1 | `-1636077697` | `dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1` |
| V2 | `839607018` | `113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd` |
| V3 | `-1456658399` | `5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1` |
| V4 | `1318350062` | `d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82` |
| V5 | `-1313754193` | `d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41` |

## Load and self-verify

```bash
rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql \
  --username mranked_bootstrap --dbname mranked_ui_rehearsal --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/rehearsal/002-positive-ui-fixture.sql
```

The script commits only after checking the source-row counts, all six ready
projection states, V5's 128 period rows and exact 1-day values, the
coverage-only all-platform contract, the complete comparison cohort and its
hour-24 value, and the exact public rating signature. It rebuilds the full
projection set twice and compares normalized period output, including V5's
`institution_period_semantics_version = 2`. It ends by printing compact JSON
summaries.

Replay the same command once more as an explicit whole-fixture idempotence
proof. Every source INSERT must report `INSERT 0 0`, while the three JSON
summaries remain unchanged.

Run the shared rollback-only checks against the populated rehearsal database:

```bash
rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql \
  --username mranked_bootstrap --dbname mranked_ui_rehearsal --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/schema/smoke.sql

rtk docker exec -i -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" \
  mranked-flyway-it-postgres-1 psql \
  --username mranked_bootstrap --dbname mranked_ui_rehearsal --no-psqlrc \
  --set ON_ERROR_STOP=1 < migration/schema/period-activity-golden.sql
```

Both scripts roll back their fixture writes. The final persistent revision must
therefore remain `9003001`.

## Stable UI identifiers

| Entity | Alpha | Beta |
| --- | ---: | ---: |
| Institution legacy ID | `910001` | `910002` |
| Channel legacy ID | `920001` | `920002` |
| Platform-account legacy ID | `930001` | `930002` |
| Post legacy ID | `940001` | `940002` |
| Platform-post legacy ID | `950001` | `950002` |

The target channel detail routes for browser QA are `/channels/920001` and
`/channels/920002`. The exact comparison selection is
`channels=920001&channels=920002`.

## Spring/API rehearsal connection

Use these local values for a separate Spring process (for example port `18082`):

```text
SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:55433/mranked_ui_rehearsal
SPRING_DATASOURCE_USERNAME=api_read
SPRING_DATASOURCE_PASSWORD=$API_READ_DB_PASSWORD
SPRING_FLYWAY_URL=jdbc:postgresql://127.0.0.1:55433/mranked_ui_rehearsal
SPRING_FLYWAY_USER=migration_owner
SPRING_FLYWAY_PASSWORD=$MIGRATION_DB_PASSWORD
SPRING_FLYWAY_DEFAULT_SCHEMA=flyway
SPRING_FLYWAY_SCHEMAS=flyway
```

Positive public requests:

```text
GET /api/v1/compare?platform=telegram&horizonHours=24&includePartial=false&metric=reactions&aggregation=median&institutionLimit=2
GET /api/v1/compare?platform=telegram&horizonHours=24&includePartial=false&metric=reactions&aggregation=median&channels=920001&channels=920002
GET /api/v1/rating?platform=telegram&period=1d&channel_sort=engagement&channel_direction=desc&post_sort=view_share&post_direction=desc&entityLimit=2
```
