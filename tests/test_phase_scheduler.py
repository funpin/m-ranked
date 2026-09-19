from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from collector_target.model import Platform
from collector_target.phase import (
    InMemoryPhaseArbiter,
    PhasePolicy,
    PhaseRequest,
    PhaseScheduler,
    due_slot,
    scheduled_slot,
    simulate_phases,
)


NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def request(platform: Platform, scheduled_at: datetime = NOW) -> PhaseRequest:
    return PhaseRequest(
        platform,
        "default",
        "test-v1",
        scheduled_at,
        scheduled_at,
        NOW,
    )


def policies() -> dict[Platform, PhasePolicy]:
    intervals = {
        Platform.TELEGRAM: 300,
        Platform.VK: 300,
        Platform.MAX: 300,
        Platform.RUTUBE: 3600,
    }
    order = sorted(platform.value for platform in Platform)
    return {
        platform: PhasePolicy(
            platform,
            interval,
            interval * order.index(platform.value) // len(order),
            1800,
        )
        for platform, interval in intervals.items()
    }


def test_slots_are_utc_anchored_and_missed_slots_are_coalesced() -> None:
    policy = PhasePolicy(Platform.TELEGRAM, 300, 150, 900)
    assert scheduled_slot(NOW + timedelta(seconds=149), 300, 150) == (
        NOW - timedelta(seconds=150)
    )
    assert scheduled_slot(NOW + timedelta(seconds=150), 300, 150) == (
        NOW + timedelta(seconds=150)
    )

    due, coalesced, next_due = due_slot(
        NOW + timedelta(minutes=31),
        policy,
        NOW + timedelta(minutes=2, seconds=30),
    )
    assert due == NOW + timedelta(minutes=27, seconds=30)
    assert coalesced == 4
    assert next_due == NOW + timedelta(minutes=32, seconds=30)


def test_arbiter_chooses_earliest_due_then_stable_platform_order() -> None:
    arbiter = InMemoryPhaseArbiter()
    later = request(Platform.MAX, NOW + timedelta(minutes=5))
    telegram = request(Platform.TELEGRAM)
    vk = request(Platform.VK)
    for item in (later, vk, telegram):
        arbiter.request(item)

    assert arbiter.try_acquire(later, stale_after_seconds=60) is None
    lease = arbiter.try_acquire(telegram, stale_after_seconds=60)
    assert lease is not None
    assert arbiter.active == telegram
    lease.finish("succeeded", NOW + timedelta(seconds=10))
    lease.release()
    assert not arbiter.request(telegram)

    second = arbiter.try_acquire(vk, stale_after_seconds=60)
    assert second is not None
    second.release()


def test_phase_wait_is_bounded_and_cancellable() -> None:
    arbiter = InMemoryPhaseArbiter()
    held = request(Platform.RUTUBE, NOW - timedelta(hours=1))
    arbiter.request(held)
    lease = arbiter.try_acquire(held, stale_after_seconds=60)
    assert lease is not None
    scheduler = PhaseScheduler(
        arbiter,
        max_wait_seconds=0.03,
        retry_seconds=0.01,
        request_stale_seconds=60,
    )
    acquisition = asyncio.run(scheduler.acquire(request(Platform.VK)))
    assert acquisition.lease is None
    assert acquisition.attempts >= 1
    assert acquisition.wait_seconds < 0.2
    lease.release()

    stop = asyncio.Event()
    stop.set()
    cancelled = asyncio.run(scheduler.acquire(request(Platform.VK), stop))
    assert cancelled.cancelled
    assert cancelled.lease is None


def test_unfinished_slot_can_be_reclaimed_after_lease_disconnect() -> None:
    arbiter = InMemoryPhaseArbiter()
    item = request(Platform.MAX)
    assert arbiter.request(item)
    crashed = arbiter.try_acquire(item, stale_after_seconds=60)
    assert crashed is not None
    crashed.release()

    assert arbiter.request(item)
    resumed = arbiter.try_acquire(item, stale_after_seconds=60)
    assert resumed is not None
    resumed.finish("succeeded", NOW + timedelta(seconds=1))
    resumed.release()
    assert not arbiter.request(item)


def test_24_hour_simulation_has_no_overlap_or_starvation() -> None:
    durations = {
        Platform.TELEGRAM: 606,
        Platform.VK: 173,
        Platform.MAX: 178,
        Platform.RUTUBE: 780,
    }
    phases = simulate_phases(
        policies(), durations, start=NOW, hours=24,
    )

    assert phases
    assert all(
        previous.completed_at <= current.started_at
        for previous, current in zip(phases, phases[1:])
    )
    counts = {
        platform: sum(phase.platform == platform for phase in phases)
        for platform in Platform
    }
    assert all(count > 0 for count in counts.values())
    assert max(counts[p] for p in (Platform.TELEGRAM, Platform.VK, Platform.MAX)) - min(
        counts[p] for p in (Platform.TELEGRAM, Platform.VK, Platform.MAX)
    ) <= 1
    assert sum(phase.coalesced_slots for phase in phases) > 0
