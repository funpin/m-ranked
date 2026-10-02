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


def test_directory_size_skips_unreadable_parts(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "file").write_bytes(b"x" * 10_000)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "hidden").write_bytes(b"y" * 10_000)
    locked.chmod(0)
    try:
        size = ops_sample.directory_bytes(tmp_path)
    finally:
        locked.chmod(0o700)
    assert size is not None and size >= 10_000
    assert ops_sample.directory_bytes(tmp_path / "missing") is None


def test_build_measures_sizes_once_an_hour(tmp_path: Path) -> None:
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
    assert "sizes" in ops_sample.build(state, 1000.0 + 3600, **kwargs)
    json.dumps(first)
