#!/usr/bin/env python3
"""Deterministic CPU/allocation probe for the packaged Analyze hot path."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import resource
from statistics import median
import sys
import time
import tracemalloc
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anomaly_analysis.config import default_manifest
from anomaly_analysis.coordinator import analysis_input_hash
from anomaly_analysis.domain import Metric, MetricObservation, ObservationQuality, PublicationHistory
from anomaly_analysis.preprocessing import prepare_metric
from anomaly_analysis.registry import DetectorRegistry


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(points: int) -> PublicationHistory:
    series = {}
    for metric_index, metric in enumerate(Metric, 1):
        value = metric_index * 100
        rows = []
        for index in range(points):
            value += 1 + ((index * metric_index) % 5)
            if index and index % 257 == 0:
                value += 80
            rows.append(MetricObservation(
                f"{metric.value}-{index}", BASE + timedelta(seconds=index * 300),
                index * 300, value, ObservationQuality.EXACT,
            ))
        # Extraction is ordered in production; reverse a bounded fraction so the
        # benchmark still covers the normalizer's ordering guarantee.
        series[metric] = tuple(rows[:-32] + list(reversed(rows[-32:])))
    return PublicationHistory(
        UUID("10000000-0000-0000-0000-000000000001"),
        UUID("20000000-0000-0000-0000-000000000002"),
        UUID("30000000-0000-0000-0000-000000000003"),
        "telegram", BASE, "complete", 1, BASE + timedelta(days=1), 1, 1,
        series, expected_sampling_seconds=300,
    )


def run_once(history: PublicationHistory) -> int:
    manifest = default_manifest()
    digest = analysis_input_hash(history, manifest.sha256)
    prepared = {
        metric: prepare_metric(history.series[metric], max_points=len(history.series[metric]))
        for metric in history.supported_metrics
    }
    outcomes = 0
    for detector in DetectorRegistry.from_manifest(manifest).detectors:
        for metric in detector.metadata.supported_metrics & history.supported_metrics:
            detector.evaluate(history, metric, prepared[metric])
            outcomes += 1
    return outcomes + len(digest)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=1024)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if not 8 <= args.points <= 4096 or args.warmup < 0 or args.repetitions < 3:
        raise SystemExit("points must be 8..4096 and repetitions at least 3")

    history = fixture(args.points)
    for _ in range(args.warmup):
        run_once(history)

    timings = []
    cpu_start = time.process_time()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(args.repetitions):
        started = time.perf_counter()
        run_once(history)
        timings.append(time.perf_counter() - started)
    cpu_seconds = time.process_time() - cpu_start
    wall_total = sum(timings)

    # Allocation tracing is deliberately outside the latency sample: tracemalloc
    # changes execution time materially and is used only for a comparable peak.
    tracemalloc.start()
    run_once(history)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports KiB.
    rss_delta_bytes = max(0, rss_peak - rss_start) * (1024 if sys.platform.startswith("linux") else 1)
    print(json.dumps({
        "implementation": "python-current",
        "machine": platform.machine(),
        "platform": platform.platform(),
        "pythonVersion": platform.python_version(),
        "pointsPerMetric": args.points,
        "metrics": len(Metric),
        "repetitions": args.repetitions,
        "warmup": args.warmup,
        "wallSeconds": round(wall_total, 6),
        "cpuSeconds": round(cpu_seconds, 6),
        "latencyP50Ms": round(median(timings) * 1000, 3),
        "latencyP95Ms": round(percentile(timings, 0.95) * 1000, 3),
        "throughputPublicationsPerSecond": round(args.repetitions / wall_total, 3),
        "pythonPeakAllocationBytes": peak_bytes,
        "maxRssDeltaBytes": rss_delta_bytes,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
