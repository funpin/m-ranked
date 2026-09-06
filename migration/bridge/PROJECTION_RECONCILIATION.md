# Independent derived projection gate

`projection_reconciliation.verify_projections` is a read-only gate for an accepted
standalone SQLite artifact and the published PostgreSQL revision. It calls the
unchanged original overview and comparison endpoint functions with an injected
clock, then compares their numeric context directly with current derived tables.
It never invokes projection rebuild, trusts a stored projection digest, or uses
source-row metadata as the target value.

Coverage is Telegram/VK/MAX/Rutube overview at 3h, 1d, 7d and 30d; non-Telegram
institution period sums/medians; and Telegram/VK/Rutube comparison at 24, 48, 72,
168 and 336 hours, with both partial-history settings. Every comparison point,
sample count and fixed cohort size is checked for reactions and engagement.
MAX has no legacy comparison formula. Telegram institution-level period metrics
are not equated with channel cards. Official rating, identity history and other
projection families retain their separate release gates.

Counters and medians use exact decimal comparison. Engagement percentages use
eight decimal places to reconcile original Python binary floats with PostgreSQL
numeric. NULL remains distinct from zero; missing/extra/duplicate rows fail.
The output records SHA-256, revision, observation anchor, source row count,
configuration, dimensions, ordered digests and changed-key samples.

Run with a migration_bridge DSN supplied in `MRANKED_PROJECTION_VERIFY_DSN`:

```text
python -m migration.bridge.projection_reconciliation \
  --source /private/accepted/S_final.sqlite --source-name production-legacy \
  --source-sha256 ACCEPTED_SHA256 --first-age-limit-seconds 360
```

Pass the actual legacy configuration explicitly. The default is the original
six-minute first-observation limit. The input must match a recorded import and
have no WAL, SHM or journal sidecar. SQLite opens with `mode=ro&immutable=1` and
`query_only=ON`; its SHA is checked before and after. PostgreSQL uses one read-only
repeatable-read transaction, or the caller's existing repeatable-read transaction.
V26 grants the bridge SELECT only on the four already-public derived tables
needed in addition to its existing reads.

Every `s_final` import and reconciliation requires this gate automatically.
For other snapshot kinds pass `--verify-projections` to `migration.bridge import`
or `reconcile`; there is no option to disable the S_final gate. The bridge report
contains a critical `derived_projection_parity` check and the full
`projection_verification` result. Cutover preflight rejects reports without that
proof or with different source SHA, revision, dimensions or comparison digests.

Original endpoint evaluation is bounded to 250,000 source rows and 5,000
institutions/channels per invocation. Exceeding a bound fails explicitly; it is
not a partial pass. Ordered comparison uses a private disk-backed SQLite sort
with a 2 MiB cache and target server cursors. No complete PostgreSQL result set is
loaded into memory.

An artifact missing owner-preserved historical source rows is explicitly rejected
with `PRESERVED_HISTORY_ORACLE_RECONSTRUCTION_REQUIRED` unless matching prior
artifacts are supplied with repeatable `--preserved-source PATH` options. These
paths also have the typed `BridgeOptions.preserved_source_paths` interface.
`preserve-disappeared` retains its verified `--prior-source` for the current
invocation; later invocations must supply that artifact again.

The verifier creates a private SQLite backup of the current source and inserts
only absent rows whose table, key and exact source row hash match an immutable
owner-approved preserved decision and a recorded prior artifact SHA. Current rows
are never overwritten. It verifies prior hashes before and after, checks the
overlay schema, SQLite integrity and foreign keys, then reads the overlay
immutably under the original published observation anchor. Reports distinguish
original SHA, overlay SHA, prior SHA values and restored row count. At most 64
prior artifacts and 250,000 classified rows are accepted. Missing, conflicting,
changed or unclassified evidence produces critical NO-GO, never a partial pass.
This source reconstruction does not claim to infer historical identity intervals
absent from all retained artifacts; those retain their independent history gate.

`ProjectionReconciliationPostgresIntegrationTest` creates a disposable database,
installs actual current Flyway SQL, imports a source fixture and compares 28 cards,
96 period cells and 7,836 comparison points. Direct mutations of card values,
period values, hourly counters and cohort membership must each fail before any
rebuild, including an overall critical bridge NO-GO. Test transactions roll back those mutations; both the owner and actual
migration_bridge role must produce the same original-source report.
