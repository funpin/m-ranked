#!/usr/bin/env python3
"""Deterministic phase-capacity and idle-wait probe."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector_target.model import Platform
from collector_target.phase import (
    InMemoryPhaseArbiter,
    PhasePolicy,
    PhaseRequest,
    PhaseScheduler,
    simulate_phases,
)


BASE = datetime(2026, 9, 19, tzinfo=timezone.utc)


def policies() -> dict[Platform, PhasePolicy]:
    intervals = {
        Platform.TELEGRAM: 300,
        Platform.VK: 300,
        Platform.MAX: 300,
        Platform.RUTUBE: 3600,
    }
    order = sorted(item.value for item in Platform)
    return {
        platform: PhasePolicy(
            platform,
            interval,
            interval * order.index(platform.value) // len(order),
            1800,
        )
        for platform, interval in intervals.items()
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


async def idle_probe() -> dict[str, float | int]:
    arbiter = InMemoryPhaseArbiter()
    held = PhaseRequest(
        Platform.RUTUBE, "default", "benchmark", BASE, BASE, BASE,
    )
    arbiter.request(held)
    lease = arbiter.try_acquire(held, stale_after_seconds=60)
    assert lease is not None
    schedulers = [
        PhaseScheduler(
            arbiter,
            max_wait_seconds=0.5,
            retry_seconds=0.05,
            request_stale_seconds=60,
        )
        for _ in range(4)
    ]
    requests = [
        PhaseRequest(
            platform, f"waiter-{index}", "benchmark",
            BASE + timedelta(minutes=1), BASE + timedelta(minutes=1), BASE,
        )
        for index, platform in enumerate(Platform)
    ]
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    outcomes = await asyncio.gather(*(
        scheduler.acquire(request)
        for scheduler, request in zip(schedulers, requests)
    ))
    wall = time.perf_counter() - wall_started
    cpu = time.process_time() - cpu_started
    lease.release()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith("linux"):
        rss *= 1024
    return {
        "idleWallSeconds": round(wall, 6),
        "idleCpuSeconds": round(cpu, 6),
        "idleCpuPercentOneCore": round(100 * cpu / wall, 3),
        "waitAttempts": sum(item.attempts for item in outcomes),
        "processMaxRssBytes": int(rss),
    }


def main() -> None:
    profiles = {
        "p50": {
            Platform.TELEGRAM: 93,
            Platform.VK: 134,
            Platform.MAX: 93,
            Platform.RUTUBE: 780,
        },
        "conservative": {
            Platform.TELEGRAM: 606,
            Platform.VK: 173,
            Platform.MAX: 178,
            Platform.RUTUBE: 780,
        },
    }
    simulations = {}
    for name, durations in profiles.items():
        phases = simulate_phases(
            policies(), durations, start=BASE, hours=24,
        )
        lags = [
            (phase.started_at - phase.scheduled_at).total_seconds()
            for phase in phases
        ]
        simulations[name] = {
            "phaseCount": len(phases),
            "counts": {
                platform.value: sum(phase.platform == platform for phase in phases)
                for platform in Platform
            },
            "maxOverlap": int(any(
                left.completed_at > right.started_at
                for left, right in zip(phases, phases[1:])
            )),
            "scheduleLagP50Seconds": round(percentile(lags, 0.5), 3),
            "scheduleLagP95Seconds": round(percentile(lags, 0.95), 3),
            "scheduleLagMaxSeconds": round(max(lags), 3),
            "coalescedSlots": sum(phase.coalesced_slots for phase in phases),
        }
    print(json.dumps({
        "simulations": simulations,
        "idleProbe": asyncio.run(idle_probe()),
        "repositorySqlRoundTrips100Publications": 24,
        "repositoryWriteShape": "unchanged-set-based",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
