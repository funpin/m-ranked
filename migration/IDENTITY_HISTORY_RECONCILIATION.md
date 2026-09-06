# Independent account history reconciliation

`s_final` now requires `canonical_identity_history` in the same repeatable-read
transaction as canonical and projection reconciliation. `reconcile` and `import`
can also request it earlier with `--verify-identity-history`. A verifier error,
missing authority or unequal timeline is critical and makes the overall gate fail.
Both cutover preflight and the fresh writer-cutover report require this proof,
bound to the exact current SQLite SHA and PostgreSQL dataset revision.

Supply earlier frozen imported files with repeatable `--historical-source PATH`.
The current file is implicit. Approved `--preserved-source` files are also
available to this verifier. It verifies each file SHA against the namespace's
import records, rejects sidecars and checks every SHA again after scanning.
Every distinct source SHA with a committed account stream requires its original
artifact, even if only unrelated fields changed. Absence of closed target rows
cannot prove absence of prior transitions and never authorizes substituting the
current source for an unknown earlier artifact.

`writer-cutover.sh --confirm WRITER-CUTOVER:<ticket> --historical-source
/var/lib/m-ranked/snapshots/S0.sqlite3 --historical-source
/var/lib/m-ranked/snapshots/catch-up.sqlite3` forwards explicit inputs. Files must
be regular, root-owned, singly linked direct children of `MIGRATION_SNAPSHOT_DIR`,
with a protected directory chain. It does not search for or silently approve
unlisted historical files. Validation happens before writer-freeze.

The independent replay reads username, title, HTTP(S) URL and native ID directly
from SQLite and original target input receipts. Committed revision order and
recorded capture/acceptance timestamps provide transition control information;
stored migration row hashes, audit after-state and history rows never supply
expected values. It reconstructs initial validity, close/open
boundaries, clear-ID gaps, reenrollment, Telegram mirror/channel order and replay
of an older accepted batch. Actual `account_identity_history` and
`account_external_identity` rows are compared in full, including validity times,
verification time, namespace and source-run provenance. Generated surrogate IDs
are not source facts; ordinal account timeline keys detect missing/extra rows.

Expected history and external digest sorting use private temporary SQLite files
with a 2 MiB page cache. Limits are 64 artifacts, 5,000 accounts, 100,000 committed
events, 1,000,000 account operations and 250,000 history transitions. Exceeding a
limit is a classified failure, never a partial pass. Each original input object
is limited to 128 KiB. V28 grants `migration_bridge` SELECT on the existing
immutable `catalog_command_receipt`; it adds no table or public raw grants.

## Authority boundary

All producers and the bridge use `MRANKED_IDENTITY_RECEIPT_DIR`. The API writes
only `admin/<request_digest>.json`; each collector writes only
`collector/<platform>/<sha256>.json`. Provision the root and isolated writer
subdirectories as described in [IDENTITY_RECEIPTS.md](../operations/runbooks/IDENTITY_RECEIPTS.md).
Private stores use regular 0400 files in 0700 directories. Explicit shared
stores use 0440 files in writer-owned 2750 directories, inheriting the dedicated
reader group; file owner and group must match that directory. Writers are not
members of the shared reader group. Group/world writes, access by others,
unprovisioned group-readable modes and symlinks fail closed. Existing private
objects can be adopted through a fenced owner/group/mode change with identical
bytes and hashes; producers never silently change existing objects' permissions.
Publication never
replaces a file and fsyncs the object and directory entries before PG commit.
A filesystem failure aborts the command/batch; rolled-back orphan objects do not
become authority because readers enumerate committed database bindings only.

The Java command producer records the original SQL input envelope
`{action,target,expected,body}` with the exact existing PostgreSQL JSONB digest
encoding. The immutable command receipt binds that digest to actor, correlation,
outcome, acceptance time, allocated target ID and revision. Its response state
and the audit before/after images are never expected identity values. Identical
input across actors/correlations safely reuses one file. Failed commands have no
accepted revision to replay.

Collectors retain only the original identity fields and their account/run/time/
source-fingerprint binding. This excludes subscriber metrics and provider raw
payloads. The receipt hash is committed in ingestion revision metadata; matching
immutable account observations establish source-fingerprint binding. Provider
raw evidence keeps its independent short retention. Receipts have no raw-payload
expiry: removing them before the identity history loses its verification inputs.
For pre-protocol observations, a still-retrievable, hash-verified original raw
object can supply the same input; missing or expired authority fails closed.

The replay merges migration, collector and accepted administrative events in
revision order. It preserves collector absent-field semantics, URL validation,
admin native-ID clear/re-enroll gaps, exact close/open times and source-run
provenance. A stale collector account reference cannot revert an absent field
over a newer accepted identity observation. Unsupported or unexplained history
still fails; an owner-authored JSON file without a committed digest is never
accepted as authority.

V29 makes administrative native-ID transitions later than every accepted open
or closed boundary. A future provider observation followed by clear and
reenrollment therefore remains chronological. The independent replay applies
the same source-event rule. Collectors retain their original observation time:
an observation at or before a closed native interval is rejected atomically,
recorded as a failed collection, and can be retried with a genuinely newer
provider timestamp. Existing accepted values and metric facts survive rejection.

The bounded reverse window admits verified identity edits to already-bound
accounts (`account.upsert` and `account.native_id`), including authoritative
clearing. Other configuration/topology changes remain an explicit rollback
preflight rejection. This does not disable those application commands outside
the rollback contract. [Reverse-sync](../operations/runbooks/ROLLBACK.md) and
the receipt runbook describe operational inputs and scope.

## Verification

`tests/test_identity_history_postgres.py` uses an actual fresh Flyway V1–V29
database, including the `migration_bridge` role. Fourteen rolled-back superuser
faults bypass write guards and corrupt closed values, interval edges, provenance,
verification time, or insert/delete history rows. Each fails both the standalone
oracle and the overall required reconciliation without rebuilding projections.
Clear/re-enroll/replay and mandatory S_final are positive cases; absent prior
artifacts and unknown authority fail closed. `tests/test_identity_history_release_gate.py`
exercises the actual jq release predicate, explicit CLI inputs and writer wiring.

The same PostgreSQL test now proves original collector receipts after actual
provider evidence expiry, retained-field semantics with a stale account handle,
and missing/forged receipt rejection. `IdentityCommandPostgresIntegrationTest`
uses actual Java catalog commands in isolated clean V1–V29 and populated
V28→V29 databases: original S_final, a future collector observation,
username/title/HTTP URL changes, native changes, clear and reenrollment,
reverse drain/verify/stop, a second required S_final and a fresh no-op repeat.
The upgrade case first proves the old chronological defect in a rolled-back
command, then checks that V29 leaves every prior history row unchanged. Both
cases reject older and equal collector timestamps without any canonical change,
verify recorded failure, and accept an unchanged, newer provider timestamp.
It verifies command rollback, idempotency and failure before durable publication.
It also restores exact input files into another protected root, makes the
original root unavailable, and requires complete reconciliation from the copy;
missing/corrupt restored inputs are NO-GO. The collector/HTTP reverse rehearsal
independently exercises true second S_final with its explicit original artifacts.
