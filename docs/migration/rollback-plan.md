# Rollback plan

Дата: 2026-09-16 · commit `b242378` · статус `draft; not production-drilled`

## Triggers

Rollback the active increment when any occurs: unexplained data mismatch/loss; API p95 >10%
above approved same-load baseline for 10 min; error rate +0.5 percentage point; collector misses
two slots; waiting DB lock >30 s; swap growth/OOM; disk >85%; transfer oldest backlog violates
SLO; checksum/schema errors repeat; or restore/replay cannot reconcile cursors.

## Order

1. Stop only the new consumer/worker or set its feature flag to off; collectors and API remain.
2. Preserve inbox/outbox, logs and cursor values. Do not delete or reset watermarks.
3. Return producer route to local inbox/current direct transaction.
4. Wait for in-flight lease expiry; compare produced, ACK and applied cursors.
5. Switch `/opt/m-ranked/current` to the recorded previous release and restart only affected
   unit. Schema additions remain because they are backward compatible.
6. Replay from last mutually confirmed cursor and run differential/count checks.
7. Reopen only after the invariant ledger accounts for every batch/event.

0027 rollback is normally a forward fix, because restoring its old body restores a call to an
object that no longer exists. If application rollback requires old publication-barrier semantics,
restore both functions in one reviewed transaction; never restore only the broken body.

Analyze rollback is `systemctl stop` plus lease expiry—no canonical data rollback. Transfer
rollback retains raw/outbox/inbox rows and changes routing; ReadyDB restore must be followed by
replay from a safe cursor as described in `backup-restore-replay.md`.

