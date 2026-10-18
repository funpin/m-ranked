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

LIMITS = {"backup_hours": 36, "disk_free_bytes": 6 * 10**9, "load15": 6.0, "ingest_minutes": 20, "ingest_lag_minutes": 10,
          "analysis_lag_seconds": 3 * 3600, "docker_bytes": 5 * 10**9, "human_5xx": 20,
          "bot_503_share": 0.5, "misses_per_second": 20, "hit_ratio": 0.3,
          "cpu_percent": 90, "cpu_minutes": 45, "page_p95_seconds": 3.0, "memory_percent": 90,
          "swap_bytes": 10**9, "disk_urgent_share": 0.07, "bots_per_minute": 150, "bot_minutes": 5}


def line(path="/", status=200, klass="human", cache="HIT"):
    return (f'203.0.113.7 [25/Sep/2026:22:55:35 +0300] "GET {path} HTTP/2.0" {status} 724 0.012 '
            f'{klass} {cache} "Mozilla/5.0 (X11) Chrome/140"')


PLATFORMS = ("telegram", "vk", "max", "rutube")


def fresh_inputs(now, **parts):
    """Файл замеров ops-sample, в котором всё в порядке; parts подменяет верхние ключи."""
    entry = {"hourOk": 50, "hourFailed": 0, "hourResults": 50, "baselineOk": 50.0,
             "lastOk": now - 60, "lastResult": now - 60}
    node = {"name": "Сервер 1 · сбор", "observedAt": now - 60, "diskTotal": 100 * 10**9, "diskFree": 50 * 10**9,
            "memoryTotal": 2 * 10**9, "memoryAvailable": 10**9, "load1Mean15m": 0.5, "cpus": 2}
    inputs = {"at": now - 30, "collection": {name: dict(entry) for name in PLATFORMS},
              "pageP95Median15m": None, "nodes": {"server-1": node}}
    inputs.update(parts)
    return inputs


def healthy(now, **overrides):
    values = {"mranked_backup_last_success_unixtime": now - 3600,
              'mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}': now - 30,
              "mranked_anomaly_queue_lag_seconds": 60.0}
    host = dict(disk_free=20 * 10**9, disk_total=50 * 10**9, load5_series=[1.0] * 15, cpu_series=[10.0] * 45,
                memory_used_share=0.5, swap_used_bytes=0, failed=[], dump_mtime=None, bots_per_minute=[10] * 5)
    inputs = overrides.pop("inputs", fresh_inputs(now))
    host.update(overrides)
    return values, dict(host=alerts.Host(**host), inputs=inputs, limits=LIMITS)


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
    values, arguments = healthy(now, **overrides)
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
    slow = firing_rules(NOW, cpu_series=[90.5] * 45, inputs=fresh_inputs(NOW, pageP95Median15m=3.5))
    assert "cpu" in slow and slow["cpu_slow"].urgent is True
    assert "cpu_slow" not in firing_rules(NOW, cpu_series=[90.5] * 45, inputs=fresh_inputs(NOW, pageP95Median15m=2.5))
    assert not {"cpu", "cpu_slow"} & set(firing_rules(NOW, cpu_series=[99.0] * 44,
                                                      inputs=fresh_inputs(NOW, pageP95Median15m=9.0)))
    assert "cpu_slow" not in firing_rules(NOW, cpu_series=[10.0] * 45, inputs=fresh_inputs(NOW, pageP95Median15m=9.0))


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


def test_bot_surge_text_names_classes_and_cpu():
    rules = firing_rules(NOW, bots_per_minute=[400] * 5, cpu_series=[10.0] * 44 + [87.4],
                         bot_classes={"crawler": 300, "ai_training": 1200, "ai_user": 5})
    text = rules["bots"].text
    assert "сейчас 400" in text
    assert "ai_training 1200, crawler 300, ai_user 5" in text   # крупные классы первыми
    assert text.endswith("процессор 87%")
    # Без замера процессора и без разбивки по классам — без хвостов.
    bare = firing_rules(NOW, bots_per_minute=[400] * 5, cpu_series=[])["bots"].text
    assert "процессор" not in bare and "за 5 мин:" not in bare


def test_bot_classes_sum_complete_minutes_and_tolerate_old_buckets():
    state = {"buckets": {
        "101": {**alerts.empty_bucket(), "bots": {"crawler": 2, "ai_user": 1}},
        "102": {k: v for k, v in alerts.empty_bucket().items() if k != "bots"},  # корзина старого формата
        "105": {**alerts.empty_bucket(), "bots": {"crawler": 3}},
        "106": {**alerts.empty_bucket(), "bots": {"crawler": 100}},  # минута ещё идёт
    }}
    assert alerts.bot_classes(state, 106, 5) == {"crawler": 5, "ai_user": 1}
    assert alerts.bot_classes({}, 106, 5) == {}


def test_bot_requests_are_counted_per_class():
    bucket = alerts.empty_bucket()
    for klass in ("crawler", "crawler", "ai_search", "human"):
        alerts.add(bucket, alerts.parse_line(line("/p", 200, klass, "MISS")))
    assert bucket["bots"] == {"crawler": 2, "ai_search": 1}
    old = {k: v for k, v in alerts.empty_bucket().items() if k != "bots"}
    alerts.add(old, alerts.parse_line(line("/p", 200, "crawler", "MISS")))   # старая корзина не падает
    assert old["bots"] == {"crawler": 1}


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


# --- сбор по площадкам, вход MAX, Сервер 1 ---------------------------------

def with_collection(now, platform, **fields):
    inputs = fresh_inputs(now)
    inputs["collection"][platform].update(fields)
    return inputs


def test_rutube_uses_90_minutes():
    assert "collection_rutube" not in firing_rules(NOW, inputs=with_collection(NOW, "rutube", lastOk=NOW - 80 * 60))
    assert "collection_rutube" in firing_rules(NOW, inputs=with_collection(NOW, "rutube", lastOk=NOW - 95 * 60))
    # Ту же давность Telegram уже не прощает.
    assert "collection_telegram" in firing_rules(NOW, inputs=with_collection(NOW, "telegram", lastOk=NOW - 80 * 60))


def test_telegram_45_minutes():
    assert "collection_telegram" not in firing_rules(NOW, inputs=with_collection(NOW, "telegram", lastOk=NOW - 40 * 60))
    rule = firing_rules(NOW, inputs=with_collection(NOW, "telegram", lastOk=NOW - 50 * 60))["collection_telegram"]
    assert rule.urgent is True and "Telegram" in rule.text and "50 мин" in rule.text


def test_platform_without_any_success_in_the_window_fires():
    rules = firing_rules(NOW, inputs=with_collection(NOW, "vk", lastOk=None))
    assert "collection_vk" in rules and "3 ч" in rules["collection_vk"].text
    inputs = fresh_inputs(NOW)
    del inputs["collection"]["vk"]
    assert "collection_vk" in firing_rules(NOW, inputs=inputs)


def test_hour_below_30_percent_of_baseline():
    def fires(hour_ok, baseline=100.0):
        inputs = with_collection(NOW, "vk", hourOk=hour_ok, hourResults=hour_ok, baselineOk=baseline)
        return "collection_vk" in firing_rules(NOW, inputs=inputs)
    assert fires(29) and not fires(31) and not fires(30)
    assert not fires(0, baseline=None)


def test_failure_share_over_20_percent():
    def fires(failed, results):
        inputs = with_collection(NOW, "vk", hourOk=results - failed, hourFailed=failed, hourResults=results,
                                 baselineOk=None)
        return firing_rules(NOW, inputs=inputs).get("collection_vk")
    assert fires(21, 100) is not None and "21%" in fires(21, 100).text
    assert fires(19, 100) is None and fires(20, 100) is None
    # Мало результатов — доля шумит и не проверяется.
    assert fires(19, 19) is None and fires(20, 20) is not None


def test_max_without_any_results_is_auth():
    inputs = with_collection(NOW, "max", lastOk=NOW - 51 * 60, lastResult=NOW - 51 * 60)
    rules = firing_rules(NOW, inputs=inputs)
    assert rules["max_auth"].urgent is True
    assert "переавторизац" in rules["max_auth"].text and "reauth-max-session.sh" in rules["max_auth"].text
    assert "collection_max" not in rules
    rules = firing_rules(NOW, inputs=with_collection(NOW, "max", lastOk=None, lastResult=None))
    assert "max_auth" in rules and "collection_max" not in rules
    # Результаты идут, но неудачные — это сбор, а не вход.
    rules = firing_rules(NOW, inputs=with_collection(NOW, "max", lastOk=NOW - 60 * 60, lastResult=NOW - 60))
    assert "collection_max" in rules and "max_auth" not in rules
    # Другие площадки без результатов — не вход MAX.
    rules = firing_rules(NOW, inputs=with_collection(NOW, "vk", lastOk=NOW - 51 * 60, lastResult=NOW - 51 * 60))
    assert "collection_vk" in rules and "max_auth" not in rules


def test_ingest_down_suppresses_collection():
    inputs = with_collection(NOW, "telegram", lastOk=NOW - 3600)
    inputs["collection"]["max"].update(lastOk=None, lastResult=None)
    values, arguments = healthy(NOW, inputs=inputs)
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = NOW - 3600
    rules = alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments)
    firing = {rule.key for rule in rules if rule.firing}
    assert "ingest" in firing
    assert not {key for key in firing if key.startswith("collection_")} and "max_auth" not in firing
    # Подавленные правила остаются в списке со сброшенным признаком: открытая тревога закроется.
    assert {"collection_telegram", "max_auth"} <= {rule.key for rule in rules}


def test_ingest_down_suppresses_silent_nodes():
    # Сервер 1 недоступен: одна причина — одно сообщение «пакеты не приходят».
    inputs = node_inputs(observedAt=NOW - 3600, diskFree=1)
    values, arguments = healthy(NOW, inputs=inputs)
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = NOW - 3600
    rules = alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments)
    firing = {rule.key for rule in rules if rule.firing}
    assert firing == {"ingest"}
    assert "node_server-1_silent" in {rule.key for rule in rules}  # открытая тревога закроется
    # Без ingest молчание узла — своя тревога.
    assert "node_server-1_silent" in firing_rules(NOW, inputs=node_inputs(observedAt=NOW - 3600))


def test_suppress_keeps_texts_and_other_rules():
    rules = [alerts.Rule("ingest", True, "приём"), alerts.Rule("collection_vk", True, "сбор", urgent=True),
             alerts.Rule("max_auth", True, "вход", urgent=True), alerts.Rule("disk", True, "диск")]
    result = {rule.key: rule for rule in alerts.suppress(rules)}
    assert result["collection_vk"] == alerts.Rule("collection_vk", False, "сбор", urgent=True)
    assert result["max_auth"].firing is False and result["ingest"].firing and result["disk"].firing
    only_auth = [alerts.Rule("max_auth", True, "вход"), alerts.Rule("collection_max", True, "сбор")]
    assert [(rule.key, rule.firing) for rule in alerts.suppress(only_auth)] == [
        ("max_auth", True), ("collection_max", False)]


def test_stale_inputs():
    values, arguments = healthy(NOW, inputs=None)
    rules = alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments)
    assert {rule.key for rule in rules if rule.firing} == {"inputs_stale"}
    assert next(rule for rule in rules if rule.key == "inputs_stale").urgent is False
    assert not [rule for rule in rules if rule.key.startswith(("collection_", "node_")) or rule.key == "max_auth"]
    assert "inputs_stale" not in firing_rules(NOW)


def test_read_inputs(tmp_path):
    path = tmp_path / "alert-inputs.json"
    assert alerts.read_inputs(path, NOW) is None
    path.write_text(json.dumps({"at": NOW - 299, "collection": {}}))
    assert alerts.read_inputs(path, NOW) == {"at": NOW - 299, "collection": {}}
    path.write_text(json.dumps({"at": NOW - 301}))
    assert alerts.read_inputs(path, NOW) is None
    assert alerts.read_inputs(path, NOW, max_age=400) == {"at": NOW - 301}
    for broken in ("garbage", "[]", json.dumps({"collection": {}}), json.dumps({"at": "yesterday"})):
        path.write_text(broken)
        assert alerts.read_inputs(path, NOW) is None


def node_inputs(**fields):
    inputs = fresh_inputs(NOW)
    inputs["nodes"]["server-1"].update(fields)
    return inputs


def test_node_rules():
    total = 100 * 10**9
    rules = firing_rules(NOW, inputs=node_inputs(diskFree=total * 6 // 100))
    assert {"node_server-1_disk", "node_server-1_disk_urgent"} <= set(rules)
    assert rules["node_server-1_disk_urgent"].urgent is True and rules["node_server-1_disk"].urgent is False
    assert "Сервер 1" in rules["node_server-1_disk"].text
    rules = firing_rules(NOW, inputs=node_inputs(diskFree=total * 10 // 100))
    assert "node_server-1_disk" in rules and "node_server-1_disk_urgent" not in rules
    assert "node_server-1_disk" in firing_rules(NOW, inputs=node_inputs(diskFree=5 * 10**9, diskTotal=500 * 10**9))
    assert "node_server-1_disk" not in firing_rules(NOW, inputs=node_inputs(diskFree=total * 13 // 100))

    assert "node_server-1_memory" in firing_rules(NOW, inputs=node_inputs(memoryAvailable=int(2 * 10**9 * 0.09)))
    assert "node_server-1_memory" not in firing_rules(NOW, inputs=node_inputs(memoryAvailable=int(2 * 10**9 * 0.11)))

    # Нагрузка — среднее load1 за 15 минут снимков узла, а не один снимок: без дребезга.
    loaded = firing_rules(NOW, inputs=node_inputs(load1Mean15m=6.2, cpus=2))
    assert "node_server-1_load" in loaded
    assert "в среднем за 15 мин" in loaded["node_server-1_load"].text
    assert "node_server-1_load" not in firing_rules(NOW, inputs=node_inputs(load1Mean15m=6.0, cpus=2))
    assert "node_server-1_load" not in firing_rules(NOW, inputs=node_inputs(load1Mean15m=9.0, cpus=None))
    # Старое имя ключа (один снимок) больше не читается.
    assert "node_server-1_load" not in firing_rules(NOW, inputs=node_inputs(load1=9.0))

    silent = firing_rules(NOW, inputs=node_inputs(observedAt=NOW - 31 * 60))
    assert silent["node_server-1_silent"].urgent is False
    assert "node_server-1_silent" not in firing_rules(NOW, inputs=node_inputs(observedAt=NOW - 29 * 60))


def test_silent_node_suppresses_its_stale_resources():
    rules = firing_rules(NOW, inputs=node_inputs(observedAt=NOW - 31 * 60, diskFree=1, load1Mean15m=50.0))
    assert set(rules) == {"node_server-1_silent"}


def test_node_with_missing_values_is_skipped_not_crashing():
    inputs = node_inputs(diskTotal=None, diskFree=None, memoryTotal=None, memoryAvailable=None, load1Mean15m=None)
    assert not firing_rules(NOW, inputs=inputs)


def test_minute_limits_are_clamped_to_one(tmp_path, monkeypatch):
    spool = tmp_path / "inbox"
    spool.mkdir()
    _server(tmp_path, monkeypatch, ALERTS_BOT_SPOOL_DIR=spool, ALERTS_BOT_MINUTES="0", ALERTS_CPU_MINUTES="0",
            ALERTS_INGEST_MINUTES="0", ALERTS_ANALYSIS_LAG_MINUTES="0")
    assert alerts.main() == 0


def test_main_reads_the_inputs_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "alert-inputs.json"
    _server(tmp_path, monkeypatch, ALERTS_INPUTS_PATH=path)
    alerts.main()
    assert "Файл замеров" in capsys.readouterr().out
    path.write_text(json.dumps(fresh_inputs(time.time(), collection={
        **fresh_inputs(time.time())["collection"], "max": {"hourOk": 0, "hourFailed": 0, "hourResults": 0,
                                                              "baselineOk": 5.0, "lastOk": None, "lastResult": None}})))
    state_before = json.loads((tmp_path / "state" / "state.json").read_text())
    assert "inputs_stale" in state_before["active"]
    alerts.main()
    out = capsys.readouterr().out
    assert "переавторизац" in out and "Прошло: Файл замеров" in out


def test_ingest_lag_fires_and_explains_stale_collection():
    # 18.10.2026: пачки приходят, но через 24 мин после печати на Сервере 1.
    inputs = with_collection(NOW, "telegram", lastOk=NOW - 60 * 60)
    inputs["collection"]["max"].update(lastOk=None, lastResult=None)
    values, arguments = healthy(NOW, inputs=inputs)
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = NOW - 5
    values['mranked_transfer_ingest_last_batch_created_unixtime{producer="server-1/default"}'] = NOW - 5 - 24 * 60
    rules = alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments)
    firing = {rule.key for rule in rules if rule.firing}
    assert "ingest_lag" in firing and "ingest" not in firing
    assert not {key for key in firing if key.startswith("collection_")} and "max_auth" not in firing
    text = next(rule.text for rule in rules if rule.key == "ingest_lag")
    assert "24 мин" in text and "сбор при этом идёт" in text


def test_small_ingest_lag_is_quiet_and_lag_does_not_mute_silent_nodes():
    values, arguments = healthy(NOW, inputs=node_inputs(observedAt=NOW - 3600))
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = NOW - 5
    values['mranked_transfer_ingest_last_batch_created_unixtime{producer="server-1/default"}'] = NOW - 5 - 3 * 60
    firing = {rule.key for rule in alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments) if rule.firing}
    assert "ingest_lag" not in firing and "node_server-1_silent" in firing
    values['mranked_transfer_ingest_last_batch_created_unixtime{producer="server-1/default"}'] = NOW - 5 - 30 * 60
    firing = {rule.key for rule in alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments) if rule.firing}
    assert "ingest_lag" in firing and "node_server-1_silent" in firing


def test_stopped_ingest_is_reported_as_ingest_not_lag():
    values, arguments = healthy(NOW)
    values['mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}'] = NOW - 3600
    values['mranked_transfer_ingest_last_batch_created_unixtime{producer="server-1/default"}'] = NOW - 7200
    firing = {rule.key for rule in alerts.evaluate(NOW, alerts.empty_bucket(), values, **arguments) if rule.firing}
    assert "ingest" in firing and "ingest_lag" not in firing
