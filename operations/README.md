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
   including a fresh checksummed strict-v4 production-like reverse-sync report
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
  commands, state v3, identity/alias rules and strict v4 rehearsal
  evidence/release-binding schema.

`operations/cold_archive/` has a separate owner. These files neither edit nor
invoke its implementation; archive-before-partition-drop remains an independent
gate.

## Local validation status

Every shell script is checked with `bash -n`, executable bits are part of the
working tree, and env/Nginx files are scanned for committed credentials.
The projection publisher must additionally pass its `--once` smoke against a
disposable PostgreSQL database under the `maintenance` role.
The [identity receipt Linux rehearsal](identity_receipts/README.md) passed 13
checks using separate Java/Python writer, reverse, backup and outsider UIDs;
the related deployment and nine-projection guard suite passed 193 tests without
skips. The checked-in units now supply the dedicated read-only group to readers
while writers retain only ownership of their own `2750` receipt subdirectory.
The V29 [HTTP transition](http_transition/evidence/local-v29-final-r1/report.json)
ran actual legacy/Spring applications through all four routing phases: **835
requests, zero errors, p95 57.174 ms**, seven rejected gates and four real Java
admin commands. The second S-final completed at R111; its exact repeat wrote
zero rows without changing the revision or identity history. The
[unchanged-artifact protocol validation](http_transition/evidence/local-v29-final-r1/protocol-validation.json)
also passed the same JQ predicate used by Gate W. Its production acceptance
remains false.

The [actual Nginx rollback proof](http_transition/evidence/local-v29-nginx-r1/report.json)
also passed: 159 continuous reads, zero failures and 46 rejected mutation/admin
requests. Freeze admission waited for the old worker generation, including a
held request and prior keepalive connection. Its initial reload-race failure
remains recorded separately; deployed systemd/process ownership and production
route activation still need their own operator acceptance.

The V28 failures remain historical evidence: the first exposed inherited
CONNECT privileges and the second exposed a native-history boundary reset;
V29 corrects the latter without changing accepted earlier history. Neither
failed report is an accepted release proof. Physical DR evidence and its exact
release binding are documented separately in
[BACKUP_RESTORE.md](runbooks/BACKUP_RESTORE.md). Local rehearsals do not attest
production Linux systemd/Nginx, an off-primary pgBackRest repository, live
providers or operator approval. Those production-like checks still precede
routing or writer changes.

The repository now contains the PG-to-legacy implementation, state-v3 journal,
systemd worker and disposable-PostgreSQL round-trip test. The latest local report is
[the actual V29 round trip](http_transition/evidence/local-v29-final-r1/reverse-http.json);
older V8/V27/V28 reports remain historical evidence and are not production approval. New report generation defaults to
`environment=disposable-postgresql-integration` with non-approvable local
release/operator/ticket placeholders. Production classification additionally
requires a canonical immutable `MRANKED_TEST_REVERSE_SYNC_RELEASE_ROOT`; the
producer verifies it is executing from that root and derives release ID/hash
from its exact `SHA256SUMS`. The remaining explicit bindings are documented in
`pg-to-legacy-sync.md`, and preflight hardcodes the required environment to
`production-like`. **Production Writer Gate W remains CLOSED** until this exact active release
has a fresh checksummed v4 report in the machine-enforced schema and the
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
V1-V29 has no dedicated reverse-sync role. That role is broader than the required
read set plus alias insert, so least privilege remains a recorded residual risk.
Do not silently substitute `api_read` (it cannot reserve aliases) or expand the
frozen migration files; use the hardened unit/private credential for the bounded
window and address a narrow role in a separately reviewed future migration.
