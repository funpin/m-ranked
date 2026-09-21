"""Collect may overlap; persist may not."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector_target.model import Platform
from collector_target.phase import (
    GLOBAL_PHASE_LEASE_NAME,
    MAX_COLLECT_SLOTS,
    NULL_PERSIST_GUARD,
    PERSIST_LOCK_NAME,
    PhasePolicy,
    PostgresPersistGuard,
    collect_slot_name,
    max_overlap,
    simulate_phases,
    simulate_split_phases,
)


START = datetime(2026, 9, 22, tzinfo=timezone.utc)

# p50 из production-аудита, разделённые на сетевую и записывающую половины.
COLLECT = {
    Platform.TELEGRAM: 84, Platform.VK: 121, Platform.MAX: 84, Platform.RUTUBE: 620,
}
PERSIST = {
    Platform.TELEGRAM: 9, Platform.VK: 13, Platform.MAX: 9, Platform.RUTUBE: 70,
}
POLICIES = {
    Platform.TELEGRAM: PhasePolicy(Platform.TELEGRAM, 300, 0, 900),
    Platform.VK: PhasePolicy(Platform.VK, 300, 75, 600),
    Platform.MAX: PhasePolicy(Platform.MAX, 300, 150, 600),
    Platform.RUTUBE: PhasePolicy(Platform.RUTUBE, 3600, 225, 1800),
}


def _day(slots: int):
    return simulate_split_phases(
        POLICIES, COLLECT, PERSIST, start=START, hours=24, collect_slots=slots,
    )


# --- the invariant ----------------------------------------------------------

@pytest.mark.parametrize("slots", range(1, MAX_COLLECT_SLOTS + 1))
def test_persist_never_overlaps_over_a_simulated_day(slots: int) -> None:
    """The whole point of the split: writes stay serialised at any ceiling.

    Collect is mostly waiting on a provider and costs no CPU, so serialising it
    bought nothing. Persist is the part that costs, and it stays exclusive.
    """
    phases = _day(slots)
    windows = [(item.persist_started, item.persist_finished) for item in phases]
    assert max_overlap(windows) == 1


@pytest.mark.parametrize("slots", range(1, MAX_COLLECT_SLOTS + 1))
def test_collect_overlap_never_exceeds_the_ceiling(slots: int) -> None:
    phases = _day(slots)
    # The slot is held for the whole cycle, exactly as the lease is.
    windows = [(item.collect_started, item.persist_finished) for item in phases]
    assert max_overlap(windows) <= slots


def test_one_slot_reproduces_the_serial_schedule() -> None:
    """Rollback is a ceiling of one, so it must behave like before the split."""
    split = _day(1)
    windows = [(item.collect_started, item.persist_finished) for item in split]
    assert max_overlap(windows) == 1
    serial = simulate_phases(
        POLICIES,
        {p: COLLECT[p] + PERSIST[p] for p in Platform},
        start=START, hours=24,
    )
    # Same platforms served, same order of magnitude of cycles.
    assert {item.platform for item in split} == {item.platform for item in serial}
    assert abs(len(split) - len(serial)) <= len(serial) // 10


def test_raising_the_ceiling_buys_cadence_without_starving_anyone() -> None:
    one, two = _day(1), _day(2)

    def counts(phases):
        return {p: sum(1 for item in phases if item.platform == p) for p in Platform}

    before, after = counts(one), counts(two)
    assert len(two) > len(one)
    for platform in Platform:
        assert after[platform] >= before[platform], platform
    # Rutube has a one-hour period; it must still be served every hour and must
    # not be crowded out by the three five-minute platforms.
    assert after[Platform.RUTUBE] >= 24


def test_a_third_slot_moves_the_bottleneck_onto_the_write_lock() -> None:
    """Why the default ceiling is two rather than four.

    Past two slots the extra cadence is marginal while the wait for the write
    lock grows by an order of magnitude: the collectors stop waiting on the
    network and start waiting on each other.
    """
    two, four = _day(2), _day(4)

    def wait_p95(phases) -> float:
        waits = sorted(item.persist_wait_seconds for item in phases)
        return waits[int(len(waits) * 0.95)]

    assert len(four) - len(two) < len(two) - len(_day(1))
    assert wait_p95(four) > wait_p95(two) * 5


# --- slot naming ------------------------------------------------------------

def test_first_slot_keeps_the_original_lease_name() -> None:
    """A host at ceiling one competes for exactly the lock it used before.

    If slot zero were renamed, rolling the ceiling back would leave an upgraded
    and a rolled-back worker holding different names for the same exclusive
    window, and both would collect at once.
    """
    assert collect_slot_name(0) == GLOBAL_PHASE_LEASE_NAME
    assert collect_slot_name(1) != GLOBAL_PHASE_LEASE_NAME
    names = {collect_slot_name(slot) for slot in range(MAX_COLLECT_SLOTS)}
    assert len(names) == MAX_COLLECT_SLOTS


@pytest.mark.parametrize("slot", [-1, MAX_COLLECT_SLOTS, MAX_COLLECT_SLOTS + 1])
def test_slot_outside_the_range_is_rejected(slot: int) -> None:
    with pytest.raises(ValueError):
        collect_slot_name(slot)


def test_persist_lock_is_a_different_name_from_any_collect_slot() -> None:
    assert PERSIST_LOCK_NAME not in {
        collect_slot_name(slot) for slot in range(MAX_COLLECT_SLOTS)
    }


# --- guard ------------------------------------------------------------------

def test_null_guard_is_reentrant_and_does_nothing() -> None:
    with NULL_PERSIST_GUARD:
        with NULL_PERSIST_GUARD:
            pass


@pytest.mark.parametrize("wait", [0, -1.0])
def test_persist_guard_rejects_a_nonpositive_wait(wait: float) -> None:
    with pytest.raises(ValueError):
        PostgresPersistGuard(lambda: None, wait_seconds=wait)


def test_persist_guard_releases_its_lock_on_the_way_out() -> None:
    class FakeConnection:
        closed = False

        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement, params=None):
            self.statements.append(statement)
            return self

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    guard = PostgresPersistGuard(lambda: connection, wait_seconds=5)
    with guard:
        assert any("pg_advisory_lock" in item for item in connection.statements)
        assert not any("unlock" in item for item in connection.statements)
    assert any("pg_advisory_unlock" in item for item in connection.statements)
    # A bounded wait is set inside PostgreSQL, not only in Python, and through
    # set_config: plain SET takes no bound parameter, which only a live
    # database notices.
    assert any(
        "set_config('lock_timeout'" in item for item in connection.statements
    )
    guard.close()
    assert connection.closed


def test_persist_guard_releases_its_mutex_when_the_connection_fails() -> None:
    """A failure while acquiring must not leave the guard permanently shut."""
    class Exploding:
        closed = False

        def execute(self, statement, params=None):
            raise RuntimeError("connection reset")

    guard = PostgresPersistGuard(lambda: Exploding(), wait_seconds=5)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            with guard:
                pass


# --- simulation input validation --------------------------------------------

@pytest.mark.parametrize("slots", [0, MAX_COLLECT_SLOTS + 1])
def test_simulation_rejects_a_ceiling_outside_the_range(slots: int) -> None:
    with pytest.raises(ValueError):
        simulate_split_phases(
            POLICIES, COLLECT, PERSIST, start=START, hours=1, collect_slots=slots,
        )


def test_simulation_requires_a_duration_for_every_platform() -> None:
    partial = {Platform.TELEGRAM: 10}
    with pytest.raises(ValueError):
        simulate_split_phases(
            POLICIES, partial, PERSIST, start=START, hours=1, collect_slots=1,
        )


def test_overlap_counts_touching_windows_as_disjoint() -> None:
    moment = START
    from datetime import timedelta
    first = (moment, moment + timedelta(seconds=10))
    second = (moment + timedelta(seconds=10), moment + timedelta(seconds=20))
    assert max_overlap([first, second]) == 1
    third = (moment + timedelta(seconds=5), moment + timedelta(seconds=15))
    assert max_overlap([first, third]) == 2
    assert max_overlap([]) == 0


# --- real PostgreSQL --------------------------------------------------------

def test_persist_guard_serialises_two_processes_on_a_live_database() -> None:
    """Two holders of the write lock never overlap, and the loser waits."""
    import os
    import threading
    import time

    psycopg = pytest.importorskip("psycopg")
    dsn = os.getenv("MRANKED_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("MRANKED_TEST_POSTGRES_DSN is not configured")

    def connect():
        return psycopg.connect(dsn, autocommit=True)

    windows: list[tuple[float, float]] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    guards = [
        PostgresPersistGuard(connect, wait_seconds=30),
        PostgresPersistGuard(connect, wait_seconds=30),
    ]

    def worker(guard) -> None:
        barrier.wait(timeout=30)
        with guard:
            began = time.monotonic()
            # Long enough that an unguarded pair would certainly overlap.
            time.sleep(0.3)
            with lock:
                windows.append((began, time.monotonic()))

    threads = [threading.Thread(target=worker, args=(guard,)) for guard in guards]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            assert not thread.is_alive()
        assert len(windows) == 2
        first, second = sorted(windows)
        # The second holder started only after the first had finished.
        assert second[0] >= first[1]
    finally:
        for guard in guards:
            guard.close()


def test_collect_slots_admit_exactly_their_ceiling_on_a_live_database() -> None:
    """The counting semaphore is real advisory locks, not an in-process guess."""
    import os

    psycopg = pytest.importorskip("psycopg")
    dsn = os.getenv("MRANKED_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("MRANKED_TEST_POSTGRES_DSN is not configured")

    from collector_target.lease import advisory_lock_key

    ceiling = 2
    ids = [advisory_lock_key(collect_slot_name(slot)) for slot in range(ceiling)]
    holders = [psycopg.connect(dsn, autocommit=True) for _ in range(ceiling + 1)]
    try:
        taken = []
        for connection in holders:
            for lock_id in ids:
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(%s)", (lock_id,),
                ).fetchone()
                if bool(row[0]):
                    taken.append((connection, lock_id))
                    break
        # Exactly `ceiling` sessions get in; the third finds every slot busy.
        assert len(taken) == ceiling
        for connection, lock_id in taken:
            connection.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    finally:
        for connection in holders:
            connection.close()
