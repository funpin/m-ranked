# Mandatory V27 integration result

PASS for all 33 commands; 309.835 seconds. This is disposable local evidence,
not production acceptance. Created PostgreSQL/Redis services and volumes were
removed successfully.

```sh
rtk proxy env JAVA_HOME=/Users/funpin/Library/Java/JavaVirtualMachines/openjdk-21/Contents/Home MAVEN_USER_HOME=/private/tmp/mranked-maven-home MRANKED_MAVEN_REPOSITORY=/private/tmp/mranked-maven-repository .venv/bin/python -m migration.integration.run --output migration/reports/integration-review-20260905-r12
```

- Clean Flyway V1–V27 and V1–V8 → V27 upgrade: PASS.
- Actual bridge 3, native clear/re-enrollment 1, complete identity history 1,
  preserved source 1, archive 1, collectors 2, observation/operational guards
  111, metrics 1 and reverse sync 10: all PASS, zero skips.
- Spring: 210 tests, zero failures/errors; four profile-only installation
  entrypoints skipped in the broad invocation after their explicit installation
  invocations passed. One separate actual PostgreSQL query-plan test passed.
- Full Python: 480 passed, 108 skipped, 38.22 seconds. Service-dependent cases are
  exercised in the preceding mandatory real-service invocations; the runner
  rejects skipped tests there.
- `git diff --check`: PASS after completion.

Exact nested commands, return codes and durations are in `integration.json`.
JUnit files and original logs remain beside it. `summary.json` records exact
Flyway pins and the source inventory at summary time. Frontend capture proceeds
independently; this report does not assert production acceptance or a route GO.
