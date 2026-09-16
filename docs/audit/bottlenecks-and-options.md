# Bottlenecks and options

Дата: 2026-09-16 · commit `b242378` · статус `draft from production read-only evidence`

| Priority | Симптом/effect | Evidence и первопричина | Изменение | Ожидаемый эффект | Risk/reversibility |
|---|---|---|---|---|---|
| P0 | Analyze не выполняет ни одной задачи; backlog 60,196 | unit inactive; 0 attempts; deployed metrics function вызывает удалённую function | применить `0027_anomaly_metrics_live_revision.sql`, smoke-test function, затем отдельным согласованием запустить worker с batch 5 | восстановление контролируемой обработки; throughput измерить | low DDL risk, `CREATE OR REPLACE`; откат старого тела запрещён, stop worker мгновенный |
| P0 | Outbox 178,339 pending, oldest >3 d | API marker не догоняет/не настроен; production unit отличается от repo | проверить DSN role и warning log; canary marker batch; затем bounded purge delivered | устранить рост 160 MB и вернуть cache-delivery health | запуск/repair только по согласованию; stop API marker rollback |
| P0 | 7.8 GiB free при БД 11.58 GB и ≈0.3–0.5 GB/day observed growth | September partitions уже 5.18 GB вместе с reactions; три local dumps ≈3 GB | добавить capacity alert; подтвердить cold archive; расширить disk до 100 GB до backlog/replay | исключить near-term ENOSPC | disk extension reversible operationally; purge без verified archive запрещён |
| P1 | CPU очередь и I/O pressure на 1 vCPU | PSI CPU 64–78%; collectors 38–60% sample; PG 10–26% | дать минимум 2, лучше 4 vCPU; разнести Rutube interval; Analyze держать paused до исправлений | latency/freshness headroom, меньше overlap | scheduling config reversible |
| P1 | Rutube perpetually overruns | 300 s global interval против cycle p50 589/p95 750; 91% partial | platform-specific interval ≥ p95 + jitter, initial proposal 900 s; retry/errors отдельно | убрать бесконечный catch-up и CPU churn; freshness станет предсказуемой | requires owner acceptance of freshness threshold |
| P1 | Нет query ranking, 126 GB temp I/O | `pg_stat_statements` absent, `track_io_timing=off` | staging first; production enable only in approved change window | attribution of temp/WAL/DB CPU | extension/config change requires explicit approval |
| P1 | Backup только в том же failure domain | local dump exists; no WAL archive, replica or verified restore evidence | external encrypted repository + restore drill | measurable RPO/RTO rather than file existence | operational project; no deletion of local dump until accepted |
| P2 | Deployment drift | service names/limits differ between repository and production | inventory + converge units in a canary release | reproducible limits and rollback | unit reload/restart requires approval |
| P2 | Analyze CPU hot path | local max-bound probe: 190.8 ms/publication at 4×4096 points; linear detector dominates profile | first remove repeated preprocessing and bound detector windows; benchmark on Linux | likely Python improvement without new toolchain | no production relevance until worker runs |
| P3 | C++ complexity without measured production CPU deficit | collectors are network/DB coupled; API is I/O-bound; Analyze inactive | do not port now; reconsider only after isolated Linux profile at 2×/5× | avoids second toolchain/CVE/on-call burden | fully reversible decision |

## Causal map

`global 300 s schedule` → `Rutube cycle > interval` → `continuous collector work` →
`collector + PostgreSQL contention on 1 vCPU` → `CPU queue + swap/I/O pressure` →
`no safe headroom for Analyze/backfill`.

Separately, `live-read delta removed function` → `stale metrics function` →
`operational_snapshot fails before claim` → `Analyze attempts=0` → `60k backlog`.

## Go/no-go for first remediation

Go only after a fresh backup exists and `0027` is reviewed. Gate: metrics function returns
all ten bounded keys under 5 s; no table rewrite/lock wait; API remains ready. Start Analyze
with batch 5 only after CPU has at least 30% headroom for 15 minutes. Stop it if API p95
exceeds accepted baseline by >10%, collector freshness misses two slots, swap grows, or DB
CPU is saturated for 5 minutes.
