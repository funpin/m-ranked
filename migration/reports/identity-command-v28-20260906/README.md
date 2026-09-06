# Original identity inputs: local V28 evidence

`report.json` links self-contained results and hashes. It is not a source backup:
the temporary original SQLite files and receipt objects were deliberately created
inside disposable fixtures. The fixture code reproduces those synthetic inputs.
No production database, raw provider payload or credential is included here.

The actual Java test creates a fresh PostgreSQL database, installs Flyway V1–V28,
imports an original S_final, and calls the real `CatalogService`/
`JdbcCatalogRepository`. Username/title/HTTP URL and native ID changes are applied
from original commands, including NULL → N → N+1 → NULL → N+2. The test then drains,
verifies and stops real reverse-sync, imports a second mandatory S_final, and
repeats it with a fresh invocation and zero writes. Rollback, duplicate commands
across actor/correlation contexts and unavailable durable storage are checked.

The exact referenced input inventory is copied into another protected directory.
With the original directory unavailable, complete reconciliation passes using
the restored copy. Missing or forged restored bytes cause NO-GO. The collector
fixture separately removes expired provider evidence after eight days and proves
that retained minimal identity inputs still reconstruct the complete timeline.
The original fourteen corruption cases and compound closed-row deletion/backdate
case remain unchanged.

Reproduction uses the existing disposable integration environment; keep all
credentials in process environment or protected local configuration:

```sh
python -m migration.integration.run --help
mvn -f backend/pom.xml -Dtest=IdentityCommandPostgresIntegrationTest,IdentityCommandEvidenceTest,PublicQueryControllerTest test
python -m pytest -q tests/test_identity_history_postgres.py tests/test_identity_receipts.py tests/test_identity_history_release_gate.py tests/test_target_collectors.py
```

The Java PostgreSQL test requires `MRANKED_EXPORT_TEST_ADMIN_URL`,
`MRANKED_EXPORT_TEST_ADMIN_USERNAME`, `MRANKED_EXPORT_TEST_ADMIN_PASSWORD`,
`MRANKED_ADMIN_TEST_PASSWORD` and `MRANKED_LEGACY_CSV_BRIDGE_PASSWORD`. The target
must be an explicitly disposable local `_it` control database. The test creates
and drops its own UUID database. The Python history test requires a fresh exact
Flyway database via `MRANKED_TEST_POSTGRES_ADMIN_DSN`. The mandatory runner
provisions these dependencies and rejects skipped required integration tests.

The combined Java run passed 21 tests; the final focused rerun passed 20 tests
after directory-parent fsync hardening. Python units passed 59 tests and the
expanded real PostgreSQL history scenario passed with zero skips. Full mandatory
integration, fresh HTTP deployment and production operational approval are
separate evidence gates owned by the coordinating task.
