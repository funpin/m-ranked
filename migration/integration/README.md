# Required migration rehearsals

`run.py` creates a randomly named Docker Compose project, private credentials,
empty PostgreSQL databases and Redis. It runs real Flyway clean installation and
the frozen V1–V8 upgrade, then bridge, native identity, complete identity history,
owner-preserved source, archive, collectors, observation integrity, operational
projection guards, metrics, Spring, query plans, the full Python suite and reverse
sync. Each mutation-heavy fixture receives its own database when its retained
history would invalidate another fixture's source. Required PostgreSQL steps
reject skipped tests. The no-service Python pass may skip those same tests, which
already run with real credentials in the preceding mandatory steps.

From the repository root with Docker, Java 21, Maven and Python 3.13 dependencies:

```sh
rtk proxy .venv/bin/python -m migration.integration.run \
  --output migration/reports/unique-integrity-run
```

`JAVA_HOME`, `MAVEN_USER_HOME` and optional `MRANKED_MAVEN_REPOSITORY` select the
toolchain. `--python` accepts an installed interpreter; Java-backed Python oracle
fixtures receive the resolved executable through `MRANKED_INTEGRATION_PYTHON`.
No developer-local `.venv` path is required in CI. Failed attempts retain their
logs and reports. The runner removes only its own containers, databases and
volumes in `finally`; output paths must be new for every invocation.

For the real browser baseline, install frontend dependencies and Playwright's
pinned Chromium, then run the self-provisioned visual mode:

```sh
rtk proxy .venv/bin/python -m migration.integration.run --visual-only \
  --output migration/reports/unique-visual-run
```

The producer creates the representative original SQLite fixture, imports it,
starts the original legacy application and the packaged Spring/Next servers,
and captures both in one browser runtime. Authentication is confined to private
fixture credentials. Browser form mutation tests must use a separate disposable
database, leaving the visual/performance corpus frozen. Frontend lint, typecheck,
OpenAPI drift, unit and route tests also run in `.github/workflows/migration.yml`.

## Verify an existing frozen corpus without writing PostgreSQL

`verify_frozen.py` combines the independent canonical digest, original endpoint
projection and complete account identity history oracles in one database-enforced
`REPEATABLE READ READ ONLY` transaction. It does not invoke bridge import, rebuild
or persist reconciliation rows. Supply the role credential only through the
`MRANKED_FROZEN_VERIFY_DSN` environment variable, and use the namespace and snapshot
kind of the accepted import:

```sh
rtk proxy .venv/bin/python -m migration.integration.verify_frozen \
  --source /private/accepted/fixture.sqlite \
  --source-namespace ACCEPTED_NAMESPACE --snapshot-kind fixture \
  --expected-revision ACCEPTED_REVISION \
  --output migration/reports/unique-frozen-verification
```

Provide repeatable `--historical-source` and `--preserved-source` paths when
closed identity transitions or owner-preserved deleted rows require previous
accepted SQLite artifacts. Source SHA, actual revision, exact Flyway manifest,
canonical counts/digests, full oracle results and duration are retained. Source
SHA is checked again after reading. Missing evidence or an exceeded oracle bound
fails explicitly; it never produces a partial pass.

The original legacy oracle is bounded to 250,000 source rows and 5,000 entities.
These are verifier limits, not a claim about production capacity. The frozen
representative fixture has 207 institutions, 824 accounts, 824 publications,
9,026 raw snapshots and 8,534,560 derived comparison points. Its fresh V26
PostgreSQL database used 2,011,543,231 bytes. After the V27 corrective rebuild the
runtime measured 3,952,228,031 bytes, and the subsequent DR capture measured
3,952,473,791 bytes; logical cardinalities stayed fixed. Physical layout and
maintenance bookkeeping can change size without adding source facts. Reports
record actual size rather than requiring artificial database bloat.

HTTP transition and physical DR have separate producers under
`operations/http_transition/` and `operations/disaster_recovery/`. Local rehearsals
do not authorize production routing, Writer Gate W, partition deletion or removal
of the recoverable legacy runtime.
