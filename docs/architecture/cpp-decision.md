# ADR: C++ candidates

Дата: 2026-09-16 · commit `b242378` · статус `decision: do not port yet`

## Verdict

No component is approved for C++ migration. The measured production limiting resources are a
single saturated CPU, PostgreSQL/temp/WAL I/O, a mis-scheduled Rutube collector, and inactive
workers—not a demonstrated Python hot loop. Adding C++ before fixing these would not restore
Analyze/outbox or disk headroom.

| Candidate | Workload | Evidence | Decision |
|---|---|---|---|
| FastAPI | DB/network wait, bounded SQL, one event loop | low API CPU in sample; no latency attribution | leave Python |
| Collectors | provider I/O + transactional per-account writes | CPU exists, but no function-level production profile; Rutube scheduling defect explains continuous work | optimize schedule/DB first |
| Canonical normalization/JSON | per provider batch | no measured share or representative byte distribution | profile before spike |
| Analyze preprocessing/hash | deterministic CPU + allocations | local 4×4096 probe 190.8 ms, 14 MB; worker inactive | optimize Python/reuse preparation, isolate worker |
| Linear-growth detector | CPU-heavy bounded windows | largest local cProfile share | only plausible future native worker/extension candidate |

## Decision threshold

A native spike becomes justified only if, after Python optimization and isolation, Analyze is
the limiting resource at 2×/5× and either (a) CPU-seconds/1k publications fall by at least 2×,
or (b) peak RSS falls at least 30%, with identical golden/fuzz results. Compare release builds
on the same Linux CPU/cgroup and dataset for ≥30 repetitions. Include startup, image size,
symbols, sanitizers, SBOM/CVE workflow and on-call complexity.

The local host cannot currently compile C++ because the Xcode license is not accepted; no
toolchain was installed or host setting changed. More importantly, a C++ benchmark now would
target an unproven bottleneck. `benchmarks/analyze_python.py` establishes the Python side for
a later same-hardware comparison.

If the threshold is met, prefer a separate C++ Analyze worker behind the versioned feature
contract. Do not replace FastAPI or provider adapters. The fallback is the Python worker using
the same lease/idempotency protocol; canary/shadow outputs must match before cutover.
