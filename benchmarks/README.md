# Benchmarks

Date: 2026-09-16 · commit `b242378` · status: `local preliminary`

Run the deterministic current-Python Analyze probe from repository root:

```bash
for points in 256 1024 4096; do
  .venv/bin/python benchmarks/analyze_python.py \
    --points "$points" --warmup 3 --repetitions 20
done
```

Measured on Apple Silicon, Python 3.14.7:

| Points/metric | p50 ms | p95 ms | publications/s | peak Python allocation |
|---:|---:|---:|---:|---:|
| 256 | 11.982 | 12.170 | 83.619 | 869,738 B |
| 1,024 | 47.438 | 48.559 | 21.014 | 3,458,048 B |
| 4,096 | 190.805 | 195.491 | 5.224 | 14,000,646 B |

Machine-readable output is committed at
[`results/2026-09-16-python-current.jsonl`](results/2026-09-16-python-current.jsonl).

Fixture is deterministic, four metrics, exact UTC observations, bounded disorder and periodic
jumps. Latency sample excludes allocation tracing; one separate traced run supplies peak bytes.
This is not a production or C++ comparison. A C++ compiler was unavailable locally, and no
production CPU hot path justified a native spike. Future comparison must use the same Linux
host/cgroup, serialized fixture/golden output, release flags, ≥30 runs, malformed/null/extreme
cases, RSS/startup/image size, sanitizers and fuzzing.

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
26 before, 27 after. Results are stored beside the other probes, see
`results/2026-09-21-transfer-sealing.json`; the wall-clock medians move inside
run-to-run noise on a laptop and are not an acceptance criterion.
