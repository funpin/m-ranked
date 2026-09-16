# Production baseline

Дата: 2026-09-16  
Commit: `b242378`  
Статус: `validated in production read-only` для короткого окна; historical SLO baseline отсутствует

Raw evidence и методика: [2026-09-16 production read-only](evidence/2026-09-16-production-readonly.md).

## Host baseline

| Метрика | Компонент | Окно | Idle | Typical | Peak/sample | Единицы | Источник | Доверие |
|---|---|---|---:|---:|---:|---|---|---|
| CPU idle | host | 5 s | — | — | 2–8 | % | `vmstat 1 5` | короткий sample |
| CPU pressure some | host | avg10/60/300 | — | 71.31 | 77.80 | % stalled time | PSI | high для окна |
| I/O pressure some | host | avg10/60/300 | — | 12.76 | 13.36 | % stalled time | PSI | high для окна |
| load average | host | 1/5/15 min | — | 2.29 | 2.17 | runnable/uninterruptible | uptime | high |
| RAM used/available | host | one-shot | — | 1.2/0.76 | — | GiB | free | one-shot |
| swap used | host | one-shot | — | 0.352 | — | GiB | free | one-shot |
| filesystem used/free | root | one-shot | — | 22/7.8 | — | GiB | df | high |

Измеренный факт: host CPU насыщен, а swap активен. Гипотеза: часть I/O pressure
вызвана совместной работой collector writes, PostgreSQL и swap; подтвердить доли можно
только 24-hour cgroup/disk history или bounded eBPF/perf после согласования.

## Процессы

| Компонент | RSS/current | CPU evidence | Restart | Примечание |
|---|---:|---:|---:|---|
| Telegram collector | ~91 MiB RSS / 80 MiB cgroup | 1,775.9 CPU-s за 4,589 s uptime (~38.7% одного CPU) | 0 | активный цикл во время sample |
| VK collector | ~97 MiB | ~5.4% среднего CPU со старта unit | 0 | — |
| MAX collector | ~77 MiB | ~5.7% | 0 | — |
| Rutube collector | ~62 MiB | ~6.1% | 0 | cycles регулярно дольше interval |
| collectors slice | ~297 MiB | 38–60% в двух cgtop samples | — | 34 tasks |
| PostgreSQL container | 291–512 MiB charged | 10–26% в samples | healthy | limit 512 MiB, 0.65 CPU |
| Next.js container | 157–174 MiB | 0–8.7% sample | 0 | limit 384 MiB |
| FastAPI | 88–95 MiB | <1% sample | 0 | 7 tasks |
| Analyze | 0 | 0 | — | inactive/dead |

Проценты со старта — производные `CPUUsageNSec / unit uptime`, а не percentile.

## Collector baseline, последние 24 часа

| Platform | Runs success/partial | Cycle p50/p95/max, s | Account success/fail | Account p50/p95/p99, s | Snapshots | Вывод |
|---|---:|---:|---:|---:|---:|---|
| Telegram | 237/40 | 93/606/929 | 18,519/47 | 8.28/18.95/50.34 | 91,009 | intermittent long/partial cycles |
| VK | 284/3 | 134/173/242 | 19,382/3 | 5.09/7.91/10.10 | 242,090 | укладывается в 300 s |
| MAX | 260/13 | 93/178/185 | 17,907/24 | 0.69/1.15/1.83 | 112,342 | укладывается |
| Rutube | 12/128 | 589/750/963 | 8,592/593 | 33.61/58.38/86.82 | 9,927 | p50 почти 2× interval; 91% cycles partial |

Факт из конфигурации: production задаёт общий interval 300 s; entrypoint выбирает
его раньше platform-specific default (`collector_target/__main__.py:145-150`).

## PostgreSQL baseline

Окно статистики — примерно 8.53 d с `stats_reset`.

| Метрика | Значение | Производная/ограничение |
|---|---:|---|
| Database | 11.58 GB | catalog size at 01:43 UTC |
| WAL | 175.56 GB | ≈20.6 GB/day; cumulative since reset |
| Temp | 125.86 GB / 9,450 files | ≈14.8 GB/day; query attribution unavailable |
| Buffer hit | 95.2% | `hits/(hits+reads)`; не latency и не OS cache ratio |
| Requested checkpoints | 185 of 2,579 | 7.2%; remaining timed |
| Deadlocks | 14 | query/workload attribution unavailable |
| Connections | 15/30 | 13 idle, 2 active at sample |
| Waiting locks | 0 | one-shot |
| Replication clients | 0 | no standby connected |
| WAL archive | 0 success / 0 fail | archive not active |

## API/SSR/Analyze gaps

Нет исторических latency/error/throughput series; поэтому p50/p95/p99 API/SSR не
выдумываются. Один curl не заменяет representative baseline. Analyze benchmark локально
описан в `benchmarks/README.md`; production cost отсутствует, потому что worker inactive.

