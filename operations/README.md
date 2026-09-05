# M-Ranked target operations

These artifacts install beside the legacy runtime; they do not replace or edit
anything in `deploy/`. Target unit names start with `m-ranked-target-`, so the
legacy `m-ranked-web.service` and `m-ranked-collector.service` remain available
throughout the rollback window.

The operational order is:

1. prepare independent Unix users, database roles and credential files;
2. stage and activate API/Web plus the continuous projection publisher in
   shadow mode;
3. verify encrypted base backup, continuous WAL and an isolated restore;
4. move only explicitly accepted read routes through the Nginx strangler;
5. perform S-final and writer cutover only when both Writer Gate W reports pass,
   including a fresh checksummed strict-v3 production-like reverse-sync report
   bound to the active release, namespace, operator and dedicated approval
   ticket and a fresh strict collector-parity v1 report bound to protected raw
   captures, the same active deploy/Flyway identity and its own external
   approval; after S-final, adapter preflight must verify the live state-v3
   journal and its exact S-final binding before target writers start;
6. run the shipped PostgreSQL-to-legacy projection throughout the bounded
   window and keep legacy recoverable for the full 72 hours.

Runbooks:

- [`DEPLOY.md`](runbooks/DEPLOY.md) — users, credentials, release packaging,
  shadow deployment and target units;
- [`BACKUP_RESTORE.md`](runbooks/BACKUP_RESTORE.md) — encrypted GFS backups,
  continuous WAL, restore verification and quarterly PITR drill;
- [`DR_STANDBY.md`](runbooks/DR_STANDBY.md) — PostgreSQL 18.6 asynchronous
  standby bootstrap, archive fallback and lag evidence;
- [`CUTOVER.md`](runbooks/CUTOVER.md) — operator gates and reversible strangler
  phases;
- [`ROLLBACK.md`](runbooks/ROLLBACK.md) — rollback triggers and safe ordering.
- [`COLLECTOR_PARITY.md`](runbooks/COLLECTOR_PARITY.md) — bounded historical
  refresh/deletion rehearsal and Writer Gate W evidence contract.
- [`pg-to-legacy-sync.md`](interfaces/pg-to-legacy-sync.md) — reverse projection
  commands, state v3, identity/alias rules and strict v3 rehearsal
  evidence/release-binding schema.

`operations/cold_archive/` has a separate owner. These files neither edit nor
invoke its implementation; archive-before-partition-drop remains an independent
gate.

## Local validation status

Every shell script is checked with `bash -n`, executable bits are part of the
working tree, and env/Nginx files are scanned for committed credentials.
The projection publisher must additionally pass its `--once` smoke against a
disposable V8 PostgreSQL database under the `maintenance` role.
`systemd-analyze`, `nginx`, `shellcheck`, `pgbackrest`, `pg_basebackup` and
`pg_verifybackup` are not installed in the current macOS workspace, so their
host-native checks cannot be claimed here. No cached Nginx container image is
available for an offline substitute. The deploy preflight requires the native
checks on the production-like Linux clone before any routing or writer change.

The repository now contains the PG-to-legacy implementation, state-v3 journal,
systemd worker and disposable-PostgreSQL round-trip test. A local passing proof
is retained at
`migration/reports/reverse-sync-rehearsal-v8-local-v3.json`; it is explicitly local
evidence, not production approval. New report generation defaults to
`environment=disposable-postgresql-integration` with non-approvable local
release/operator/ticket placeholders. Production classification additionally
requires a canonical immutable `MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT`; the
producer verifies it is executing from that root and derives release ID/hash
from its exact `SHA256SUMS`. The remaining explicit bindings are documented in
`pg-to-legacy-sync.md`, and preflight hardcodes the required environment to
`production-like`. Writer Gate W remains closed until this exact active release
has a fresh checksummed v3 report in the machine-enforced schema and the
independently reviewed four-provider collector report sealed/reverified by the
active release. The collector tool validates integrity and declared invariants,
not the truth of provider/SQL captures; that truth and approval remain external
human gates. Leave
`COMPATIBILITY_SYNC_READY=false` until both exist.

Release identity includes the required `SYMLINKS.sha256` raw-target inventory,
which is itself covered by `SHA256SUMS`; deploy and cutover recompute it so an
internal pnpm/Next link cannot be added or retargeted without invalidating the
release provenance.

Deploy, cutover preflight, routing, writer cutover and rollback are serialized
for their complete operation by the fixed root-owned mode-`0600`
`/run/lock/m-ranked-transition.lock` on inherited FD 8. Contention and forged
inheritance fail closed; there is no emergency or environment bypass. Except
for the root-owned pre-activation deploy artifact, operational entrypoints and
nested siblings must resolve from the canonical active release. Previously
installed entrypoints that predate this guard cannot join the lock
retroactively and must be prohibited during rollout.

The reverse worker currently uses `migration_bridge` because frozen Flyway
V1-V8 has no dedicated reverse-sync role. That role is broader than the required
read set plus alias insert, so least privilege remains a recorded residual risk.
Do not silently substitute `api_read` (it cannot reserve aliases) or expand the
frozen migration set; use the hardened unit/private credential for the bounded
window and address a narrow role in a separately reviewed future migration.
