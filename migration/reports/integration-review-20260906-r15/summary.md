# Integration integration-review-20260906-r15 results

PASS: 33 commands, zero failures, cleanup complete. Sum of recorded command durations: 554.058 seconds. This is not a reconstructed wall-clock run duration. No production acceptance is claimed.

Actual database evidence in `reverse.json` records V1–V29: 29 successful Flyway migrations with exact checksums and file SHA256 values. This manifest was observed at reverse rehearsal, not at run start.

| Mandatory service suite | Cases | Skips | Command seconds |
|---|---:|---:|---:|
| bridge | 3 | 0 | 16.590 |
| native-identity | 1 | 0 | 16.860 |
| identity-history | 1 | 0 | 13.983 |
| preserved-source | 1 | 0 | 9.648 |
| archive | 1 | 0 | 0.768 |
| collectors | 2 | 0 | 1.601 |
| observation-integrity | 111 | 0 | 33.939 |
| operations-metrics | 1 | 0 | 0.610 |
| reverse-rehearsal | 10 | 0 | 13.694 |

All 131 cases in these commands passed with zero skips. Some operational and reverse commands also contain unit cases; the recorded module counts are retained in `summary.json`.

Spring generic invocation: 216 cases, 212 passed, four conditional `MigrationInstallationTest` entry points skipped, zero errors/failures. Query-plan invocation separately passed 1 case(s), zero skips. Sanitized XML is retained in `spring-junit`; its manifest binds original and retained hashes. Required clean/V8-upgrade and seven disposable installations passed in explicit commands, independently of the generic invocation's conditional installer skips.

Full Python invocation: 531 passed, 108 skipped, 41.31 seconds reported by pytest. `conditional-service-coverage.json` maps all 108 conditional nodeids to successful mandatory-service JUnit cases. The full Python log did not include individual skip reasons; the map comes from read-only collection and reviewed runtime guards, and matches the exact logged skip count. No test bodies were rerun for this map.

Retained structured proofs include async and legacy CSV heap/boundedness, legacy byte oracles including actual cold archive, period/projection oracles, health, identity command roundtrip/receipt restore, reverse and query plans. Their exact paths and hashes are listed in `summary.json`. These results and hashes are not a restorable source backup.

| Command | Seconds | Exact argv |
|---|---:|---|
| services | 6.289 | `docker compose --project-name mranked-ci-b2ab5320d78a --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-n7hk6l12/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml up -d --wait postgres redis` |
| create-clean_it | 0.244 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE clean_it OWNER migration_owner'` |
| create-upgrade_it | 0.242 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE upgrade_it OWNER migration_owner'` |
| create-bridge_it | 0.179 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE bridge_it OWNER migration_owner'` |
| create-collector_it | 0.186 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE collector_it OWNER migration_owner'` |
| create-reverse_it | 0.246 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE reverse_it OWNER migration_owner'` |
| create-ledger_it | 0.239 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE ledger_it OWNER migration_owner'` |
| create-catalog_it | 0.190 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE catalog_it OWNER migration_owner'` |
| create-native_it | 0.188 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE native_it OWNER migration_owner'` |
| create-history_it | 0.246 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE history_it OWNER migration_owner'` |
| create-golden_it | 0.181 | `docker exec mranked-ci-b2ab5320d78a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE golden_it OWNER migration_owner'` |
| flyway-clean-upgrade | 18.892 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#cleanInstallationAndFrozenV8UpgradeHaveTheSameManifest' test` |
| flyway-bridge_it | 8.405 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-collector_it | 7.808 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-reverse_it | 6.377 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-ledger_it | 5.497 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-catalog_it | 5.276 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-native_it | 5.609 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-history_it | 4.950 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| redis-ping | 0.175 | `docker exec mranked-ci-b2ab5320d78a-redis-1 sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'` |
| bridge | 16.590 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_migration_bridge_postgres.py tests/test_bridge_actual_target_postgres.py -k 'not missing_source_row and not cleared_native_identity' --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/bridge.xml` |
| native-identity | 16.860 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_cleared_native_identity_closes_history_and_reenrollment_appends --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/native-identity.xml` |
| identity-history | 13.983 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_identity_history_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/identity-history.xml` |
| preserved-source | 9.648 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_missing_source_row_requires_verified_owner_ledger_and_remains_checked --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/preserved-source.xml` |
| archive | 0.768 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_cold_archive_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/archive.xml` |
| collectors | 1.601 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_target_collectors_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/collectors.xml` |
| observation-integrity | 33.939 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_observation_integrity_postgres.py tests/test_operational_projection_guards.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/observations.xml` |
| operations-metrics | 0.610 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_operations_metrics_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/metrics.xml` |
| spring | 326.804 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository '-Dtest=!QueryPlanEvidenceTest' test` |
| query-plans | 4.287 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Dtest=QueryPlanEvidenceTest test` |
| python | 42.150 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q` |
| reverse-rehearsal | 13.694 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_reverse_sync_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r15/reverse.xml` |
| cleanup | 1.705 | `docker compose --project-name mranked-ci-b2ab5320d78a --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-n7hk6l12/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml down --volumes --remove-orphans` |
