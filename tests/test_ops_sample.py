import json
import subprocess
from pathlib import Path

from api.tools import ops_sample

LOG = (
    '1.2.3.4 [02/Oct/2026:21:00:00 +0300] "GET / HTTP/1.1" 200 1000 0.010 human HIT "UA"\n'
    '1.2.3.4 [02/Oct/2026:21:00:01 +0300] "GET /compare HTTP/1.1" 502 10 1.500 human MISS "UA"\n'
    '5.6.7.8 [02/Oct/2026:21:00:02 +0300] "GET /accounts HTTP/1.1" 503 0 0.001 crawler - "bot"\n'
    '1.2.3.4 [02/Oct/2026:21:00:03 +0300] "GET /_next/static/a.js HTTP/1.1" 200 500 0.000 human HIT "UA"\n'
)


def test_proc_parsers_read_counters_and_bytes() -> None:
    cpu = ops_sample.cpu_counters("cpu  10 0 5 80 5 0 0 0 0 0\ncpu0 1 1 1 1\n")
    assert cpu["total"] == 100 and cpu["idle"] == 80
    memory = ops_sample.memory("MemTotal: 4 kB\nMemAvailable: 2 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    assert memory == {"total": 4096, "available": 2048, "swapTotal": 0, "swapFree": 0}


def test_traffic_counts_only_growth_since_previous_sample(tmp_path: Path) -> None:
    log = tmp_path / "access.log"
    log.write_text(LOG)
    state: dict = {}
    # Первый запуск запоминает конец журнала и ничего не считает.
    assert ops_sample.read_traffic(log, state, 100.0) is None
    with log.open("a") as stream:
        stream.write(LOG)
        stream.write('1.2.3.4 [02/Oct/2026:21:00:04 +0300] "GET / HTTP/1.1" 200 1')  # неполная строка
    traffic = ops_sample.read_traffic(log, state, 400.0)
    assert traffic is not None
    assert traffic["seconds"] == 300.0
    assert traffic["requests"] == 4 and traffic["human"] == 3 and traffic["bots"] == 1
    assert traffic["status"] == {"2xx": 2, "3xx": 0, "4xx": 0, "5xx": 2}
    assert traffic["human5xx"] == 1 and traffic["bot503"] == 1
    assert traffic["pages"] == 2 and traffic["pageHits"] == 1
    assert traffic["p95"] == 1.5
    # Неполная строка дочитывается в следующий раз, поворот журнала — с начала.
    log.write_text(LOG[:90])
    rotated = ops_sample.read_traffic(log, state, 700.0)
    assert rotated is not None and rotated["requests"] == 1


def test_media_and_service_files_are_not_pages() -> None:
    # Картинка реакции, иконки, манифест и robots.txt идут через тот же кэш,
    # но страницами не являются: 10-секундный отказ картинки Telegram не
    # должен выдавать себя за медленную страницу на графике скорости.
    totals, latencies = ops_sample.empty_traffic(), []
    for path in ("/emoji/5461040295409892378", "/icons/icon-192.png", "/splash/a.png",
                 "/apple-touch-icon.png", "/favicon.ico", "/manifest.webmanifest",
                 "/robots.txt", "/sitemap.xml"):
        ops_sample.add_line(totals, latencies,
                            f'1.2.3.4 [16/Oct/2026:02:13:49 +0300] "GET {path} HTTP/2.0" 404 47 14.359 human MISS "UA"')
    ops_sample.add_line(totals, latencies,
                        '1.2.3.4 [16/Oct/2026:02:13:55 +0300] "GET /findings?platform=all HTTP/2.0" 200 9 2.377 human MISS "UA"')
    assert totals["requests"] == 9 and totals["pages"] == 1 and totals["pageHits"] == 0
    assert latencies == [2.377]


def test_units_report_failures_and_restarts() -> None:
    def run(command, **_):
        if command[1] == "list-units":
            out = ("m-ranked-target-api.service loaded active running API\n"
                   "m-ranked-target-tail.service loaded failed failed Tail\n"
                   "docker.service not-found inactive dead docker\n")
        else:
            out = "Id=m-ranked-target-api.service\nNRestarts=3\n\nId=nginx.service\nNRestarts=0\n"
        return subprocess.CompletedProcess(command, 0, out, "")

    units = ops_sample.unit_states(run)
    assert units == {"failed": ["m-ranked-target-tail.service"], "active": 1, "total": 2,
                     "restarts": {"m-ranked-target-api.service": 3, "nginx.service": 0}}


def test_pipeline_metrics_pick_latest_and_sum_labels() -> None:
    values = {
        'mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}': 1000.0,
        'mranked_anomaly_analyses_total{platform="vk"}': 3.0,
        'mranked_anomaly_analyses_total{platform="max"}': 4.0,
        "mranked_anomaly_queue_lag_seconds": 60.0,
    }
    result = ops_sample.pipeline(values)
    assert result["ingestAcceptedAt"] == 1000.0 and result["analyses"] == 7.0
    assert result["analysisLag"] == 60.0 and result["backupAt"] is None


def test_directory_size_takes_du_total_even_when_parts_are_unreadable(tmp_path: Path) -> None:
    def run(command, **_):
        assert command[:4] == ["du", "-s", "-x", "--block-size=1"]
        # du пропустил нечитаемый каталог: код 1, но итог напечатан.
        return subprocess.CompletedProcess(command, 1, f"123456\t{command[-1]}\n", "du: cannot read directory")

    assert ops_sample.directory_bytes(tmp_path, run) == 123456
    assert ops_sample.directory_bytes(tmp_path / "missing", run) is None
    assert ops_sample.directory_bytes(tmp_path, lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "")) is None


def test_build_measures_sizes_on_schedule(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  1 2 3 4 5 6 7 8\n")
    (proc / "loadavg").write_text("0.10 0.20 0.30 1/100 42\n")
    (proc / "meminfo").write_text("MemTotal: 8 kB\nMemAvailable: 4 kB\n")

    def run(command, **_):
        return subprocess.CompletedProcess(command, 0, "", "")

    state: dict = {}
    kwargs = dict(proc=proc, log=tmp_path / "none.log", metrics=tmp_path, disk=tmp_path,
                  sizes={"state": tmp_path}, run=run)
    first = ops_sample.build(state, 1000.0, **kwargs)
    assert first["load"] == [0.1, 0.2, 0.3] and "sizes" in first and first["traffic"] is None
    assert "sizes" not in ops_sample.build(state, 1300.0, **kwargs)
    assert "sizes" in ops_sample.build(state, 1000.0 + ops_sample.SIZE_INTERVAL_SECONDS, **kwargs)
    json.dumps(first)


def test_collection_window_starts_where_the_previous_sample_ended() -> None:
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append(params)

            class Cursor:
                @staticmethod
                def fetchall():
                    return [("vk", 80, 2, 0, 1000.5, 1000.9), ("rutube", 0, 1, 0, None, 990.0)]
            return Cursor()

    result = ops_sample.collection(Connection(), 700.0, 1000.0)
    assert calls == [{"since": 700.0, "until": 1000.0}]
    assert result == {"vk": {"ok": 80, "failed": 2, "other": 0, "lastOk": 1000.5, "lastResult": 1000.9},
                      "rutube": {"ok": 0, "failed": 1, "other": 0, "lastOk": None, "lastResult": 990.0}}


def test_collection_query_reports_last_result() -> None:
    # Последний результат любого исхода: у отозванного входа MAX его нет вовсе.
    assert "last_result" in ops_sample.COLLECTION
    assert "max(result.completed_at)" in ops_sample.COLLECTION


def row(**platforms):
    return {name: {"ok": ok, "failed": failed, "other": other, "lastOk": last_ok, "lastResult": last_result}
            for name, (ok, failed, other, last_ok, last_result) in platforms.items()}


def test_summarize_collection() -> None:
    hour = [row(telegram=(3, 1, 0, 100.0, 110.0)),
            {},
            None,
            row(telegram=(2, 0, 1, 120.0, 130.0), vk=(5, 5, 0, 90.0, 95.0))]
    # Три часа: час целиком плюс два предыдущих; значения последних результатов — максимум.
    window = hour + [row(telegram=(9, 9, 9, 50.0, 60.0), max=(0, 4, 0, None, 70.0))]
    # Старые строки без lastResult: последним результатом считается последний успех.
    window.append({"rutube": {"ok": 1, "failed": 0, "other": 0, "lastOk": 80.0}})
    baseline = [[row(telegram=(10, 0, 0, 1.0, 1.0))],
                [row(telegram=(20, 5, 0, 1.0, 1.0)), row(telegram=(5, 0, 0, 1.0, 1.0))],
                [],
                [row(vk=(1, 0, 0, 1.0, 1.0))]]
    result = ops_sample.summarize_collection(hour, window, baseline)
    assert result["telegram"] == {"hourOk": 5, "hourFailed": 1, "hourResults": 7, "baselineOk": 10.0,
                                  "lastOk": 120.0, "lastResult": 130.0}
    # Неделя без строк не считается, неделя со строками без площадки считается нулём.
    assert result["vk"]["baselineOk"] == 0.0 and result["vk"]["hourOk"] == 5
    assert result["vk"]["hourResults"] == 10
    assert result["max"] == {"hourOk": 0, "hourFailed": 0, "hourResults": 0, "baselineOk": 0.0,
                             "lastOk": None, "lastResult": 70.0}
    assert result["rutube"]["lastOk"] == 80.0 and result["rutube"]["lastResult"] == 80.0
    assert ops_sample.summarize_collection([], [], [[], [], [], []]) == {}
    only = ops_sample.summarize_collection(hour, hour, [[], [], [], []])
    assert only["telegram"]["baselineOk"] is None


def test_baseline_is_median_of_weekly_sums() -> None:
    weeks = [[row(telegram=(value, 0, 0, 1.0, 1.0))] for value in (10, 40, 20, 30)]
    result = ops_sample.summarize_collection([row(telegram=(1, 0, 0, 1.0, 1.0))], [], weeks)
    assert result["telegram"]["baselineOk"] == 25.0
    # Ключ из окна без часа не теряется: у площадки только прошлые недели.
    result = ops_sample.summarize_collection([], [], weeks)
    assert result["telegram"]["hourOk"] == 0 and result["telegram"]["baselineOk"] == 25.0


def test_page_p95_median_skips_missing_values() -> None:
    assert ops_sample.page_p95_median([None, 1.0, 3.0, None, 2.0]) == 2.0
    assert ops_sample.page_p95_median([None, None]) is None
    assert ops_sample.page_p95_median([]) is None


def test_node_inputs_keep_resources_and_cpu_count() -> None:
    rows = [("server-1", "Сервер 1 · сбор", "1", 1000.5, 100, 40, 200, 80, 0.61),
            ("storage-1", "Хранилище", None, 900.0, None, None, None, None, None)]
    nodes = ops_sample.node_inputs(rows)
    assert nodes["server-1"] == {"name": "Сервер 1 · сбор", "observedAt": 1000.5, "diskTotal": 100, "diskFree": 40,
                                 "memoryTotal": 200, "memoryAvailable": 80, "load1": 0.61, "cpus": 1}
    # Узел без показателей остаётся: по его возрасту тревога «молчит» всё равно считается.
    assert nodes["storage-1"]["observedAt"] == 900.0 and nodes["storage-1"]["load1"] is None
    assert nodes["storage-1"]["cpus"] is None


def test_alert_inputs_file_is_atomic_and_world_readable(tmp_path: Path) -> None:
    path = tmp_path / "state" / "alert-inputs.json"
    path.parent.mkdir()
    ops_sample.write_alert_inputs(path, {"at": 1.0, "collection": {}})
    assert json.loads(path.read_text()) == {"at": 1.0, "collection": {}}
    assert path.stat().st_mode & 0o777 == 0o644
    assert [item.name for item in path.parent.iterdir()] == ["alert-inputs.json"]
    ops_sample.write_alert_inputs(path, {"at": 2.0})
    assert json.loads(path.read_text()) == {"at": 2.0}


def test_alert_inputs_errors_never_break_the_sample(caplog) -> None:
    class Connection:
        def execute(self, *args):
            raise RuntimeError("secret detail")

    import logging
    with caplog.at_level(logging.WARNING, logger="ops-sample"):
        assert ops_sample.refresh_alert_inputs(Connection(), 1000.0, Path("/nonexistent/dir/x.json")) is False
    assert "RuntimeError" in caplog.text and "secret detail" not in caplog.text


def test_backups_list_copies_running_state_and_request(tmp_path: Path) -> None:
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (backups_dir / "mranked-20260927T010000Z.dump").write_bytes(b"a" * 10)
    (backups_dir / "mranked-20260927T010000Z.restore-verified.json").write_text("{}")
    (backups_dir / "mranked-20260928T010000Z.dump").write_bytes(b"b" * 20)
    request = tmp_path / "refresh"
    request.write_text("{}")

    def run(command, **_):
        return subprocess.CompletedProcess(command, 0, "ActiveState=activating\nResult=success\nExecMainStatus=0\n", "")

    result = ops_sample.backups(backups_dir, request, run)
    assert [item["name"] for item in result["files"]] == ["mranked-20260928T010000Z.dump", "mranked-20260927T010000Z.dump"]
    assert result["files"][1]["verified"] and not result["files"][0]["verified"]
    assert result["running"] and result["requested"] and result["lastExitStatus"] == 0
    assert ops_sample.backups(tmp_path / "none", request, run) is None


def test_refresh_builds_file_from_the_three_queries(tmp_path: Path) -> None:
    now = 1_000_000.0
    seen = []

    class Connection:
        def execute(self, sql, params=None):
            seen.append((sql, params))

            class Cursor:
                @staticmethod
                def fetchall():
                    if sql is ops_sample.RECENT_SAMPLES:
                        # Новые первыми; последняя строка старше часа, p95 у части строк пуст.
                        return [({"vk": {"ok": 4, "failed": 0, "other": 0, "lastOk": now - 5, "lastResult": now - 5}},
                                 "2.0", now - 10),
                                ({}, None, now - 70),
                                ({"vk": {"ok": 9, "failed": 1, "other": 0, "lastOk": now - 7000,
                                         "lastResult": now - 7000}}, "4.0", now - 7000)]
                    if sql is ops_sample.WEEKLY_SAMPLES:
                        return [(1, {"vk": {"ok": 8}}), (3, {"vk": {"ok": 12}}), (3, {})]
                    return [("server-1", "Сервер 1", "2", now - 20, 100, 50, 10, 5, 0.5)]
            return Cursor()

    path = tmp_path / "alert-inputs.json"
    assert ops_sample.refresh_alert_inputs(Connection(), now, path) is True
    written = json.loads(path.read_text())
    assert written["at"] == now and written["pageP95Median15m"] == 3.0
    assert written["collection"]["vk"] == {"hourOk": 4, "hourFailed": 0, "hourResults": 4, "baselineOk": 10.0,
                                           "lastOk": now - 5, "lastResult": now - 5}
    assert written["nodes"]["server-1"]["cpus"] == 2
    assert [item[0] for item in seen] == [ops_sample.RECENT_SAMPLES, ops_sample.WEEKLY_SAMPLES,
                                          ops_sample.NODE_SAMPLES]
