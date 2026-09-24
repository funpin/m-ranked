from collections import namedtuple
import asyncio
from types import SimpleNamespace
import pytest
from collector_runtime import storage
from collector_target.__main__ import _disk_admission

Usage = namedtuple('Usage', 'total used free')

def test_admission_hysteresis_and_restart(monkeypatch):
    free = [6_000_000_000]
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda p: Usage(30_000_000_000, 30_000_000_000-free[0], free[0]))
    monkeypatch.setattr(storage.os, 'statvfs', lambda p: SimpleNamespace(f_files=100, f_favail=50))
    gate = storage.CollectionDiskGate('/', paused=True)
    assert gate.allows_cycle()
    free[0] = 2_900_000_000
    assert not gate.allows_cycle()
    free[0] = 4_000_000_000
    assert not gate.allows_cycle()  # still below 15% resume watermark
    free[0] = 4_600_000_000
    assert gate.allows_cycle()
    assert not storage.heavy_job_allowed('/', 1)
    free[0] = 8_000_000_000
    assert storage.heavy_job_allowed('/', 1_000_000_000)
    monkeypatch.setattr(storage.os, 'statvfs', lambda p: SimpleNamespace(f_files=100, f_favail=1))
    assert not gate.allows_cycle()


def test_unknown_filesystem_fails_closed(monkeypatch):
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda p: (_ for _ in ()).throw(OSError()))
    assert not storage.CollectionDiskGate('/').allows_cycle()


def test_paused_cycle_resumes_or_stops_without_acquiring_a_lease(monkeypatch):
    async def scenario():
        answers = iter([False, False, True])
        gate = SimpleNamespace(path='/', allows_cycle=lambda: next(answers))
        waits = []
        async def wait(stop, seconds):
            waits.append(seconds)
            return False
        monkeypatch.setattr('collector_target.__main__._wait_or_stop', wait)
        assert await _disk_admission(gate, asyncio.Event(), once=False)
        assert waits == [30,30]
        gate.allows_cycle = lambda: False
        assert not await _disk_admission(gate, asyncio.Event(), once=True)
        stop = asyncio.Event(); stop.set()
        assert not await _disk_admission(gate, stop, once=False)
    asyncio.run(scenario())


def test_backfill_pressure_stops_before_database_work(monkeypatch):
    from anomaly_analysis import backfill
    monkeypatch.setenv('ANOMALY_DATABASE_URL','postgresql://invalid/test')
    monkeypatch.setattr('sys.argv',['backfill'])
    monkeypatch.setattr(backfill.shutil,'disk_usage',lambda p: Usage(30_000_000_000,29_000_000_000,1_000_000_000))
    monkeypatch.setattr(backfill.os,'statvfs',lambda p: SimpleNamespace(f_files=100,f_favail=50))
    monkeypatch.setattr(backfill,'PostgresAnomalyStore',lambda d: (_ for _ in ()).throw(AssertionError('DB must not open')))
    with pytest.raises(SystemExit,match='insufficient disk reserve'):
        backfill.main()
