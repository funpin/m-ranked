from pathlib import Path

from api import live_host
from api.live_host import HostMonitor

NET = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: {lo} 10 0 0 0 0 0 0 {lo} 10 0 0 0 0 0 0
  eth0: {rx} 10 0 0 0 0 0 0 {tx} 10 0 0 0 0 0 0
docker0: 999999 10 0 0 0 0 0 0 999999 10 0 0 0 0 0 0
"""
DISK = """ 252 0 vda {r} 0 {rs} 0 {w} 0 {ws} 0 0 0 0
 252 1 vda1 1 0 {rs} 0 1 0 {ws} 0 0 0 0
   7 0 loop0 1 0 99999 0 1 0 99999 0 0 0 0
"""


def write_proc(root: Path, *, total: int, idle: int, available: int, rx: int, tx: int, read: int, written: int) -> None:
    (root / "self" / "net").mkdir(parents=True, exist_ok=True)
    busy = total - idle
    (root / "stat").write_text(f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0\n")
    (root / "meminfo").write_text(
        f"MemTotal: 1000 kB\nMemFree: 10 kB\nMemAvailable: {available} kB\nSwapTotal: 100 kB\nSwapFree: 60 kB\n")
    (root / "loadavg").write_text("0.50 0.40 0.30 1/100 42\n")
    (root / "self" / "net" / "dev").write_text(NET.format(lo=123456, rx=rx, tx=tx))
    (root / "diskstats").write_text(DISK.format(r=1, rs=read // 512, w=1, ws=written // 512))


def test_parsers_skip_virtual_interfaces_and_partitions() -> None:
    assert live_host.net_bytes(NET.format(lo=5, rx=100, tx=40)) == (100, 40)
    assert live_host.disk_bytes(DISK.format(r=1, rs=2, w=1, ws=4)) == (1024, 2048)
    assert live_host.cpu_counters("cpu  10 0 5 80 5 0 0 0\n") == (100, 85)
    for name, whole in (("vda", True), ("vda1", False), ("nvme0n1", True), ("nvme0n1p2", False),
                        ("mmcblk0", True), ("mmcblk0p1", False), ("loop0", False), ("dm-0", False)):
        assert live_host._whole_disk(name) is whole


def test_monitor_rates_and_ring_buffer(tmp_path: Path) -> None:
    moments = iter([100.0, 105.0, 110.0, 115.0])
    monitor = HostMonitor(interval=5, horizon=10, proc=tmp_path, disk=tmp_path, clock=lambda: next(moments))
    write_proc(tmp_path, total=1000, idle=800, available=750, rx=1000, tx=500, read=0, written=0)
    assert monitor.sample() is None  # первое чтение — только опора для разностей
    write_proc(tmp_path, total=2000, idle=1300, available=500, rx=6000, tx=1500, read=5120, written=10240)
    point = monitor.sample()
    assert point is not None
    assert point["cpu"] == 50.0
    assert point["memory"] == 50.0
    assert point["memoryUsedBytes"] == 500 * 1024
    assert point["swapUsedBytes"] == 40 * 1024
    assert point["load"] == 0.5
    assert point["netRxBytesPerSecond"] == 1000.0
    assert point["netTxBytesPerSecond"] == 200.0
    assert point["diskReadBytesPerSecond"] == 1024.0
    assert point["diskWriteBytesPerSecond"] == 2048.0
    assert monitor.memory_total == 1000 * 1024
    assert monitor.disk_total is not None
    # Счётчик сети обнулился (перезапуск интерфейса) — скорость неизвестна, а не отрицательна.
    write_proc(tmp_path, total=3000, idle=2300, available=500, rx=10, tx=10, read=5120, written=10240)
    assert monitor.sample()["netRxBytesPerSecond"] is None
    write_proc(tmp_path, total=4000, idle=3300, available=500, rx=20, tx=20, read=5120, written=10240)
    monitor.sample()
    # Горизонт 10 с при шаге 5 с — в буфере две последние точки.
    assert [point["at"] for point in monitor.points] == [110.0, 115.0]
    assert [point["at"] for point in monitor.since(110.0)] == [115.0]
    assert len(monitor.since(None)) == 2


def test_missing_proc_files_do_not_raise(tmp_path: Path) -> None:
    monitor = HostMonitor(proc=tmp_path / "absent", disk=tmp_path)
    assert monitor.sample() is None
    assert list(monitor.points) == []
