# Required migration rehearsals

`run.py` creates a randomly named Docker Compose project, private credentials,
empty PostgreSQL databases and Redis. It runs real Flyway clean installation and
the frozen V8 → V29 → V30 upgrade, then bridge, native identity, complete identity history,
owner-preserved source, archive, collectors, observation integrity, operational
projection guards, metrics, Spring, query plans, the full Python suite and reverse
sync. Each mutation-heavy fixture receives its own database when its retained
history would invalidate another fixture's source. Required PostgreSQL steps
reject skipped tests. The no-service Python pass may skip those same tests, which
already run with real credentials in the preceding mandatory steps.

From the repository root with Docker, Java 21, Maven and Python 3.13 dependencies:

Operational shell tests also require Bash, GNU coreutils, GNU awk and `jq`.
CI explicitly installs `gawk`/`jq` and creates `.venv`, which is also used by the
release's isolated Python wrappers. The runner places temporary fixtures below
its private output directory: provenance tests intentionally reject a writable
ancestor such as `/tmp`. Use an output directory under a trusted checkout.
Temporary runtime directories are removed on exit, ignored by Git and excluded
from CI artifact uploads, including interrupted runs; private service credentials
must never become retained test evidence.

Set `MRANKED_LEGACY_REFERENCE_ROOT` to the separate trusted checkout described in
[legacy-reference.md](../legacy-reference.md) before either integration command.

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

For the required real-browser overview status/identity comparison, install Node
24, frontend dependencies and Playwright's pinned Chromium, then run:

```sh
rtk proxy .venv/bin/python -m migration.integration.run --semantic-only \
  --output migration/reports/unique-browser-semantics-run
```

The comparison follows each old card's destination through the target's
compatibility redirects before checking its canonical UUID link. Text, warning
state, order, counts and every continuation page still have to match. Numeric,
CSV, mutation and history integrity remain mandatory in the PostgreSQL/Spring
suite; frontend route/chart interactions are covered by `pnpm check`.
The `overview-status` fixture profile keeps all 207 institutions and more than
200 accounts per platform, using short histories for added accounts. It is not
a performance or long-horizon chart corpus. The default `legacy-visual` profile
retains the historical 16-day histories and over 8 million comparison points.

The historical pixel comparison is a separate diagnostic audit:

```sh
rtk proxy .venv/bin/python -m migration.integration.run --visual-only \
  --output migration/reports/unique-visual-run
```

Both browser modes create the representative original SQLite fixture, import it,
starts the original legacy application and the packaged Spring/Next servers,
and inspect both in one browser runtime. Authentication is confined to private
fixture credentials. Browser form mutation tests must use a separate disposable
database, leaving the visual/performance corpus frozen. Frontend lint, typecheck,
OpenAPI drift, unit and route tests also run in `.github/workflows/migration.yml`.
CI requires the current stack checks and `--semantic-only`. The old 0.5% pixel
threshold targets the Python UI before canonical routes and shared history
charts; it is not an acceptance criterion for those intentional changes.
`--visual-only` and the manual workflow input `legacy_pixel_audit` preserve that
historical audit without silently relaxing its threshold or rewriting evidence.

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
