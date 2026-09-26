# Benchmarks

## Анализ аномальной динамики v2

Дата: 2026-09-23 · статус: `local`, Apple Silicon, Python 3.14.7, numpy 2.4.6.

```bash
.venv/bin/python benchmarks/anomaly_throughput.py --sample 3000 \
  --json benchmarks/results/2026-09-23-anomaly-throughput.json
```

Популяция — 29 000 активных постов с равномерным возрастом в окне 30 суток
(Telegram 40 %, ВК 35 %, MAX 15 %, RuTube 10 %), ряды до 1 200 точек с шагом
сбора по возрасту, 5 % постов с линейной подачей. Нагрузка считается по
таблице расписания, стоимость анализа — на стратифицированной выборке из
3 000 постов при зрелой норме площадки.

| Показатель | Значение | Бюджет (план, раздел 11) |
|---|---:|---:|
| Нужно анализов в час | 14 982 | ~17 000 |
| Расчёт на пост, p50 / p95 | 7,45 / 11,36 мс | ≤ 50 мс вместе с чтением |
| из них подготовка ряда, p95 | 1,19 мс | |
| из них детекторы, p95 | 10,25 мс | |
| из них сборка уровня, p95 | 0,02 мс | |
| Средняя загрузка | 0,023 ядра | ≤ 0,2 ядра |
| Пиковая память процесса | 136 МБ | ≤ 384 МБ |

Стоимость растёт с возрастом поста вместе с числом точек: 1,9 мс в первые
сутки, 8,4 мс на 7–30 сутках. Даже при плановых 17 000 анализах в час
расчёт занимает меньше 0,05 ядра. Чтение рядов не измерено — для него нужен
стенд PostgreSQL; на него остаётся около 38 мс из 50 на пост.

Машиночитаемый результат —
[`results/2026-09-23-anomaly-throughput.json`](results/2026-09-23-anomaly-throughput.json).
Прежний бенчмарк `analyze_python.py` удалён вместе с кодом, который он мерил;
его результат `results/2026-09-16-python-current.jsonl` оставлен как история.

## Collector phase scheduler

Run the deterministic 24-hour capacity simulation and bounded idle-wait probe:

```bash
.venv/bin/python benchmarks/collector_phase.py
```

The 2026-09-19 result is stored in
[`results/2026-09-19-collector-phase.json`](results/2026-09-19-collector-phase.json).
Both p50 and conservative profiles produced zero overlap and every platform ran;
the conservative profile distributed the three short-period platforms evenly
(`70/70/70`) and ran Rutube 25 times.  Lag/coalescing confirm that the desired
five-minute cadence is over capacity under strict serialization.  The idle
probe used four waiting coroutines in one process, so its 31.9 MiB RSS is not a
four-process production RSS measurement; production cgroup RSS remains a
rollout observation.  Persistence was not changed: the existing 100-publication
fixture remains 24 SQL calls with one set-based statement per major entity.

## Transfer sealing

With disposable PostgreSQL and both test DSNs configured, run:

```bash
.venv/bin/python benchmarks/transfer_sealing.py
```

The probe excludes fixture setup and delivery, alternates six first-observation
account batches with transfer disabled/enabled, and counts connection- and
cursor-level SQL calls. Sealing adds exactly one round trip per account batch:
22 before, 23 after. The absolute numbers dropped by four when the CSV
materialization was retired; the sealing delta itself is unchanged. Results are
stored beside the other probes, see
`results/2026-09-21-transfer-sealing.json`; the wall-clock medians move inside
run-to-run noise on a laptop and are not an acceptance criterion.

## Shared response cache

Run against a disposable real Redis (database 15 is flushed by the probe):

```bash
.venv/bin/python benchmarks/response_cache.py \
  --redis-url redis://127.0.0.1:56379/15 \
  --samples 500 --entries 256 --payload-bytes 4096
```

The 2026-09-21 Apple Silicon / Python 3.14.7 / Redis 8.10.0 run measured LRU
versus Redis hit p50 at 0.000375 versus 0.541249 ms and miss+fill p50 at
0.000666 versus 1.039813 ms. Warming one of four workers produced 25% first-wave
hits with isolated LRUs and 100% with Redis. Allocation/server-memory estimates
for 256 4-KiB values were 4,491,520 versus 1,452,256 bytes with four workers;
at one worker LRU was both faster and smaller. Full methodology, p95 values and
the decision are recorded in ADR-011. Output is intentionally not committed as
a generated result artifact.

## Collect and persist ceilings

```bash
.venv/bin/python benchmarks/collect_persist_split.py
```

Pure simulation of a day: no database, no provider. It answers what raising
`COLLECTOR_COLLECT_CONCURRENCY` buys in cadence and what it costs in waiting
for the exclusive write lock. Results in
`results/2026-09-22-collect-persist-split.json`; the write overlap is 1 at
every ceiling, which is the invariant the split exists to preserve.
