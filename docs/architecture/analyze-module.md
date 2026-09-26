# Analyze module and capacity isolation

> Документ описывает модель v1 и сохранён как история. Анализ v2 — [ADR-014](adr/ADR-014-anomaly-analysis-v2.md)
> и [описание методов](../research/anomaly-methods-v2.md).

Дата: 2026-09-16 · commit `b242378` · статус `code contract validated; production worker inactive`

## Existing boundary

Snapshots enqueue one durable candidate per publication; claims use lease + `SKIP LOCKED`,
history extraction is bounded, and success/failure publication is atomic. Detectors are
registered independently with stable IDs/versions (`anomaly_analysis/registry.py:11-40`).
Manifest, preprocessing and aggregation versions participate in reproducibility
(`anomaly_analysis/config.py:81-112`; `anomaly_analysis/coordinator.py:166-186`).

Production gap: 60,196 candidates, 0 attempts, and metrics function drift. Migration 0027
repairs the function locally but is not applied to production.

## Target contract

Detector input: versioned feature bundle `{publicationId, sourceRevision, featureSchema,
metricSemanticsVersion, capabilityVersion, ordered observations, quality flags}`. Output:
`detectorId`, implementation/model/rule version, manifest hash, score or null, confidence,
severity, reason codes, evidence interval, provenance and input hash. Same input+manifest is
idempotent; a rerun may create a new attempt but cannot duplicate active findings.

Common feature preparation remains separate from detectors. A detector cannot query collector
tables directly; it receives a bounded immutable snapshot. Adding a detector changes only
manifest/registry and analysis storage, never collector contracts.

## Scheduling and isolation

Queues: `online_incremental` > `recovery` > `replay` > `configuration_backfill`. Set explicit
concurrency and DB statement budget per class. API/SSR, DataAdapter and collectors receive
higher CPU/IO weight; Analyze is killable without stopping ingestion or reads. Scale out with
`SKIP LOCKED` workers only after DB extraction I/O is measured.

Initial canary after migration: batch 5, one worker, max 1024 points, CPU quota 0.5 on a host
with spare core. Increase one dimension at a time. Current 1-vCPU host has no safe headroom.

## Local sizing probe

On Apple Silicon/Python 3.14.7, current Python pipeline (hash + preparation + all three
detectors × four metrics) measured:

| Points per metric | p50 | p95 | Throughput | Python peak allocation |
|---:|---:|---:|---:|---:|
| 256 | 12.0 ms | 12.2 ms | 83.6 publications/s | 0.87 MB |
| 1,024 | 47.4 ms | 48.6 ms | 21.0/s | 3.46 MB |
| 4,096 | 190.8 ms | 195.5 ms | 5.22/s | 14.0 MB |

This is a deterministic engineering probe, not production capacity. cProfile shows the
linear-growth detector dominates, followed by input hashing and repeated preparation. At the
maximum bound, 60k items would be roughly 3.2 CPU-hours on this machine; typical production
history appears much shorter but its distribution was not scanned for safety.

## Proposed technical SLOs (require owner approval)

- eligible candidate p95 age <15 min steady-state, <24 h for backfill;
- incremental queue drains ≥2× peak creation rate;
- no Analyze-induced API p95 regression >10% or collector missed slot;
- expired leases 0 steady-state; unexplained failed attempts <0.1%;
- every result includes source revision, manifest hash and reason/provenance.
