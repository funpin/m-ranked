# Integration integration-review-20260906-r14 results

PASS: 33 commands, zero failures, cleanup complete. Sum of recorded command durations: 396.012 seconds. This is not a reconstructed wall-clock run duration. No production acceptance is claimed.

Actual database evidence in `reverse.json` records V1–V28: 28 successful Flyway migrations with exact checksums and file SHA256 values. This manifest was observed at reverse rehearsal, not at run start.

| Mandatory service suite | Cases | Skips | Command seconds |
|---|---:|---:|---:|
| bridge | 3 | 0 | 23.918 |
| native-identity | 1 | 0 | 20.260 |
| identity-history | 1 | 0 | 13.336 |
| preserved-source | 1 | 0 | 10.265 |
| archive | 1 | 0 | 0.998 |
| collectors | 2 | 0 | 1.977 |
| observation-integrity | 111 | 0 | 37.328 |
| operations-metrics | 1 | 0 | 1.084 |
| reverse-rehearsal | 10 | 0 | 14.080 |

All 131 cases in these commands passed with zero skips. Some operational and reverse commands also contain unit cases; the recorded module counts are retained in `summary.json`.

Spring generic invocation: 215 cases, 211 passed, four conditional `MigrationInstallationTest` entry points skipped, zero errors/failures. Query-plan invocation separately passed 1 case(s), zero skips. Sanitized XML is retained in `spring-junit`; its manifest binds original and retained hashes. Required clean/V8-upgrade and seven disposable installations passed in explicit commands, independently of the generic invocation's conditional installer skips.

Full Python invocation: 526 passed, 108 skipped, 41.46 seconds reported by pytest. `conditional-service-coverage.json` maps all 108 conditional nodeids to successful mandatory-service JUnit cases. The full Python log did not include individual skip reasons; the map comes from read-only collection and reviewed runtime guards, and matches the exact logged skip count. No test bodies were rerun for this map.

Retained structured proofs include async and legacy CSV heap/boundedness, legacy byte oracles including actual cold archive, period/projection oracles, health, identity command roundtrip/receipt restore, reverse and query plans. Their exact paths and hashes are listed in `summary.json`. These results and hashes are not a restorable source backup.

| Command | Seconds | Exact argv |
|---|---:|---|
| services | 6.610 | `docker compose --project-name mranked-ci-a8e4bf1daed0 --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-2p7luboo/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml up -d --wait postgres redis` |
| create-clean_it | 0.336 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE clean_it OWNER migration_owner'` |
| create-upgrade_it | 0.384 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE upgrade_it OWNER migration_owner'` |
| create-bridge_it | 0.228 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE bridge_it OWNER migration_owner'` |
| create-collector_it | 0.223 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE collector_it OWNER migration_owner'` |
| create-reverse_it | 0.380 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE reverse_it OWNER migration_owner'` |
| create-ledger_it | 0.170 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE ledger_it OWNER migration_owner'` |
| create-catalog_it | 0.172 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE catalog_it OWNER migration_owner'` |
| create-native_it | 0.170 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE native_it OWNER migration_owner'` |
| create-history_it | 0.177 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE history_it OWNER migration_owner'` |
| create-golden_it | 0.173 | `docker exec mranked-ci-a8e4bf1daed0-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE golden_it OWNER migration_owner'` |
| flyway-clean-upgrade | 11.885 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#cleanInstallationAndFrozenV8UpgradeHaveTheSameManifest' test` |
| flyway-bridge_it | 5.710 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-collector_it | 7.082 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-reverse_it | 5.647 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-ledger_it | 6.002 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-catalog_it | 5.249 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-native_it | 4.657 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-history_it | 6.426 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| redis-ping | 0.183 | `docker exec mranked-ci-a8e4bf1daed0-redis-1 sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'` |
| bridge | 23.918 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_migration_bridge_postgres.py tests/test_bridge_actual_target_postgres.py -k 'not missing_source_row and not cleared_native_identity' --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/bridge.xml` |
| native-identity | 20.260 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_cleared_native_identity_closes_history_and_reenrollment_appends --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/native-identity.xml` |
| identity-history | 13.336 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_identity_history_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/identity-history.xml` |
| preserved-source | 10.265 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_missing_source_row_requires_verified_owner_ledger_and_remains_checked --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/preserved-source.xml` |
| archive | 0.998 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_cold_archive_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/archive.xml` |
| collectors | 1.977 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_target_collectors_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/collectors.xml` |
| observation-integrity | 37.328 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_observation_integrity_postgres.py tests/test_operational_projection_guards.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/observations.xml` |
| operations-metrics | 1.084 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_operations_metrics_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/metrics.xml` |
| spring | 162.520 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository '-Dtest=!QueryPlanEvidenceTest' test` |
| query-plans | 4.679 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Dtest=QueryPlanEvidenceTest test` |
| python | 42.563 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q` |
| reverse-rehearsal | 14.080 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_reverse_sync_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r14/reverse.xml` |
| cleanup | 1.140 | `docker compose --project-name mranked-ci-a8e4bf1daed0 --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-2p7luboo/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml down --volumes --remove-orphans` |
