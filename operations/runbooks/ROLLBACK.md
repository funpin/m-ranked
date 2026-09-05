# Rollback during the compatibility window

Owner: incident commander authorizes; application operator executes; data and
database operators verify reverse-sync and recovery evidence. Target data is
never deleted during rollback.

Immediate rollback triggers are a correctness/parity regression, duplicate
ingestion, target collector split brain, private cache leakage, sustained public
5xx above 1%, overview p95 above 1 second on bounded miss or 300 ms on hit,
freshness/outbox/WAL/replica lag beyond its cutover threshold, or inability to
explain a reconciliation mismatch.

Run the rehearsed rollback with the same environment and ticket:

```bash
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  set -a
  source /etc/m-ranked/cutover.env
  set +a
  release_path="$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK")"
  exec "$release_path/operations/scripts/rollback.sh" --confirm ROLLBACK:CHANGE
'
```

Rollback participates in the same exclusive root-owned
`/run/lock/m-ranked-transition.lock` as deploy and cutover. It must run from
the canonical active release, inherits FD 8 into its nested routing switch,
and holds the lock through recovery verification and the final state report.
Contention or an invalid inherited descriptor exits 75. There is deliberately
no unlocked emergency override: investigate/terminate the owning operation or
repair the fixed lock inode under incident-command authorization, then rerun
the normal rollback entrypoint.

Ordering is deliberate:

1. atomically return public routing to legacy and validate/reload Nginx;
2. stop all four target writers;
3. stop the continuous reverse-sync worker, then run `drain` with the original
   operator/ticket while it holds every collector advisory lock;
4. fix the exact post-S-final revision set and plan hash, allocate any remaining
   positive publication/snapshot aliases, checkpoint/fsync SQLite and run
   `verify` against that same plan;
5. run `stop` only after state v3 is `verified`, then restart the legacy
   collector;
6. verify legacy health and write an operator report.

The expected journal progression is `active -> drained -> verified -> stopped`.
Repeated drain/verify/stop is safe only when S-final, legacy target identity,
revision set, positive aliases and canonical plan hash are unchanged. Preserve
the mode-`0600` v3 journal and the live SQLite file together; replacing the file
changes its path/device/inode binding and deliberately blocks the transition.

If the executable is unavailable, the journal is not v3, or drain/verify/stop
fails, the script leaves both collector sets stopped after reads return to
legacy. Starting either writer without resolving that state risks split brain
and requires incident-commander approval. Never delete the journal, edit an
alias, manufacture `stopped`, or fall back to a forward-only/no-op adapter.
API/Web may remain in shadow for diagnosis.

After rollback, create a new verified SQLite Backup API export at a different
path, retain the original S-final, state-v3 journal and target PostgreSQL, and
run the forward bridge/reconciliation against that export. The strict reverse
publication/snapshot envelopes must resolve the same publication UUIDs,
identity-role sets and target snapshot IDs, with zero duplicate observations and
no NULL/zero drift. Do not point the old journal at the export and do not reuse
the failed cutover or rehearsal report for another attempt. Correct the fault,
rehearse again on a clone, issue a new change ticket and repeat the read-route
gates before writer cutover.

The frozen V1-V8 database has no dedicated reverse-sync role. Rollback therefore
uses the `migration_bridge` credential, whose grants are broader than the
adapter's required reads plus legacy-alias insert. Treat that as an explicit
least-privilege residual risk: keep the credential host-local/private, use it
only for the compatibility window, and retain the reported database/role with
the incident evidence. A future narrow role requires its own reviewed migration;
do not modify V1-V8 during an incident.

If PostgreSQL itself is damaged, use `BACKUP_RESTORE.md` to restore on a separate
host to the point before the incident. RPO target is 15 minutes and RTO target is
2 hours; an unmeasured or failed drill is a blocker, not an accepted backup.
