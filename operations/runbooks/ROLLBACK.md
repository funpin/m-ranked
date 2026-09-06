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

1. atomically install `rollback-freeze` and validate/reload Nginx: public
   GET/HEAD reads use legacy, public mutations are denied and the modern admin
   API stays closed. Before progressing, wait for the verified pre-reload Nginx
   worker generation to exit, including its open connections;
2. stop the target API and all four collectors, waiting for each stop to finish;
3. stop the continuous reverse-sync worker, then run `drain` with the original
   operator/ticket while it holds every collector advisory lock;
4. fix the exact post-S-final revision set and plan hash, allocate any remaining
   positive publication/snapshot aliases, checkpoint/fsync SQLite and run
   `verify` against that same plan;
5. run `stop` only after state v3 is `verified`, then verify legacy health;
6. install the normal legacy route to reopen legacy administrative writes,
   restart the legacy collector and write an operator report.

The expected journal progression is `active -> drained -> verified -> stopped`.
Reload acknowledgement alone does not establish a write fence. The routing
helper verifies the systemd Nginx master PID, executable and process start time,
captures its worker PID/start-time identities before reload and waits for all
of those identities to exit while the same master remains alive. The default
`NGINX_FREEZE_TIMEOUT_SECONDS=30` is bounded to at most 120 seconds. Unreadable
process identities, a changed master or a timeout block progress without
killing workers or reverting the installed freeze route. Resolve the underlying
condition before retrying; an old connection may still be active while a failed
freeze remains unverified.

Repeated drain/verify/stop is safe only when S-final, legacy target identity,
revision set, positive aliases and canonical plan hash are unchanged. Preserve
the mode-`0600` v3 journal and the live SQLite file together; replacing the file
changes its path/device/inode binding and deliberately blocks the transition.

If the executable is unavailable, the journal is not v3, or drain/verify/stop
fails, the script retains `rollback-freeze`; it does not reopen administrative
writes. A failed service stop also prevents draining or proceeding to the normal
legacy route. Starting either writer without resolving that state risks split brain
and requires incident-commander approval. Never delete the journal, edit an
alias, manufacture `stopped`, or fall back to a forward-only/no-op adapter.
The web process may remain in shadow for diagnosis; target API writers remain
stopped until a separately gated transition.

After rollback, create a new verified SQLite Backup API export at a different
path and retain every original S0/catch-up/S-final artifact, the state-v3
journal, target PostgreSQL, and the original identity receipt directory. Run
that export as a **new `s_final`** with every prior source artifact supplied
through `--historical-source`; require both independent projection and complete
identity-history proofs. Repeat the same completed batch once: it must write
zero rows without advancing the dataset revision or changing canonical,
projection, alias or account history hashes. The strict reverse
publication/snapshot envelopes must resolve the same publication UUIDs,
identity-role sets and target snapshot IDs, with zero duplicate observations and
no NULL/zero drift. Do not point the old journal at the export and do not reuse
the failed cutover or rehearsal report for another attempt. Correct the fault,
rehearse again on a clone, issue a new change ticket and repeat the read-route
gates before writer cutover.

The next read-route preflight expects a running target API. Restart it in the
protected shadow configuration only after rollback has completed and its reverse
state is verified/stopped. Keep target collectors stopped and target admin
routes closed while legacy owns writes; collectors restart only through the new
Writer Gate W transition. A failed rollback is not permission to restart the API
or either collector set.

Only original-receipt-verified `account.upsert` presentation edits and
`account.native_id` changes are reversible configuration deltas. They must
address an account already bound to S-final, with the same canonical key,
institution, aliases, enabled state and access mode. Explicit native-ID clears
remain NULL after reverse; unknown collector values retain their prior value.
Other administrative or formula changes block reverse synchronization.

Keep `MRANKED_IDENTITY_RECEIPT_DIR` consistent for collectors, Java admin, bridge
and the reverse-sync environment. Provision the `2750`/`0440` reader-group
layout before cutover: `telegram-monitor` needs the unit's supplementary
`m-ranked-identity-readers` group to read each writer-owned receipt subtree.
Missing or hash-mismatched original files block drain and the next S-final;
current rows and `catalog_command_receipt.response.state` cannot substitute
for original inputs. Verify receipt recovery using `IDENTITY_RECEIPTS.md`
before reopening writers. Gate W now requires report **v4**, including both
S-final proofs, unchanged zero-write repeat and the actual HTTP/admin/collector
transition evidence. Journal format remains v3.

The frozen V1-V29 database has no dedicated reverse-sync role. Rollback therefore
uses the `migration_bridge` credential, whose grants are broader than the
adapter's required reads plus legacy-alias insert. Treat that as an explicit
least-privilege residual risk: keep the credential host-local/private, use it
only for the compatibility window, and retain the reported database/role with
the incident evidence. A future narrow role requires its own reviewed migration;
do not modify V1-V29 during an incident.

If PostgreSQL itself is damaged, use `BACKUP_RESTORE.md` to restore on a separate
host to the point before the incident. RPO target is 15 minutes and RTO target is
2 hours; an unmeasured or failed drill is a blocker, not an accepted backup.
