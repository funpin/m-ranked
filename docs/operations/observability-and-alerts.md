# Observability and alerts

Дата: 2026-09-16 · commit `b242378` · статус `draft; baseline gaps documented`

## Required series

- host/cgroup: CPU usage/throttle/PSI, RSS/peak/swap/OOM, disk bytes/IOPS/latency/queue,
  network/retransmits, restart count;
- PostgreSQL: connections, waits/deadlocks, WAL/checkpoints, temp bytes, table/index growth,
  autovacuum/dead tuples, backup/archive/replication state and bounded query ranking;
- collectors: cycle/account latency histograms, snapshots, failures/retries/rate limit, cycle
  overrun and freshness by platform;
- transfer: produced/ACK/applied cursor, rows/bytes, backlog/oldest, retry/duplicate/reject;
- Analyze: queue/eligible/oldest, batch and publication latency, attempts/outcomes, source lag,
  CPU-seconds/1k and peak RSS/job;
- API/SSR: request rate, p50/p95/p99, errors, response bytes, DB query count/time and cache hit.

## Proposed initial alerts (owner must approve)

Page: disk >90% or predicted <7 days; OOM/restart loop; collector freshness >2 scheduled slots;
transfer cursor regression/unaccounted records; backlog oldest >30 min; API 5xx >1% for 5 min;
restore verification >24 h stale. Ticket/warn: disk >70%, swap growth, CPU PSI avg10 >30% for
15 min, Rutube partial >5%, Analyze oldest >15 min after steady-state activation.

Before enabling query capture on production, review overhead and privacy. Prefer normalized
`pg_stat_statements` IDs; never export query parameters, raw payload, account IDs or DSNs.

