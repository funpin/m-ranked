# Integration integration-review-20260906-r17 results

PASS: 33 commands, zero failures, cleanup complete. Sum of recorded command durations: 393.912 seconds. This is not a reconstructed wall-clock run duration. No production acceptance is claimed.

Actual database evidence in `reverse.json` records V1–V29: 29 successful Flyway migrations with exact checksums and file SHA256 values. This manifest was observed at reverse rehearsal, not at run start.

| Mandatory service suite | Cases | Skips | Command seconds |
|---|---:|---:|---:|
| bridge | 3 | 0 | 21.670 |
| native-identity | 1 | 0 | 21.944 |
| identity-history | 1 | 0 | 15.606 |
| preserved-source | 1 | 0 | 12.899 |
| archive | 1 | 0 | 0.988 |
| collectors | 2 | 0 | 2.353 |
| observation-integrity | 111 | 0 | 41.567 |
| operations-metrics | 1 | 0 | 0.808 |
| reverse-rehearsal | 10 | 0 | 12.044 |

All 131 cases in these commands passed with zero skips. Some operational and reverse commands also contain unit cases; the recorded module counts are retained in `summary.json`.

Spring generic invocation: 224 cases, 220 passed, four conditional `MigrationInstallationTest` entry points skipped, zero errors/failures. Query-plan invocation separately passed 1 case(s), zero skips. Sanitized XML is retained in `spring-junit`; its manifest binds original and retained hashes. Required clean/V8-upgrade and seven disposable installations passed in explicit commands, independently of the generic invocation's conditional installer skips.

Full Python invocation: 579 passed, 108 skipped, 42.40 seconds reported by pytest. `conditional-service-coverage.json` maps all 108 conditional nodeids to successful mandatory-service JUnit cases. The full Python log did not include individual skip reasons; the map comes from read-only collection and reviewed runtime guards, and matches the exact logged skip count. No test bodies were rerun for this map.

Retained structured proofs include async and legacy CSV heap/boundedness, legacy byte oracles including actual cold archive, period/projection oracles, health, identity command roundtrip/receipt restore, reverse and query plans. Their exact paths and hashes are listed in `summary.json`. These results and hashes are not a restorable source backup.

| Command | Seconds | Exact argv |
|---|---:|---|
| services | 6.064 | `docker compose --project-name mranked-ci-9efc1c45f26a --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-z2i1vzmx/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml up -d --wait postgres redis` |
| create-clean_it | 0.186 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE clean_it OWNER migration_owner'` |
| create-upgrade_it | 0.173 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE upgrade_it OWNER migration_owner'` |
| create-bridge_it | 0.180 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE bridge_it OWNER migration_owner'` |
| create-collector_it | 0.178 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE collector_it OWNER migration_owner'` |
| create-reverse_it | 0.176 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE reverse_it OWNER migration_owner'` |
| create-ledger_it | 0.177 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE ledger_it OWNER migration_owner'` |
| create-catalog_it | 0.181 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE catalog_it OWNER migration_owner'` |
| create-native_it | 0.176 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE native_it OWNER migration_owner'` |
| create-history_it | 0.184 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE history_it OWNER migration_owner'` |
| create-golden_it | 0.179 | `docker exec mranked-ci-9efc1c45f26a-postgres-1 psql -U mranked_bootstrap -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE golden_it OWNER migration_owner'` |
| flyway-clean-upgrade | 12.370 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#cleanInstallationAndFrozenV8UpgradeHaveTheSameManifest' test` |
| flyway-bridge_it | 5.493 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-collector_it | 5.545 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-reverse_it | 5.018 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-ledger_it | 5.371 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-catalog_it | 6.168 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-native_it | 4.788 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| flyway-history_it | 6.312 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Pmigration-integration '-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase' test` |
| redis-ping | 0.185 | `docker exec mranked-ci-9efc1c45f26a-redis-1 sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'` |
| bridge | 21.670 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_migration_bridge_postgres.py tests/test_bridge_actual_target_postgres.py -k 'not missing_source_row and not cleared_native_identity' --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/bridge.xml` |
| native-identity | 21.944 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_cleared_native_identity_closes_history_and_reenrollment_appends --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/native-identity.xml` |
| identity-history | 15.606 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_identity_history_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/identity-history.xml` |
| preserved-source | 12.899 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_bridge_actual_target_postgres.py::test_missing_source_row_requires_verified_owner_ledger_and_remains_checked --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/preserved-source.xml` |
| archive | 0.988 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_cold_archive_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/archive.xml` |
| collectors | 2.353 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_target_collectors_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/collectors.xml` |
| observation-integrity | 41.567 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_observation_integrity_postgres.py tests/test_operational_projection_guards.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/observations.xml` |
| operations-metrics | 0.808 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_operations_metrics_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/metrics.xml` |
| spring | 157.034 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository '-Dtest=!QueryPlanEvidenceTest' test` |
| query-plans | 3.605 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/backend/mvnw -Dmranked.build.directory=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/backend-build -Dmaven.repo.local=/private/tmp/mranked-maven-repository -Dtest=QueryPlanEvidenceTest test` |
| python | 43.203 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q` |
| reverse-rehearsal | 12.044 | `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python -m pytest -q tests/test_reverse_sync_postgres.py --junitxml=/Users/funpin/Documents/ChatGPT/TG-monitoring/migration/reports/integration-review-20260906-r17/reverse.xml` |
| cleanup | 1.087 | `docker compose --project-name mranked-ci-9efc1c45f26a --env-file /private/var/folders/rx/pcjkmw2d7tjbjll21rtr8z8h0000gn/T/mranked-integration-z2i1vzmx/services.env -f /Users/funpin/Documents/ChatGPT/TG-monitoring/infra/compose.yaml down --volumes --remove-orphans` |
