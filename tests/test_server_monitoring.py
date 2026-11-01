"""Мониторинг серверов: процессы из systemctl и textfile-метрик, очередь точек
агента, буфер API через перезапуск, состояние сервера и пропуски замеров."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from api import server_monitor as monitor
from api.live_host import HostMonitor
from api.tools import ops_sample
from operations.storage import agent as agent_module, hostinfo, store
from operations.storage.hub import _clean_report, clean_samples

LISTING = """m-ranked-target-api.service loaded active running M-Ranked API
m-ranked-target-anomaly-norms.service loaded inactive dead Norms
m-ranked-target-anomaly-norms.timer loaded active waiting Norms timer
m-ranked-target-web.service loaded failed failed Web
m-ranked-target-gone.service not-found inactive dead gone
m-ranked-target.target loaded active active Target
"""
SHOWN = """Id=m-ranked-target-api.service
ActiveState=active
SubState=running
Result=success
ActiveEnterTimestamp=@1000
ExecMainStartTimestamp=@1000
ExecMainExitTimestamp=
NRestarts=2
LastTriggerUSec=
NextElapseUSecRealtime=
Unit=

Id=m-ranked-target-anomaly-norms.service
ActiveState=inactive
SubState=dead
Result=exit-code
ActiveEnterTimestamp=@2000
ExecMainStartTimestamp=@2000
ExecMainExitTimestamp=@2100
NRestarts=0
LastTriggerUSec=
NextElapseUSecRealtime=
Unit=

Id=m-ranked-target-anomaly-norms.timer
ActiveState=active
SubState=waiting
Result=success
ActiveEnterTimestamp=@500
ExecMainStartTimestamp=
ExecMainExitTimestamp=
NRestarts=
LastTriggerUSec=@2000
NextElapseUSecRealtime=@90000
Unit=m-ranked-target-anomaly-norms.service

Id=m-ranked-target-web.service
ActiveState=failed
SubState=failed
Result=exit-code
ActiveEnterTimestamp=@0
ExecMainStartTimestamp=@1500
ExecMainExitTimestamp=@1600
NRestarts=5
LastTriggerUSec=
NextElapseUSecRealtime=
Unit=
"""


def fake_systemctl(calls: list[list[str]]):
    def run(command, **_):
        calls.append(command)
        return SimpleNamespace(stdout=LISTING if command[1] == "list-units" else SHOWN)
    return run


def test_tasks_merge_timer_with_its_service_and_read_unix_times() -> None:
    calls: list[list[str]] = []
    found = {task["unit"]: task for task in hostinfo.tasks(fake_systemctl(calls))}
    assert len(calls) == 2  # список и свойства — двумя вызовами на всё
    assert "m-ranked-target-gone.service" not in calls[1] and "m-ranked-target.target" not in calls[1]
    assert set(found) == {"api", "web", "anomaly-norms"}
    norms = found["anomaly-norms"]
    assert norms["scheduled"] and norms["result"] == "exit-code"
    assert (norms["lastAt"], norms["nextAt"], norms["exitedAt"]) == (2000.0, 90000.0, 2100.0)
    assert found["api"]["restarts"] == 2 and found["api"]["since"] == 1000.0
    assert found["web"]["active"] == "failed" and found["web"]["since"] is None


def test_tasks_without_systemctl_are_empty() -> None:
    def broken(*_, **__):
        raise FileNotFoundError("systemctl")
    assert hostinfo.tasks(broken) == []


def test_collector_metrics_from_textfiles(tmp_path: Path) -> None:
    (tmp_path / "m-ranked-collector-telegram.prom").write_text(
        "# TYPE x gauge\n"
        'mranked_collector_last_success_unixtime{platform="telegram"} 1730000000.5\n'
        'mranked_collector_cycle_duration_seconds{platform="telegram"} 42\n'
        'mranked_collector_provider_errors_total{platform="telegram",class="timeout"} 2\n'
        'mranked_collector_provider_errors_total{platform="telegram",class="http"} 3\n'
        'mranked_collector_runs_total{platform="telegram",status="succeeded"} 9\n'
        'mranked_collector_cycle_duration_seconds{platform="evil"} 1\n')
    (tmp_path / "sender.prom").write_text("mranked_transfer_sender_backlog 7\nmranked_transfer_sender_delivered_total 99\n")
    (tmp_path / "ignored.txt").write_text("mranked_transfer_sender_backlog 1000\n")
    found = hostinfo.collector_processes(hostinfo.textfile(tmp_path, hostinfo.COLLECTOR_PREFIXES))
    assert found["collectors"] == {"telegram": {"lastSuccessAt": 1730000000.5, "cycleSeconds": 42.0,
                                                "providerErrors": 5.0}}
    assert found["transfer"] == {"backlog": 7.0, "delivered": 99.0}


def test_rates_between_runs_and_after_reboot() -> None:
    before = {"at": 100.0, "cpu": [1000, 800], "net": [0, 0], "disk": [0, 0]}
    after = {"at": 160.0, "cpu": [1600, 1100], "net": [6000, 600], "disk": [60, 120]}
    assert hostinfo.rates(before, after) == {
        "cpuPercent": 50.0, "netRxBytesPerSecond": 100.0, "netTxBytesPerSecond": 10.0,
        "diskReadBytesPerSecond": 1.0, "diskWriteBytesPerSecond": 2.0}
    rebooted = {"at": 220.0, "cpu": [10, 5], "net": [1, 1], "disk": [1, 1]}
    assert set(hostinfo.rates(after, rebooted).values()) == {None}
    assert set(hostinfo.rates(None, after).values()) == {None}


def test_release_from_current_symlink(tmp_path: Path) -> None:
    (tmp_path / "mranked-v2026.11.0-s1").mkdir()
    (tmp_path / "current").symlink_to(tmp_path / "mranked-v2026.11.0-s1")
    assert hostinfo.release(tmp_path / "current") == "v2026.11.0"
    assert hostinfo.release(tmp_path / "missing") is None


class QueueHub:
    def __init__(self, statuses: list[int]):
        self.statuses, self.reports = statuses, []

    def json(self, method, path, document=None):
        self.reports.append(document)
        status = self.statuses.pop(0)
        return status, ({"tasks": []} if status == 200 else None)


def ticking(monkeypatch) -> None:
    """Запуски агента — раз в минуту, а не в одну миллисекунду теста."""
    moments = iter(range(1_800_000_000, 1_900_000_000, 60))
    monkeypatch.setattr(hostinfo, "time", SimpleNamespace(time=lambda: float(next(moments))))


def test_agent_keeps_points_until_the_main_server_accepts_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "unit_states", lambda units: {})
    ticking(monkeypatch)
    hub = QueueHub([503, 503, 200, 200])
    agent = agent_module.Agent(hub, tmp_path / "store", tmp_path / "state", [], budget=60,
                               metrics_dir=tmp_path, proc=tmp_path / "proc", run=fake_systemctl([]))
    for _ in range(4):
        agent.run_once()
    # Два отказа (перезапуск приёмника при выкатке) — третий отчёт несёт все три точки.
    assert [len(report["samples"]) for report in hub.reports] == [1, 2, 3, 1]
    assert len({point["at"] for point in hub.reports[2]["samples"]}) == 3
    assert json.loads((tmp_path / "state" / "state.json").read_text())["samples"] == []
    assert hub.reports[0]["processes"]["tasks"] and hub.reports[0]["agentVersion"] == "2"


def test_agent_queue_is_bounded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "unit_states", lambda units: {})
    monkeypatch.setattr(agent_module, "MAX_QUEUED_SAMPLES", 3)
    ticking(monkeypatch)
    hub = QueueHub([503] * 5)
    agent = agent_module.Agent(hub, tmp_path / "store", tmp_path / "state", [], budget=60,
                               metrics_dir=tmp_path, proc=tmp_path / "proc", run=fake_systemctl([]))
    for _ in range(5):
        agent.run_once()
    assert len(hub.reports[-1]["samples"]) == 3


def test_hub_accepts_only_sane_points_and_known_process_fields() -> None:
    now = 1_800_000_000.0
    report = {"samples": [{"at": now - 60, "cpuPercent": 12.5, "release": "v2026.11.0", "evil": 1},
                          {"at": now - 60, "cpuPercent": 99},          # повтор — отброшен
                          {"at": now + 3600, "cpuPercent": 1},          # из будущего
                          {"at": now - 5 * 3600, "cpuPercent": 1},      # слишком старый
                          {"at": "x"}, "junk",
                          {"at": now, "load1": float("nan"), "release": "rm -rf /"}],
              "processes": {"release": "v2026.11.0", "bootAt": 5, "tasks": [
                  {"unit": "x" * 200, "active": "active", "since": 1, "evil": "y"}, {"unit": 5}],
                  "collectors": {"telegram": {"cycleSeconds": 3, "evil": 1}, "evil": {}},
                  "transfer": {"backlog": 4, "evil": "x"}}}
    samples = clean_samples(report, now)
    assert [sample["at"] for sample in samples] == [now - 60, now]
    assert samples[0]["cpuPercent"] == 12.5 and "evil" not in samples[0]
    assert samples[1]["load1"] is None and samples[1]["release"] is None
    processes = _clean_report(report)["processes"]
    assert processes["tasks"] == [{"unit": "x" * 80, "active": "active", "scheduled": False, "since": 1}]
    assert processes["collectors"] == {"telegram": {"cycleSeconds": 3}}
    assert processes["transfer"] == {"backlog": 4}


PROC_STAT = "cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\nbtime 100\n"


def write_proc(root: Path, busy: int, idle: int) -> None:
    (root / "self" / "net").mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text(PROC_STAT.format(busy=busy, idle=idle))
    (root / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 500 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    (root / "loadavg").write_text("0.5 0.4 0.3 1/1 1\n")
    (root / "self" / "net" / "dev").write_text("h\nh\n")
    (root / "diskstats").write_text("")


def test_live_buffer_survives_restart(tmp_path: Path) -> None:
    proc, clock = tmp_path / "proc", [1000.0]
    state = tmp_path / "buffer.json"
    write_proc(proc, 0, 0)
    first = HostMonitor(interval=5, proc=proc, disk=tmp_path, clock=lambda: clock[0], state_file=state)
    first.sample()
    clock[0] += 5
    write_proc(proc, 50, 50)
    first.sample()
    assert first.save()
    # Перезапуск: новый процесс читает буфер, первая точка — от счётчиков до остановки.
    clock[0] += 30
    write_proc(proc, 350, 50)
    second = HostMonitor(interval=5, proc=proc, disk=tmp_path, clock=lambda: clock[0], state_file=state)
    assert second.load() == 1
    point = second.sample()
    assert point is not None and point["cpu"] == 100.0
    assert [item["at"] for item in second.points] == [1005.0, 1035.0]
    # Буфер старше горизонта не возвращается.
    clock[0] += 4 * 3600
    third = HostMonitor(interval=5, proc=proc, disk=tmp_path, clock=lambda: clock[0], state_file=state)
    assert third.load() == 0


def test_live_buffer_without_file_is_fine(tmp_path: Path) -> None:
    monitor_ = HostMonitor(state_file=tmp_path / "missing" / "buffer.json")
    assert monitor_.load() == 0
    assert monitor_.save() is False


def node(**overrides):
    row = {"id": "server-1", "display_name": "Сервер 1", "role": "collector", "state": "active",
           "platforms": [], "last_seen_at": datetime.fromtimestamp(10_000, timezone.utc),
           "report": {"metrics": {"cpus": 1, "memoryTotalBytes": 100, "memoryAvailableBytes": 40},
                      "processes": {"release": "v2026.11.0", "bootAt": 1.0, "tasks": [
                          {"unit": "collector@telegram", "active": "active", "since": 2000.0},
                          {"unit": "collector-watchdog", "scheduled": True, "active": "inactive", "lastAt": 9000.0}]}}}
    row.update(overrides)
    return row


def test_server_status_states() -> None:
    now = 10_060.0
    assert monitor.status(node(), now)["state"] == "ok"
    assert monitor.status(node(), now)["release"] == "v2026.11.0"
    assert monitor.status(node(last_seen_at=datetime.fromtimestamp(9_000, timezone.utc)), now)["state"] == "offline"
    restarted = node(report={"processes": {"tasks": [{"unit": "collector@vk", "active": "active", "since": 9_900.0}]}})
    assert monitor.status(restarted, now)["state"] == "restarted"
    failed = node(report={"processes": {"tasks": [{"unit": "transfer-sender", "active": "failed"}]}})
    assert monitor.status(failed, now) | {"failed": ["transfer-sender"]} == monitor.status(failed, now)
    assert monitor.status(failed, now)["state"] == "degraded"
    main = node(role="main", report={"processes": {"deploy": {"version": "v2026.11.1", "phase": "миграции",
                                                               "startedAt": 10_000.0}}})
    updating = monitor.status(main, now, last_sample=10_030.0)
    assert (updating["state"], updating["label"]) == ("updating", "обновляется до v2026.11.1")
    # Основной без свежего снимка — нет связи, даже при живом агенте.
    assert monitor.status(main, now, last_sample=None)["state"] == "offline"


def test_gaps_name_an_update_between_versions() -> None:
    points = [(0.0, "v1"), (60.0, "v1"), (120.0, "v1"), (600.0, "v2"), (660.0, "v2"), (1500.0, "v2")]
    found = monitor.gaps(points, now=1530.0, start=30.0, step=60)
    assert found["count"] == 2
    assert [item["seconds"] for item in found["items"]] == [840, 480]   # новые первыми
    assert found["items"][1]["cause"] == "обновление v1 → v2" and found["items"][0]["cause"] is None
    trailing = monitor.gaps(points, now=2000.0, start=0.0, step=60)
    assert trailing["items"][0]["to"] is None and trailing["items"][0]["seconds"] == 500
    assert monitor.gaps([], now=100.0, start=0.0)["items"][0]["seconds"] == 100


def test_gap_step_follows_the_old_five_minute_agent() -> None:
    points = [(float(at), None) for at in range(0, 3000, 300)]
    assert monitor.gaps(points, now=2760.0, start=0.0)["count"] == 0


def test_collector_view_counts_cycles_and_collection_gaps() -> None:
    now = 100_000.0
    runs = [{"platform": "telegram", "runs": 10, "succeeded": 9, "partial": 0, "failed": 1, "accounts": 300,
             "errors": 2, "last_started": now - 100, "last_completed": now - 50, "running_since": None,
             "median_seconds": 40.0}]
    starts = [{"platform": "telegram", "started": now - 10_000}, {"platform": "telegram", "started": now - 100}]
    view = monitor.collector_view(node(platforms=["telegram"]), runs, starts,
                                  {"ingestAcceptedAt": now - 30, "ingestBatchCreatedAt": now - 90}, now, 86400)
    cycle = view["cycles"][0]
    assert (cycle["runs"], cycle["failed"], cycle["medianSeconds"]) == (10, 1, 40.0)
    assert len(cycle["gaps"]) == 2  # с начала периода до первого цикла и 9 900 с без циклов
    assert view["transfer"]["queueDelaySeconds"] == 60
    assert [task["unit"] for task in view["tasks"]] == ["collector@telegram", "collector-watchdog"]
    # Единственный сборщик без назначения собирает все площадки.
    assert [item["platform"] for item in monitor.collector_view(node(), [], [], None, now, 3600)["cycles"]] == \
        ["telegram", "vk", "max", "rutube"]


def test_ops_sample_keeps_failed_snapshots_and_writes_them_back() -> None:
    state: dict = {}
    for at in (60.0, 120.0):
        ops_sample.keep_pending(state, {"cpu": {"total": at}, "sizes": {"big": 1}}, at)
    assert [item["at"] for item in state["pending"]] == [60.0, 120.0]
    assert "sizes" not in state["pending"][0]["sample"]
    ops_sample.keep_pending(state, {}, 120.0 + ops_sample.MAX_PENDING * 60 + 1)
    assert [item["at"] for item in state["pending"]][-1] > 120.0 and len(state["pending"]) == 1


def test_store_inserts_pending_snapshots_with_their_own_time(monkeypatch) -> None:
    executed: list[tuple[str, tuple]] = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            executed.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [])

    monkeypatch.setitem(__import__("sys").modules, "psycopg", SimpleNamespace(connect=lambda *a, **k: Connection()))
    monkeypatch.setattr(ops_sample, "collection", lambda connection, since, until: {})
    state = {"pending": [{"at": 60.0, "sample": {"v": 1}}]}
    ops_sample.store("dsn", {"v": 1}, state, 120.0)
    inserts = [params for sql, params in executed if "INSERT INTO ops_and_admin.host_sample" in sql]
    assert [params[0] for params in inserts] == [60.0, 120.0]
    assert "pending" not in state


def test_deploy_marker_is_read_and_stale_ones_ignored(tmp_path: Path) -> None:
    from operations.storage.main_agent import deploy_marker
    marker = tmp_path / "in-progress.json"
    assert deploy_marker(marker) is None
    marker.write_text(json.dumps({"version": "v2026.11.1", "phase": "переключение", "startedAt": 5}))
    assert deploy_marker(marker) == {"version": "v2026.11.1", "phase": "переключение", "startedAt": 5}
    assert deploy_marker(marker, now=marker.stat().st_mtime + 2 * 86400) is None
    marker.write_text(json.dumps({"version": "$(reboot)", "phase": "x" * 99}))
    assert deploy_marker(marker)["version"] is None and len(deploy_marker(marker)["phase"]) == 40


def test_deploy_script_marks_and_clears_progress() -> None:
    script = Path("operations/deploy/deploy-release.sh").read_text()
    assert 'mark "$version" "переключение"' in script and 'rm -f -- "$MARKER"' in script
    assert subprocess.run(["bash", "-n", "operations/deploy/deploy-release.sh"]).returncode == 0


def test_host_metrics_report_swap_and_load_triple(tmp_path: Path) -> None:
    metrics = store.host_metrics(tmp_path)
    assert {"load1", "load5", "load15"} <= set(metrics)
