# Target collectors

`collector_target` is the PostgreSQL-only ingestion path for Telegram, VK,
MAX, and RUTUBE. It reuses the current read-only platform gateways but does not
open or write the legacy SQLite database.

## Runtime contract

Run one isolated process per platform:

```text
.venv/bin/python -m collector_target --platform telegram
.venv/bin/python -m collector_target --platform vk
.venv/bin/python -m collector_target --platform max
.venv/bin/python -m collector_target --platform rutube
```

`--platform %i` is the systemd template contract. The default is a long-running
poll loop; `--once` performs one cycle for smoke tests. `--partition default`
collects all enabled accounts. Deterministic zero-based shards use `INDEX/COUNT`,
for example `--partition 0/4`.

The database DSN is read only from `COLLECTOR_DATABASE_URL`, with
`DATABASE_URL` as a fallback, so credentials do not appear in the process list.
`COLLECTOR_VERSION` and `COLLECTOR_POLL_INTERVAL_SECONDS` are optional. Existing
platform credentials and `DATA_SOURCE` continue to come from `.env`/`Settings`
when no credential file is configured.

Tracked-publication refresh has two independent bounded controls:

- `COLLECTOR_REFRESH_LIMIT` (default `100`) is the maximum number of due
  publications point-read per account/run;
- `COLLECTOR_REFRESH_SCAN_LIMIT` (default `400`, never below the refresh limit)
  bounds the circular PostgreSQL candidate scan.

Discovery always runs first with its own `DISCOVERY_LIMIT`; refresh cannot
consume or reduce that budget. Candidates are active publications inside
`TRACK_POST_FOR_HOURS`, ordered circularly by deterministic publication UUID.
The account checkpoint `collector.refresh_cursor.v1` advances through rows that
were examined, but stops at the last selected row when the refresh budget fills.
It commits with the account batch, so a failed/resumed run selects the same page
and every eligible row is eventually revisited without starving discovery.

For systemd `LoadCredential`, set
`COLLECTOR_PLATFORM_AUTH_FILE=%d/platform-auth`. The file is parsed as UTF-8
`KEY=value`, is limited to 16 KiB, must be a non-symlink regular file owned by
root or the service user with mode `0400` or `0600`, and has an exact
platform/mode allowlist:

- Telegram `mtproto`: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
- Telegram `public_web`/`telegram_web`: no keys
- VK: `VK_ACCESS_TOKEN`
- MAX: `MAX_USER_PHONE`
- RUTUBE: no keys

Blank lines and comments beginning with `#` are accepted. Unknown, duplicate,
malformed, blank, missing, or extra entries fail startup. Supplying a direct
credential and a credential-file value for the same platform also fails closed.
The loader never copies secrets into process environment variables, arguments,
or error messages. Telegram and MAX session paths remain ordinary writable
state paths; a MAX unit must start with a previously authorized session because
the target runtime does not perform an interactive login.

## Guarantees

- A deterministic run ID is derived from platform, partition, collector version,
  and scheduled UTC instant.
- A PostgreSQL advisory lease is independent for every platform/partition.
  A MAX failure therefore cannot prevent Telegram, VK, or RUTUBE from running.
- Successful accounts are skipped when the same deterministic run resumes;
  failed or interrupted accounts are retried. The CLI first resumes the oldest
  running/partial/failed run for its platform, partition, and collector version;
  otherwise it uses a deterministic wall-clock schedule slot.
- Each account commits its account/publication observations, reaction rows,
  retrievable sanitized evidence, account cursor, dataset revision, and outbox event
  in one PostgreSQL transaction.
- That collector outbox event is `projection.rebuild.requested`; a raw ingestion
  commit is never advertised as `dataset.revision.changed`. The separate
  maintenance-role projection publisher coalesces requests, rebuilds and
  verifies all six latest-revision projections, then atomically records the
  cache-visible published-revision event. Exact account replay creates neither
  another request nor another revision.
- Observation conflicts use deterministic identity and sampling keys. An exact
  retry writes neither a second observation nor a second dataset revision.
- Telegram public discovery observed no later than
  `COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES` (six minutes by default) emits one
  estimated, age-zero synthetic snapshot and the real rounded snapshot for the
  same publication. The synthetic row has sampling bucket `-1`, never produces
  deletion/presence evidence, and only sets the stored period-baseline decision
  while history remains `complete`. Later discovery stays `incomplete` and has
  no synthetic row. Telegram MTProto never creates a publication baseline.
- `forced_incomplete` is monotonic: neither a later `complete` observation nor
  a later synthetic input may upgrade it or create a publication-time baseline.
  V30 allows an independently retained legacy baseline on an already
  forced-incomplete publication; refresh and replay preserve that stored fact.
  Imported publications keep their original UUID, including snapshot writes
  and presence/deletion probes when a provider record resolves to an imported ID.
- `NULL` remains “unsupported/unavailable”; zero remains an observed zero. VK
  positive-to-zero regressions are persisted as `NULL` with
  `suspected_reset` quality.
- Evidence and logs use allowlisted counters/identifiers and recursive secret
  redaction. Exception messages are never persisted or logged by this runtime.
- Every returned discovery/point-read publication records a `present` deletion
  observation and resets pending missing evidence. A successful rediscovery also
  clears `deleted_at`, matching legacy recovery behavior without deleting prior
  observations.
- `DELETION_CONFIRMATION_CHECKS` defaults to `2` and the target rejects values
  below two. Only provider-authoritative point results increment the counter:
  successful MTProto `get_messages` omission, Telegram public `404`/`410` or its
  recognized deleted marker, successful VK `wall.getById` omission/deleted item,
  successful MAX `get_messages` omission, and RUTUBE exact-video `404`/`410`.
  Feed/history omission, partial discovery, authentication failures, rate limits,
  transport failures, `5xx`, and ambiguous bodies never increment it. The
  threshold sets only `publication.deleted_at`; identities and observations are
  retained.

V3 stores scheduler, observation, and collection instants separately in
`collection_run.scheduled_at` and the metric snapshot `observed_at`/
`collected_at` columns. Operational checkpoints also retain the latest schedule
and per-account cursor. Observed presentation and native identifiers are
versioned in the two catalog history tables and their denormalized current
values are updated with the V3 column-level grants. Native identities keep the
bridge-compatible `<platform>:native_id` namespace. V9 writes sanitized evidence to `COLLECTOR_RAW_EVIDENCE_DIR` (default
`data/target-raw-evidence`), which must be durable service-owned storage. The
content-addressed JSON is published atomically with mode `0400` inside a `0700`
directory before the canonical transaction commits. `ingest.raw_payload` stores
the immutable `file://` reference, verified SHA-256 and seven-day `purge_after`.
`ImmutableEvidenceStore.read()` enforces expiry, root confinement, no symlinks,
permissions, canonical serialization, redaction and content hash. A crash before
PG commit may leave an unreferenced object; exact retry reuses it. Missing or
corrupt evidence fails closed. This raw-evidence directory is not a cold archive.
Normalization rejection records sanitized retrievable evidence in
`ingest.evidence_quarantine` without publishing canonical facts.

Raw evidence is opt-in with `COLLECTOR_PERSIST_RAW_EVIDENCE=true`. Compact
production collectors retain the canonical `source_fingerprint` without writing
one filesystem object per observation. Target-generated legacy CSV lexemes are
separately opt-in with `COLLECTOR_PERSIST_LEGACY_CSV=true` and stay disabled once
the legacy stack has been retired.

## Collector metrics

Set `COLLECTOR_METRICS_FILE` to an absolute, service-writable Prometheus textfile
path, for example `/var/lib/node_exporter/textfile_collector/telegram.prom`.
Provision its directory first and use a distinct file for each platform process
and shard. A node exporter textfile collector can serve these files on the
private monitoring network. Each update is atomically replaced with mode `0640`.

The runtime records account latency histograms (success/failure), run outcomes,
inserted snapshot counters and the last successful collection timestamp. Labels
are bounded by the four platform enum values and fixed status/outcome enums;
they never contain account IDs, URLs, credentials or exception messages. Counter
resets on process restart have normal Prometheus counter semantics. A failed
metrics write logs only a sanitized exception class and cannot undo a committed
collection. Alert expressions are in
`operations/observability/collector-alerts.yml`; this textfile producer does not
claim that a production scrape endpoint has already been deployed.

V9 stores each metric's quality and source/semantic evidence independently.
Row-level quality is operational only: one invalid shares value cannot hide
valid views, reactions or comments. Publication and account insert triggers
serialize corrections by logical slot, no-op exact fingerprints, reject reused
fingerprints with different values, and assign immutable predecessor, sequence
and reason. Both active-tip views select the largest correction sequence.
Published V1–V8 rows are backfilled once without changing their original values.
Older hash-only raw references are marked `legacy_evidence_unavailable`; their
missing payload is an explicit acceptance gap, never evidence of retrieval.

## Explicit remaining validation gaps

- The bounded refresh/deletion pipeline has deterministic unit and disposable
  PostgreSQL coverage, but no live provider credentials were used here. A
  production-like shadow run must still prove discovery + historical refresh +
  two-check deletion/recovery for every enabled platform before legacy
  collection can be retired.
- Remote encrypted evidence storage/key management and production storage
  acceptance remain external work. `ImmutableEvidenceStore.purge_expired()`
  removes expired/unreferenced blobs in bounded batches using the collector's
  per-hash database lock. All PG references are checked before unlink; orphan
  files receive at least seven days of grace. Use the maintenance role and the
  same durable directory; the generic PG metadata purge alone does not remove
  the files.

Unit tests live in `tests/test_target_collectors.py`. The real-schema suite
in `tests/test_target_collectors_postgres.py` is mandatory in
`python -m migration.integration.run`: that producer provisions its own services
and rejects skipped integration cases. A standalone invocation requires
`MRANKED_TEST_POSTGRES_DSN` set to a collector-role DSN for a database with
the target Flyway schema. Fixture creation/cleanup uses
`MRANKED_TEST_POSTGRES_ADMIN_DSN`; it falls back to the first DSN only for a
privileged disposable test database. Against the exact current schema it verifies public
baseline/actual persistence, retry idempotency, monotonic forced-incomplete
merge, and the rollback-only `1d` activity projection from publication zero.

Account observations also publish a minimal original identity receipt before
their PostgreSQL transaction commits. Set `MRANKED_IDENTITY_RECEIPT_DIR` to the
same protected root used by the API, migration verifier and reverse sync; each
collector writes only its own `collector/<platform>/` subtree. The deployed
shared-reader layout uses writer-owned `2750` directories and immutable `0440`
files with group `m-ranked-identity-readers`. Collectors are not members of that
group; reverse/backup readers receive supplementary membership. Private
single-user fixtures still use exact `0700`/`0400`. These inputs retain username,
title, safe URL, native ID, observation time and committed event bindings. They
are retained independently of expiring provider raw payloads so that later
S_final verification can reconstruct the identity timeline from original
inputs. See [ownership and recovery requirements](../operations/runbooks/IDENTITY_RECEIPTS.md).
