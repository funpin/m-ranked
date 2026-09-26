"""Тревоги Сервера 2: разбор журнала nginx, пороги и порядок сообщений."""
import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(__file__).parents[1] / "operations" / "scripts" / "alerts.py"
SPEC = importlib.util.spec_from_file_location("alerts", SCRIPT)
assert SPEC and SPEC.loader
alerts = importlib.util.module_from_spec(SPEC)
sys.modules["alerts"] = alerts  # dataclass ищет модуль по имени
SPEC.loader.exec_module(alerts)

LIMITS = {"backup_hours": 36, "disk_free_bytes": 6 * 10**9, "load5": 4.0, "ingest_minutes": 20,
          "analysis_lag_seconds": 3 * 3600, "docker_bytes": 5 * 10**9, "human_5xx": 20,
          "bot_503_share": 0.5, "misses_per_second": 20, "hit_ratio": 0.3}


def line(path="/", status=200, klass="human", cache="HIT"):
    return (f'203.0.113.7 [25/Sep/2026:22:55:35 +0300] "GET {path} HTTP/2.0" {status} 724 0.012 '
            f'{klass} {cache} "Mozilla/5.0 (X11) Chrome/140"')


def healthy(now, **overrides):
    values = {"mranked_backup_last_success_unixtime": now - 3600,
              'mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}': now - 30,
              "mranked_anomaly_queue_lag_seconds": 60.0}
    arguments = dict(disk_free=20 * 10**9, disk_total=50 * 10**9, load5=1.0, failed=[], dump_mtime=None,
                     limits=LIMITS)
    arguments.update(overrides)
    return values, arguments


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
    values, arguments = healthy(now, disk_free=4 * 10**9, load5=6.5, failed=["m-ranked-target-web.service"])
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
    assert alerts.transitions(fire, state, now) == ["🔴 мало места"]
    assert alerts.transitions(fire, state, now + 60) == []
    assert alerts.transitions(fire, state, now + alerts.REPEAT_SECONDS)[0].startswith("🔴 Всё ещё: мало места")
    assert alerts.transitions([alerts.Rule("disk", False, "места хватает")], state, now + 7 * 3600) == [
        "🟢 Прошло: места хватает"]
    assert state["active"] == {}


def test_metrics_files_are_read_by_full_series_name(tmp_path):
    (tmp_path / "a.prom").write_text('# HELP x\nmranked_x{producer="a"} 1.5\nmranked_y 2\n')
    assert alerts.metrics(tmp_path) == {'mranked_x{producer="a"}': 1.5, "mranked_y": 2.0}


def _server(tmp_path, monkeypatch, **env):
    """Сервер без бэкапа и метрик: тревоги точно будут."""
    monkeypatch.delenv("ALERTS_TELEGRAM_CHAT_ID", raising=False)
    for name, value in {"ALERTS_STATE_DIR": tmp_path / "state", "ALERTS_ACCESS_LOG": tmp_path / "access.log",
                        "ALERTS_METRICS_DIR": tmp_path / "metrics", "ALERTS_BACKUP_DIR": tmp_path / "backups",
                        "ALERTS_TELEGRAM_TOKEN_FILE": tmp_path / "no-token", **env}.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(alerts, "failed_units", lambda: [])


def test_without_telegram_alerts_go_to_the_journal_only(tmp_path, monkeypatch, capsys):
    # Telegram необязателен: без токена и чата тревоги пишутся в журнал службы,
    # запуск успешен, и в сеть ничего не уходит.
    _server(tmp_path, monkeypatch)
    monkeypatch.setattr(alerts, "send", lambda *args: (_ for _ in ()).throw(AssertionError("send without Telegram")))
    assert alerts.main() == 0
    assert capsys.readouterr().out.strip()
    assert (tmp_path / "state" / "state.json").exists()


def test_unreachable_telegram_does_not_break_the_run(tmp_path, monkeypatch, capsys):
    token = tmp_path / "token"
    token.write_text("123:abc\n")
    _server(tmp_path, monkeypatch, ALERTS_TELEGRAM_TOKEN_FILE=token, ALERTS_TELEGRAM_CHAT_ID="42")

    def unreachable(*args):
        raise OSError("network is unreachable")
    monkeypatch.setattr(alerts, "send", unreachable)
    assert alerts.main() == 0
    assert "telegram send failed" in capsys.readouterr().err
