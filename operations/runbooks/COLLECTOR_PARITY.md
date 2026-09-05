# Target collector parity rehearsal

This runbook produces evidence for the collector portion of Writer Gate W. It
does not authorize stopping legacy collection, changing routes, deleting a real
publication, or fabricating a passing report.

## Static and disposable-database proof

Run the deterministic suite against the release candidate and a disposable
database migrated from V1 through the release's latest version:

```bash
rtk .venv/bin/python -m pytest -q tests/test_target_collectors.py
rtk env \
  MRANKED_TEST_POSTGRES_DSN="postgresql://collector_ingest@HOST/DB" \
  MRANKED_TEST_POSTGRES_ADMIN_DSN="postgresql://TEST_OWNER@HOST/DB" \
  .venv/bin/python -m pytest -q tests/test_target_collectors_postgres.py
```

The PostgreSQL tests prove first missing, intervening transient/auth evidence,
confirmed second missing, tombstone exclusion from refresh, actual rediscovery
recovery, atomic checkpointing, idempotent replay, and rollback on a failed
account transaction. They also prove a timely Telegram public baseline plus
actual snapshot, no retry revision, monotonic forced-incomplete semantics and a
rollback-only V5 activity result from zero. The provider adapter tests prove Telegram deleted marker,
MAX exact-lookup omission, RUTUBE exact `404`, and that `401`/`403`/`429` never
become deletion evidence.

## Shadow proof for all four platforms

Use isolated target accounts/sessions and a PostgreSQL clone. Keep the legacy
collector running against legacy SQLite; target collectors must not share its
session files. Set and record non-secret policy values:

```text
COLLECTOR_REFRESH_LIMIT=100
COLLECTOR_REFRESH_SCAN_LIMIT=400
DELETION_CONFIRMATION_CHECKS=2
TRACK_POST_FOR_HOURS=960
```

For Telegram MTProto/public (as deployed), VK, MAX, and RUTUBE:

1. Seed or import more tracked publications than the discovery page returns.
2. Run enough cycles for the circular cursor to wrap at least once.
3. Show a snapshot from a publication absent from discovery but returned by an
   exact point lookup.
4. Inject/replay a controlled auth failure, rate limit, transport failure and
   partial/ambiguous discovery; verify `consecutive_missing` does not increase.
5. Against a controlled provider test publication or recorded contract fixture,
   produce two authoritative missing results in distinct runs. Never delete a
   third party or production publication for this rehearsal.
6. Verify only the second result is `confirmed_deleted`, historical rows remain,
   and a later actual rediscovery records `present` and clears `deleted_at`.
7. Replay a committed run/account batch and prove no duplicate snapshots,
   deletion observations, revisions, or outbox events.
8. Keep `m-ranked-target-projection-publisher.service` active, wait for all six
   named projection states to equal the newest collector revision, and record
   that exact revision in the evidence. An older ready revision is a failure.

Useful read-only checks (bind IDs as parameters; do not paste credentials):

```sql
SELECT checkpoint_key, scope_id, value, source_observed_at
FROM ops_and_admin.operational_checkpoint
WHERE checkpoint_key = 'collector.refresh_cursor.v1';

SELECT publication_id, collection_run_id, observed_at, outcome,
       reason_code, consecutive_missing
FROM ingest.deletion_observation
ORDER BY publication_id, observed_at, id;

SELECT id, primary_account_id, published_at, deleted_at
FROM ingest.publication
WHERE id = :publication_id;
```

## Evidence and go/no-go

Store sanitized commands and query output as five distinct raw files below one
protected evidence root: one database/Flyway capture and one platform capture
for Telegram, VK, MAX and RUTUBE. Raw files must be regular non-symlinks with a
single hard link, no write bits, a SHA-256/byte count in the source document and
an mtime inside the declared shadow-run window. Do not include credentials,
session material or third-party personal data.

The source document is an exact versioned object. Its top-level fields are
`evidenceType=collector-parity-shadow-observations`, `evidenceVersion=1`,
`environment=production-like`, `status=pass`, `startedAt`, `finishedAt`,
`operator`, dedicated `approvalTicket`, `sourceNamespace`, `attestation`,
`database`, `flywayDatabaseMigrations`, `policy`, exactly four `platforms`,
`projection` and `duplicates`. Each platform record binds account/run UUIDs,
provider mode and authoritative-missing reason, cursor-wrap/off-page exact
refresh counts, the first/second/confirmed/rediscovered run sequence, transient
failure counters, replay zeros, latest revision and its raw file. Projection
state must put all six named projections at the newest collector revision;
duplicate counts must all be integer zero. The sealer rejects extra keys,
floats masquerading as integers, local/test namespaces or databases,
placeholder approvals, stale/future timestamps and any Flyway history other
than the frozen successful V1-V8 set.

After an independent reviewer has checked that the raw captures really came
from the controlled live-provider shadow run and recorded approval in the
external change system, seal a new report from the canonical active release:

```bash
release_path="$(readlink -f /opt/m-ranked/current)"
evidence_root=/var/lib/m-ranked/release-gates/collector-parity
source_path="$evidence_root/source-RELEASE-APPROVAL-UTC.json"
report_path="$evidence_root/collector-parity-RELEASE-APPROVAL-UTC.json"

rtk sudo /bin/bash -p \
  "$release_path/operations/bin/collector-parity-evidence" seal \
  --source "$source_path" \
  --output "$report_path" \
  --evidence-root "$evidence_root" \
  --active-release-link /opt/m-ranked/current \
  --install-root /opt/m-ranked/releases \
  --deploy-report /var/lib/m-ranked/deploy-reports/current.json \
  --operator "$OPERATOR_ID" \
  --approval-ticket "$COLLECTOR_PARITY_APPROVAL_TICKET" \
  --source-namespace "$MIGRATION_SOURCE_NAMESPACE" \
  --max-age-seconds "$COLLECTOR_PARITY_MAX_AGE_SECONDS"
```

Replace `RELEASE`, `APPROVAL` and `UTC`; every output path must be new. The
command writes mode-`0600` report v1 plus a mode-`0600` sibling `.sha256` and
never overwrites either. It derives release ID, deploy-report digest,
`SHA256(SHA256SUMS)`, deploy time/ticket and exact symlink/Flyway identity from
the active tree. `cutover-preflight.sh` invokes `verify` from that same canonical
release and checks freshness, raw evidence, active link and deploy binding
again. The old unversioned four-boolean JSON is rejected.

This tool is a sealer/verifier, not an oracle: it validates artifact integrity
and declared invariants but does not contact PostgreSQL or providers and an
unkeyed SHA-256 sidecar is not authentication. The evidence directory, host
clock, deploy report and external approval system must be trusted, and the
independent reviewer remains responsible for the truth of the captured
provider/SQL facts. Unit tests and fabricated raw text are never acceptance
evidence.

Any feed omission treated as missing, threshold below two, cursor advance after
rollback, lost historical row, duplicate identity/snapshot, or leakage of an
exception/credential is a fail. Keep Writer Gate W blocked until this strict
collector report, the production-like PG-to-legacy rehearsal and every other
cutover gate pass. The active-release preflight runs under the shared fixed
FD 8 transition lock; concurrent deploy/cutover attempts fail closed instead
of verifying or executing a collector wrapper from a moving/stale release.
