# Migration plan

Дата: 2026-09-16 · commit `b242378` · статус `draft; no production changes`

| Step | Prerequisite/change | Verification and go/no-go | Observation | Rollback |
|---|---|---|---|---|
| 0. Capacity safety | ≥30 GB free or disk extension; fresh backup | no disk/backup alerts | 24 h | do not start backlog work |
| 1. Repair metrics | review/apply `db/migrations/0027_anomaly_metrics_live_revision.sql` | function returns ten keys <5 s; API ready | 15 min | `CREATE OR REPLACE` prior body only if old dependency also exists; normally forward-fix |
| 2. Repair outbox | validate outbox credential/role and deployed API unit; start marker canary | pending decreases, no lock waits/API regression | 30 min | disable marker, retain rows |
| 3. Schedule collectors | remove global Rutube 300 s override; propose 900 s + jitter | no freshness breach; CPU PSI and partial rate fall | 24 h | restore exact env value and restart only Rutube |
| 4. Analyze canary | batch 5, max points 1024, CPU 0.5, low IO weight | queue decreases; API p95 ≤baseline+10%; no missed collector slots | 1 h then 24 h | stop Analyze; leases expire safely |
| 5. Observability | collect 7 d cgroup, endpoint and pg query metrics | no missing series; thresholds approved | 7 d | exporter off; no data-path effect |
| 6. Contract foundation | add raw event v1, transfer outbox/inbox in local mode | contract/idempotency/failure tests green | soak 24 h | feature flag uses current direct path |
| 7. Shadow DataAdapter | dual-write inbox output to shadow schema, compare | zero unexplained row/hash differences | ≥7 d | stop shadow consumer |
| 8. Two-server canary | mTLS push for one platform/range | no loss; ACK/apply cursor accounting exact | ≥48 h incl. link interruption | route producer to local inbox; replay |
| 9. Expand traffic | 10→25→50→100% | backlog drains ≥2× peak; resource reserves intact | ≥24 h per stage | previous percentage + replay |
| 10. Native spike, optional | only if Analyze remains limiting | ≥2× CPU or ≥30% RSS benefit and differential equality | 30+ runs + 7 d shadow | Python worker switch |

## Database migration discipline

0027 replaces only a function body: no heap rewrite, index build or table lock beyond catalog
DDL. Run with `lock_timeout=1s`, `statement_timeout=5s` in a transaction; if lock cannot be
acquired, abort and retry in a window. It remains compatible with current application code.

Future inbox/outbox DDL follows expand–migrate–contract: nullable/additive objects first,
backfill in bounded batches, dual-read/write, then constraints validated separately. Never add
a rewriting default or unmeasured index build on the 5M/8M-row partitions.

## Acceptance invariants

- accepted + duplicate + deferred + rejected = input count;
- ACK never precedes durable inbox; applied cursor never crosses an uncommitted event;
- replay has zero unexplained final duplicates/loss;
- UTC/null/Unicode/integer semantics match current characterization tests;
- Analyze stop has no effect on collect/transfer/API/SSR;
- the same contract/E2E suite passes local and remote transport profiles.

