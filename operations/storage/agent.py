"""Агент узла: отчёт основному серверу и исполнение заданий хранилища.

Работает на каждом сервере, кроме основного, раз в минуту (таймер systemd) и
только на стандартной библиотеке. За один запуск:

1. снимает метрики машины (загрузку CPU и скорости сети и диска — по
   разности счётчиков с прошлого запуска), процессы проекта (службы, задания
   по расписанию, сборщики и отправитель переноса по их textfile-метрикам) и
   опись файлов хранилища;
2. отправляет отчёт с итогами прошлых заданий и неотправленными минутными
   точками на /node/v1/report по mTLS — тот же адрес, сертификат и CA, что у
   отправителя переноса;
3. пишет runtime.json (политика сбора и состав сборщиков) атомарно — сборщики
   перечитывают его в начале цикла;
4. исполняет задания в пределах бюджета времени: скачивает куски файла с
   основного, отдаёт свой файл основному или удаляет лишнюю копию. Недокачанная
   копия лежит в incoming и продолжается со следующего запуска.

Итоги заданий и минутные точки хранятся в state.json до подтверждения
основным: обрыв связи и перезапуск приёмника при выкатке не теряют ни
результата, ни докачки, ни замера — точки уходят следующим отчётом со своим
временем.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit

from . import hostinfo, store

logger = logging.getLogger("node-agent")
VERSION = "2"
DEFAULT_STATE_DIR = Path("/var/lib/m-ranked/node-agent")
DEFAULT_METRICS_DIR = Path("/var/lib/node_exporter/textfile_collector")
# Три часа минутных точек: столько основной может быть недоступен без потери
# истории ресурсов; дальше теряются самые старые.
MAX_QUEUED_SAMPLES = 180
SAMPLE_KEYS = ("cpuPercent", "memoryTotalBytes", "memoryAvailableBytes", "swapUsedBytes", "load1",
               "diskTotalBytes", "diskFreeBytes", "storeBytes", "netRxBytesPerSecond", "netTxBytesPerSecond",
               "diskReadBytesPerSecond", "diskWriteBytesPerSecond")


class Hub:
    def __init__(self, endpoint: str, certificate: str, private_key: str, ca_bundle: str, timeout: float = 30.0):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("hub endpoint must be an HTTPS URL without credentials")
        self.host, self.port = parsed.hostname, parsed.port or 443
        self.context = ssl.create_default_context(cafile=ca_bundle)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.context.load_cert_chain(certificate, private_key)
        self.timeout = timeout

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=self.timeout)
        try:
            headers = {"content-length": str(len(body or b""))}
            if body is not None:
                headers["content-type"] = "application/octet-stream"
            connection.request(method, path, body=body or b"", headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def json(self, method: str, path: str, document: Any = None) -> tuple[int, Any]:
        status, raw = self.request(method, path, json.dumps(document).encode() if document is not None else b"")
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, None


def processes(units: list[str], metrics_dir: Path, run: Any = subprocess.run,
              proc: Path = Path("/proc")) -> tuple[dict[str, Any], dict[str, str]]:
    """Процессы проекта для панели и состояние служб из NODE_AGENT_UNITS.

    Состояние служб берётся из того же вызова systemctl show; отдельный
    is-active нужен только службам вне шаблона проекта."""
    found = hostinfo.tasks(run)
    states = {task["id"]: task["active"] for task in found}
    missing = [unit for unit in units if unit not in states]
    units_state = {unit: states[unit] for unit in units if unit in states}
    units_state.update(unit_states(missing))
    try:
        boot = hostinfo.boot_at((proc / "stat").read_text())
    except OSError:
        boot = None
    report = {"release": hostinfo.release(), "bootAt": boot, "tasks": found,
              **hostinfo.collector_processes(hostinfo.textfile(metrics_dir, hostinfo.COLLECTOR_PREFIXES))}
    return report, units_state


def sample_point(metrics: dict[str, Any], at: float, release: str | None) -> dict[str, Any]:
    point: dict[str, Any] = {"at": round(at, 3), "release": release}
    point.update({key: metrics.get(key) for key in SAMPLE_KEYS})
    return point


def unit_states(units: list[str]) -> dict[str, str]:
    if not units:
        return {}
    try:
        output = subprocess.run(["systemctl", "is-active", *units], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return dict(zip(units, output.split()))


def write_runtime(path: Path, runtime: dict[str, Any]) -> bool:
    """Записать runtime.json, если он изменился; True — записан новый."""
    encoded = json.dumps(runtime, ensure_ascii=False, sort_keys=True).encode()
    try:
        if path.read_bytes() == encoded:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".runtime-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


class Agent:
    def __init__(self, hub: Hub, root: Path, state_dir: Path, units: list[str], budget: float,
                 clock: Any = time.monotonic, metrics_dir: Path = DEFAULT_METRICS_DIR,
                 proc: Path = Path("/proc"), run: Any = subprocess.run) -> None:
        self.hub, self.root, self.state_dir, self.units = hub, root, state_dir, units
        self.budget, self.clock = budget, clock
        self.metrics_dir, self.proc, self.run = metrics_dir, proc, run
        self.state_path = state_dir / "state.json"
        self._state: dict[str, Any] = {}

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        state = {**self._state, "results": (self._state.get("results") or [])[-200:],
                 "samples": (self._state.get("samples") or [])[-MAX_QUEUED_SAMPLES:]}
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _load_results(self) -> list[dict[str, Any]]:
        return list(self._load_state().get("results") or [])

    def _save_results(self, results: list[dict[str, Any]]) -> None:
        self._state["results"] = results
        self._save_state()

    def run_once(self) -> dict[str, Any]:
        started = self.clock()
        store.ensure_layout(self.root)
        self._state = self._load_state()
        pending = list(self._state.get("results") or [])
        metrics = store.host_metrics(self.root)
        counters = hostinfo.counters(self.proc)
        metrics.update(hostinfo.rates(self._state.get("counters"), counters))
        found, units = processes(self.units, self.metrics_dir, self.run, self.proc)
        # Точка ложится в очередь до отправки: упади отправка или сам агент —
        # она уйдёт со следующим отчётом.
        samples = list(self._state.get("samples") or [])[-(MAX_QUEUED_SAMPLES - 1):]
        samples.append(sample_point(metrics, counters["at"], found.get("release")))
        self._state.update({"counters": counters, "samples": samples})
        self._save_state()
        report = {
            "agentVersion": VERSION,
            "metrics": metrics,
            "units": units,
            "processes": found,
            "inventory": store.inventory(self.root),
            "results": pending,
            "samples": samples,
        }
        status, answer = self.hub.json("POST", "/node/v1/report", report)
        if status != 200 or not isinstance(answer, dict):
            # Итоги и точки остаются в state.json до следующего удачного отчёта.
            logger.warning("node report rejected status=%s queued=%s", status, len(samples))
            return {"status": status, "done": 0}
        self._state["samples"] = []
        self._save_results([])
        runtime = answer.get("runtime")
        if isinstance(runtime, dict):
            write_runtime(self.state_dir / "runtime.json", runtime)
        results: list[dict[str, Any]] = []
        done = 0
        for task in answer.get("tasks") or []:
            if self.clock() - started > self.budget:
                break
            try:
                outcome = self._execute(task, started)
            except Exception as error:  # noqa: BLE001 — одно задание не останавливает другие
                logger.warning("node task failed object=%s class=%s", task.get("objectId"), type(error).__name__)
                outcome = {"objectId": task.get("objectId"), "state": "failed", "error": type(error).__name__}
            if outcome is not None:
                results.append(outcome)
                done += 1
        self._save_results(results)
        return {"status": status, "done": done, "tasks": len(answer.get("tasks") or [])}

    def _execute(self, task: dict[str, Any], started: float) -> dict[str, Any] | None:
        kind, name, object_id = task["kind"], task["name"], task["objectId"]
        final = store.object_path(self.root, kind, name)
        if task["type"] == "delete":
            final.unlink(missing_ok=True)
            store.incoming_path(self.root, object_id).unlink(missing_ok=True)
            return {"objectId": object_id, "state": "deleted"}
        if task["type"] == "fetch":
            return self._fetch(task, final, started)
        if task["type"] == "push":
            return self._push(task, final, started)
        return None

    def _fetch(self, task: dict[str, Any], final: Path, started: float) -> dict[str, Any]:
        object_id, size = task["objectId"], int(task["size"])
        if final.exists() and final.stat().st_size == size and store.sha256_file(final) == task["sha256"]:
            return {"objectId": object_id, "state": "verified", "sha256": task["sha256"], "bytes": size}
        partial = store.incoming_path(self.root, object_id)
        partial.parent.mkdir(parents=True, exist_ok=True)
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            partial.unlink()
            offset = 0
        with partial.open("ab") as handle:
            while offset < size:
                if self.clock() - started > self.budget:
                    return {"objectId": object_id, "state": "transferring", "bytes": offset}
                length = min(store.CHUNK_BYTES, size - offset)
                status, data = self.hub.request("GET", f"/node/v1/objects/{object_id}?offset={offset}&length={length}")
                if status != 200 or len(data) != length:
                    return {"objectId": object_id, "state": "failed", "error": f"http_{status}", "bytes": offset}
                handle.write(data)
                offset += len(data)
        digest = store.sha256_file(partial)
        if digest != task["sha256"]:
            partial.unlink(missing_ok=True)
            return {"objectId": object_id, "state": "failed", "error": "sha256_mismatch", "bytes": 0}
        store.publish(partial, final, task["kind"])
        return {"objectId": object_id, "state": "verified", "sha256": digest, "bytes": size}

    def _push(self, task: dict[str, Any], final: Path, started: float) -> dict[str, Any] | None:
        """Отдать свою копию основному; сверку и учёт делает основной при commit."""
        object_id, size = task["objectId"], int(task["size"])
        if not final.exists() or final.stat().st_size != size:
            return {"objectId": object_id, "state": "failed", "error": "missing_local_copy"}
        offset = 0
        with final.open("rb") as handle:
            while offset < size:
                if self.clock() - started > self.budget:
                    return None
                handle.seek(offset)
                chunk = handle.read(min(store.CHUNK_BYTES, size - offset))
                status, answer = self._put(object_id, offset, chunk)
                if status == 409 and isinstance(answer, dict) and isinstance(answer.get("offset"), int):
                    # Основной уже принял часть файла раньше — продолжаем с неё.
                    offset = answer["offset"]
                    continue
                if status != 200 or not isinstance(answer, dict):
                    return None
                offset = int(answer.get("offset", offset + len(chunk)))
        self.hub.json("POST", f"/node/v1/objects/{object_id}/commit", {})
        return None

    def _put(self, object_id: str, offset: int, chunk: bytes) -> tuple[int, Any]:
        status, raw = self.hub.request("PUT", f"/node/v1/objects/{object_id}?offset={offset}", chunk)
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # По умолчанию — адрес приёмника из окружения отправителя переноса.
    endpoint = (os.getenv("NODE_AGENT_HUB_URL", "").strip()
                or os.getenv("COLLECTOR_TRANSFER_HTTPS_ENDPOINT", "").strip())
    parsed = urlsplit(endpoint)
    hub = Hub(f"{parsed.scheme}://{parsed.netloc}",
              os.environ["NODE_AGENT_CERTIFICATE"], os.environ["NODE_AGENT_PRIVATE_KEY"],
              os.environ["NODE_AGENT_CA_BUNDLE"])
    agent = Agent(hub, Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT))),
                  Path(os.getenv("NODE_AGENT_STATE_DIR", str(DEFAULT_STATE_DIR))),
                  os.getenv("NODE_AGENT_UNITS", "").split(), float(os.getenv("NODE_AGENT_BUDGET_SECONDS", "50")),
                  metrics_dir=Path(os.getenv("NODE_AGENT_METRICS_DIR", str(DEFAULT_METRICS_DIR))))
    try:
        summary = agent.run_once()
    except (OSError, ssl.SSLError) as error:
        logger.warning("node agent unreachable hub class=%s", type(error).__name__)
        return 0
    logger.info("node agent run status=%s done=%s", summary.get("status"), summary.get("done"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
