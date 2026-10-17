"""Тревоги Сервера 2: разбор журнала nginx, пороги и порядок сообщений."""
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

SCRIPT = Path(__file__).parents[1] / "operations" / "scripts" / "alerts.py"
SPEC = importlib.util.spec_from_file_location("alerts", SCRIPT)
assert SPEC and SPEC.loader
alerts = importlib.util.module_from_spec(SPEC)
sys.modules["alerts"] = alerts  # dataclass ищет модуль по имени
SPEC.loader.exec_module(alerts)

LIMITS = {"backup_hours": 36, "disk_free_bytes": 6 * 10**9, "load15": 6.0, "ingest_minutes": 20,
          "analysis_lag_seconds": 3 * 3600, "docker_bytes": 5 * 10**9, "human_5xx": 20,
          "bot_503_share": 0.5, "misses_per_second": 20, "hit_ratio": 0.3,
          "cpu_percent": 90, "cpu_minutes": 45, "page_p95_seconds": 3.0, "memory_percent": 90,
          "swap_bytes": 10**9, "disk_urgent_share": 0.07, "bots_per_minute": 150, "bot_minutes": 5}


def line(path="/", status=200, klass="human", cache="HIT"):
    return (f'203.0.113.7 [25/Sep/2026:22:55:35 +0300] "GET {path} HTTP/2.0" {status} 724 0.012 '
            f'{klass} {cache} "Mozilla/5.0 (X11) Chrome/140"')


def healthy(now, **overrides):
    values = {"mranked_backup_last_success_unixtime": now - 3600,
              'mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}': now - 30,
              "mranked_anomaly_queue_lag_seconds": 60.0}
    host = dict(disk_free=20 * 10**9, disk_total=50 * 10**9, load5_series=[1.0] * 15, cpu_series=[10.0] * 45,
                memory_used_share=0.5, swap_used_bytes=0, failed=[], dump_mtime=None, bots_per_minute=[10] * 5)
    host.update(overrides)
    return values, dict(host=alerts.Host(**host), inputs=None, limits=LIMITS)


def test_log_line_carries_class_cache_and_static_flag():
    item = alerts.parse_line(line("/_next/static/chunks/a.js", 200, "crawler", "MISS"))
    assert item == {"status": 200, "klass": "crawler", "cache": "MISS", "seconds": 0.012, "static": True}
    assert alerts.parse_line("garbage") is None


def test_log_is_read_incrementally_and_survives_rotation(tmp_path):
    log = tmp_path / "access.log"
    log.write_text(line() + "\n")
    state = {}
    alerts.read_log(log, state, 100)
    # Первый запуск не считает историю — только то, что пришло после.
    assert alerts.window(state)["requests"] == 0
    with log.open("a") as stream:
        stream.write(line("/p/1", 200, "ai_training", "MISS") + "\n" + line("/p/2", 503, "ai_training", "MISS") + "\n")
    alerts.read_log(log, state, 101)
    total = alerts.window(state)
    assert total["requests"] == 2 and total["bot_503"] == 1 and total["misses"] == {"ai_training": 2}
    rotated = tmp_path / "access.log.1"
    log.rename(rotated)
    log.write_text(line("/p/3", 502, "human", "MISS") + "\n")
    alerts.read_log(log, state, 102)
    assert alerts.window(state)["human_5xx"] == 1
    # Корзины старше окна выпадают.
    alerts.read_log(log, state, 102 + alerts.WINDOW_MINUTES + 1)
    assert alerts.window(state)["requests"] == 0


def test_healthy_server_raises_nothing():
    now = 1_800_000_000.0
    values, arguments = healthy(now)
    traffic = alerts.empty_bucket()
    assert not [rule.key for rule in alerts.evaluate(now, traffic, values, **arguments) if rule.firing]


def test_thresholds_fire_on_the_problems_they_name():
    now = 1_800_000_000.0
    values, arguments = healthy(now, disk_free=4 * 10**9, load5_series=[6.5] * 15, failed=["m-ranked-target-web.service"])
    values["mranked_backup_last_success_unixtime"] = now - 40 * 3600
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = now - 3600
    traffic = alerts.empty_bucket()
    for item in ([line("/p", 503, "ai_training", "MISS")] * 150 + [line("/q", 200, "crawler", "MISS")] * 7000
                 + [line("/", 502, "human", "MISS")] * 25):
        alerts.add(traffic, alerts.parse_line(item))
    firing = {rule.key for rule in alerts.evaluate(now, traffic, values, **arguments) if rule.firing}
    assert firing == {"backup", "disk", "load", "units", "ingest", "human_5xx", "misses", "hit_ratio"}


def test_missing_backup_metric_falls_back_to_the_newest_dump():
    now = 1_800_000_000.0
    values, arguments = healthy(now, dump_mtime=now - 3600)
    del values["mranked_backup_last_success_unixtime"]
    assert not next(rule for rule in alerts.evaluate(now, alerts.empty_bucket(), values, **arguments)
                    if rule.key == "backup").firing


def test_alert_is_sent_on_entry_repeat_and_resolution_only():
    state, now = {}, 1_800_000_000.0
    fire = [alerts.Rule("disk", True, "мало места")]
    assert [alerts.format_event(event) for event in alerts.transitions(fire, state, now)] == ["🔴 мало места"]
    assert alerts.transitions(fire, state, now + 60) == []
    repeat = alerts.transitions(fire, state, now + alerts.REPEAT_SECONDS)
    assert alerts.format_event(repeat[0]).startswith("🔴 Всё ещё: мало места")
    resolved = alerts.transitions([alerts.Rule("disk", False, "места хватает")], state, now + 7 * 3600)
    assert [alerts.format_event(event) for event in resolved] == ["🟢 Прошло: места хватает"]
    assert state["active"] == {}


def test_transitions_return_events():
    state, now = {}, 1_800_000_000.0
    fire = [alerts.Rule("disk", True, "мало места", urgent=True), alerts.Rule("load", True, "нагрузка")]
    opened = alerts.transitions(fire, state, now)
    assert opened == [alerts.Event("disk", "open", True, "мало места", now),
                      alerts.Event("load", "open", False, "нагрузка", now)]
    repeated = alerts.transitions(fire, state, now + alerts.REPEAT_SECONDS + 1)
    assert [(event.key, event.kind, event.urgent, event.since) for event in repeated] == [
        ("disk", "repeat", True, now), ("load", "repeat", False, now)]
    quiet = [alerts.Rule("disk", False, "места хватает", urgent=True), alerts.Rule("load", True, "нагрузка")]
    resolved = alerts.transitions(quiet, state, now + alerts.REPEAT_SECONDS + 2)
    assert resolved == [alerts.Event("disk", "resolve", True, "места хватает", now)]


def test_format_event_keeps_current_texts():
    since = 1_800_000_000.0
    stamp = time.strftime("%d.%m %H:%M", time.localtime(since))
    assert alerts.format_event(alerts.Event("disk", "open", False, "мало места", since)) == "🔴 мало места"
    assert alerts.format_event(alerts.Event("disk", "repeat", False, "мало места", since)) == (
        f"🔴 Всё ещё: мало места (с {stamp})")
    assert alerts.format_event(alerts.Event("disk", "resolve", False, "места хватает", since)) == (
        "🟢 Прошло: места хватает")


def test_metrics_files_are_read_by_full_series_name(tmp_path):
    (tmp_path / "a.prom").write_text('# HELP x\nmranked_x{producer="a"} 1.5\nmranked_y 2\n')
    assert alerts.metrics(tmp_path) == {'mranked_x{producer="a"}': 1.5, "mranked_y": 2.0}


def _server(tmp_path, monkeypatch, **env):
    """Сервер без бэкапа и метрик: тревоги точно будут."""
    for name, value in {"ALERTS_STATE_DIR": tmp_path / "state", "ALERTS_ACCESS_LOG": tmp_path / "access.log",
                        "ALERTS_METRICS_DIR": tmp_path / "metrics", "ALERTS_BACKUP_DIR": tmp_path / "backups",
                        "ALERTS_BOT_SPOOL_DIR": tmp_path / "no-spool", **env}.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(alerts, "failed_units", lambda: [])


def test_write_event_is_atomic_and_world_readable(tmp_path):
    spool = tmp_path / "inbox"
    spool.mkdir()
    event = alerts.Event("disk", "open", True, "мало места", 1_800_000_000.0)
    alerts.write_event(spool, event, "Сервер 2", 1_800_000_060.5)
    files = list(spool.iterdir())
    assert len(files) == 1 and files[0].suffix == ".json" and files[0].name.endswith("-disk.json")
    assert files[0].stat().st_mode & 0o777 == 0o644
    assert json.loads(files[0].read_text()) == {
        "version": 1, "server": "Сервер 2", "key": "disk", "kind": "open", "urgent": True,
        "text": "мало места", "since": 1_800_000_000.0, "at": 1_800_000_060.5}


def test_spool_is_capped_at_500_files(tmp_path):
    spool = tmp_path / "inbox"
    spool.mkdir()
    for number in range(500):
        (spool / f"{number:019d}-disk.json").write_text("{}")
    alerts.write_event(spool, alerts.Event("load", "open", False, "нагрузка", 1.0), "Сервер 2", 2.0)
    names = sorted(path.name for path in spool.glob("*.json"))
    assert len(names) == 500
    assert f"{0:019d}-disk.json" not in names and f"{1:019d}-disk.json" in names
    assert names[-1].endswith("-load.json")


def test_without_spool_dir_only_prints(tmp_path, monkeypatch, capsys):
    _server(tmp_path, monkeypatch)
    assert alerts.main() == 0
    assert capsys.readouterr().out.strip()
    assert not (tmp_path / "no-spool").exists()
    assert (tmp_path / "state" / "state.json").exists()


def test_events_reach_the_spool_when_it_exists(tmp_path, monkeypatch, capsys):
    spool = tmp_path / "inbox"
    spool.mkdir()
    _server(tmp_path, monkeypatch, ALERTS_BOT_SPOOL_DIR=spool, ALERTS_SERVER_NAME="Сервер Т")
    assert alerts.main() == 0
    printed = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(path.read_text()) for path in spool.glob("*.json")]
    assert payloads and len(payloads) == len(printed)
    assert {payload["server"] for payload in payloads} == {"Сервер Т"}
    assert {payload["kind"] for payload in payloads} == {"open"}


def test_spool_failure_reopens_next_minute(tmp_path, monkeypatch, capsys):
    spool = tmp_path / "inbox"
    spool.mkdir()
    _server(tmp_path, monkeypatch, ALERTS_BOT_SPOOL_DIR=spool)

    def broken(*args):
        raise OSError("disk full")
    monkeypatch.setattr(alerts, "write_event", broken)
    assert alerts.main() == 0
    assert "spool write failed" in capsys.readouterr().err
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["active"] == {}


def test_no_direct_telegram_path():
    assert not hasattr(alerts, "send")
    assert "api.telegram.org" not in SCRIPT.read_text()


@pytest.mark.parametrize(("accounts", "remaining", "firing"), [
    (16, 4 * 86400, False), (16, 3 * 86400, False),
    (16, 3 * 86400 - 1, True), (16, 0, True), (16, -86400, True),
    (0, -86400, False), (16, None, True), (16, float("nan"), True),
])
def test_active_max_reference_warns_before_expiry(accounts, remaining, firing):
    now = 1_800_000_000.0
    values, arguments = healthy(now)
    values["mranked_anomaly_reference_accounts"] = accounts
    if remaining is not None:
        values["mranked_anomaly_reference_expires_at_unixtime"] = now + remaining
    rule = next(rule for rule in alerts.evaluate(now, alerts.empty_bucket(), values, **arguments)
                if rule.key == "analysis_reference")
    assert rule.firing is firing
    assert "MAX" in rule.text


def test_renewed_reference_resolves_existing_alert():
    now = 1_800_000_000.0
    values, arguments = healthy(now)
    values["mranked_anomaly_reference_accounts"] = 16
    values["mranked_anomaly_reference_expires_at_unixtime"] = now + 2 * 86400
    state = {}
    first = alerts.evaluate(now, alerts.empty_bucket(), values, **arguments)
    assert len(alerts.transitions(first, state, now)) == 1
    assert alerts.transitions(first, state, now + 60) == []
    values["mranked_anomaly_reference_expires_at_unixtime"] = now + 28 * 86400
    renewed = alerts.evaluate(now + 120, alerts.empty_bucket(), values, **arguments)
    messages = [alerts.format_event(event) for event in alerts.transitions(renewed, state, now + 120)]
    assert len(messages) == 1 and messages[0].startswith("🟢 Прошло:")
    assert "analysis_reference" not in state["active"]


@pytest.mark.parametrize(("age_days", "firing"), [(None, False), (1.0, False), (2.5, True)])
def test_stale_account_tail_profile_warns(age_days, firing):
    now = 1_800_000_000.0
    values, arguments = healthy(now)
    if age_days is not None:
        values["mranked_anomaly_tail_last_run_unixtime"] = now - age_days * 86400
    rule = next(rule for rule in alerts.evaluate(now, alerts.empty_bucket(), values, **arguments)
                if rule.key == "analysis_tail")
    assert rule.firing is firing


def firing_rules(now, traffic=None, **overrides):
    inputs = overrides.pop("inputs", None)
    values, arguments = healthy(now, **overrides)
    arguments["inputs"] = inputs
    rules = alerts.evaluate(now, traffic or alerts.empty_bucket(), values, **arguments)
    return {rule.key: rule for rule in rules if rule.firing}


NOW = 1_800_000_000.0


def test_load_uses_15_minute_mean():
    assert "load" not in firing_rules(NOW, load5_series=[6.0] * 15)
    assert "load" in firing_rules(NOW, load5_series=[6.1] * 15)
    assert "load" not in firing_rules(NOW, load5_series=[7.0] * 14)


def test_cpu_sustained_45_minutes():
    rules = firing_rules(NOW, cpu_series=[90.5] * 45)
    assert "cpu" in rules and rules["cpu"].urgent is False and "cpu_slow" not in rules
    slow = firing_rules(NOW, cpu_series=[90.5] * 45, inputs={"pageP95Median15m": 3.5})
    assert "cpu" in slow and slow["cpu_slow"].urgent is True
    assert "cpu_slow" not in firing_rules(NOW, cpu_series=[90.5] * 45, inputs={"pageP95Median15m": 2.5})
    assert not {"cpu", "cpu_slow"} & set(firing_rules(NOW, cpu_series=[99.0] * 44,
                                                      inputs={"pageP95Median15m": 9.0}))
    assert "cpu_slow" not in firing_rules(NOW, cpu_series=[10.0] * 45, inputs={"pageP95Median15m": 9.0})


def test_memory_and_swap():
    assert "memory" in firing_rules(NOW, memory_used_share=0.91)
    assert "memory" in firing_rules(NOW, swap_used_bytes=int(1.1e9))
    assert "memory" not in firing_rules(NOW, memory_used_share=0.89, swap_used_bytes=int(0.5e9))
    assert "memory" not in firing_rules(NOW, memory_used_share=None, swap_used_bytes=None)


def test_disk_urgent_is_separate_key():
    total = 500 * 10**9
    rules = firing_rules(NOW, disk_free=int(total * 0.08), disk_total=total)
    assert "disk" in rules and "disk_urgent" not in rules
    rules = firing_rules(NOW, disk_free=int(total * 0.06), disk_total=total)
    assert "disk" in rules and rules["disk_urgent"].urgent is True


def test_bots_surge_needs_five_minutes():
    rules = firing_rules(NOW, bots_per_minute=[151] * 5)
    assert rules["bots"].urgent is True
    assert "bots" not in firing_rules(NOW, bots_per_minute=[151] * 4 + [100])
    assert "bots" not in firing_rules(NOW, bots_per_minute=[151] * 4)


def test_existing_urgency():
    now = NOW
    values, arguments = healthy(now, failed=["m-ranked-x.service"], disk_free=1)
    values["mranked_backup_last_success_unixtime"] = now - 40 * 3600
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = now - 3600
    values["mranked_anomaly_queue_lag_seconds"] = 5 * 3600.0
    values["mranked_anomaly_reference_accounts"] = 16
    values["mranked_anomaly_reference_expires_at_unixtime"] = now + 86400
    values["mranked_anomaly_tail_last_run_unixtime"] = now - 5 * 86400
    values["mranked_host_docker_reclaimable_bytes"] = 9e9
    traffic = alerts.empty_bucket()
    for item in ([line("/p", 503, "ai_training", "MISS")] * 9000 + [line("/q", 200, "crawler", "MISS")] * 7000
                 + [line("/", 502, "human", "MISS")] * 25):
        alerts.add(traffic, alerts.parse_line(item))
    urgent = {rule.key: rule.urgent for rule in alerts.evaluate(now, traffic, values, **arguments) if rule.firing}
    for key in ("units", "human_5xx"):
        assert urgent[key] is True
    for key in ("backup", "ingest", "analysis", "docker", "misses", "hit_ratio", "bot_503",
                "analysis_reference", "analysis_tail"):
        assert urgent[key] is False


def test_series_keep_only_the_latest_values():
    state = {}
    for value in range(20):
        series = alerts.push_series(state, "load5", float(value), 15)
    assert series == [float(value) for value in range(5, 20)]
    assert alerts.push_series(state, "cpu", 1.0, 45) == [1.0] and state["series"]["load5"] == series


def test_cpu_busy_percent_uses_difference_from_previous_run(monkeypatch):
    state = {}
    readings = iter([(1000, 800), (1200, 900), (1200, 900)])
    monkeypatch.setattr(alerts, "read_cpu_times", lambda: next(readings))
    assert alerts.cpu_busy_percent(state) is None  # первого запуска не с чем сравнивать
    assert alerts.cpu_busy_percent(state) == pytest.approx(50.0)  # занято 100 из 200 тактов
    assert alerts.cpu_busy_percent(state) is None  # время не сдвинулось
    monkeypatch.setattr(alerts, "read_cpu_times", lambda: None)
    assert alerts.cpu_busy_percent(state) is None


def test_proc_readers_parse_and_tolerate_absence(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 10 50 800 20 5 5 10 99 99\ncpu0 1 1 1 1 1 1 1 1 1 1\n")
    assert alerts.read_cpu_times(stat) == (1000, 820)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 800 kB\nSwapFree: 300 kB\n")
    share, swap = alerts.read_memory(meminfo)
    assert share == pytest.approx(0.75) and swap == 500 * 1024
    missing = tmp_path / "absent"
    assert alerts.read_cpu_times(missing) is None and alerts.read_memory(missing) == (None, None)


def test_bots_per_minute_returns_complete_minutes_oldest_first():
    state = {"buckets": {str(minute): {**alerts.empty_bucket(), "bot_requests": minute - 100}
                         for minute in (101, 102, 104, 105, 106)}}
    # Минута 106 ещё идёт; 103 пропущена и считается нулём.
    assert alerts.bots_per_minute(state, 106, 5) == [1, 2, 0, 4, 5]


def test_buckets_survive_long_enough_for_five_complete_minutes(tmp_path):
    log = tmp_path / "access.log"
    log.write_text("")
    state = {}
    alerts.read_log(log, state, 100)
    for minute in range(101, 108):
        with log.open("a") as stream:
            stream.write(line("/p", 200, "crawler", "MISS") * 1 + "\n")
        alerts.read_log(log, state, minute)
    assert alerts.bots_per_minute(state, 107, 5) == [1] * 5
    assert alerts.window(state)["bot_requests"] == alerts.WINDOW_MINUTES


def _failing_spool(tmp_path, monkeypatch, state, fire=True):
    spool = tmp_path / "inbox"
    spool.mkdir()
    _server(tmp_path, monkeypatch, ALERTS_BOT_SPOOL_DIR=spool)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "state.json").write_text(json.dumps(state))
    monkeypatch.setattr(alerts, "evaluate", lambda *args, **kwargs: [
        alerts.Rule("disk", fire, "мало места")])

    def broken(*args):
        raise OSError("disk full")
    monkeypatch.setattr(alerts, "write_event", broken)


def test_spool_failure_on_repeat_keeps_previous_sent(tmp_path, monkeypatch, capsys):
    now = time.time()
    old = now - alerts.REPEAT_SECONDS - 10
    _failing_spool(tmp_path, monkeypatch, {"active": {"disk": {"since": old - 100, "sent": old}}})
    assert alerts.main() == 0
    saved = json.loads((tmp_path / "state" / "state.json").read_text())
    assert saved["active"]["disk"] == {"since": old - 100, "sent": old}


def test_spool_failure_on_resolve_keeps_alert_active(tmp_path, monkeypatch, capsys):
    now = time.time()
    _failing_spool(tmp_path, monkeypatch, {"active": {"disk": {"since": now - 500, "sent": now - 400}}}, fire=False)
    assert alerts.main() == 0
    saved = json.loads((tmp_path / "state" / "state.json").read_text())
    assert saved["active"]["disk"] == {"since": now - 500, "sent": now - 400}
