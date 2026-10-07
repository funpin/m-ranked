"""Агент узла: отчёт основному серверу и исполнение заданий хранилища.

Работает на каждом сервере, кроме основного, раз в минуту (таймер systemd) и
только на стандартной библиотеке. За один запуск:

1. снимает метрики машины, состояние служб и опись файлов хранилища;
2. отправляет отчёт с итогами прошлых заданий на /node/v1/report по mTLS —
   тот же адрес, сертификат и CA, что у отправителя переноса;
3. пишет runtime.json (политика сбора и состав сборщиков) атомарно — сборщики
   перечитывают его в начале цикла;
4. исполняет задания в пределах бюджета времени: скачивает куски файла с
   основного, отдаёт свой файл основному или удаляет лишнюю копию. Недокачанная
   копия лежит в incoming и продолжается со следующего запуска.

Итоги заданий хранятся в state.json до подтверждения основным: обрыв связи
не теряет ни результата, ни докачки.
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

from . import store

logger = logging.getLogger("node-agent")
VERSION = "1"
DEFAULT_STATE_DIR = Path("/var/lib/m-ranked/node-agent")


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
                 clock: Any = time.monotonic) -> None:
        self.hub, self.root, self.state_dir, self.units = hub, root, state_dir, units
        self.budget, self.clock = budget, clock
        self.state_path = state_dir / "state.json"

    def _load_results(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value.get("results", []) if isinstance(value, dict) else []
        except (FileNotFoundError, ValueError):
            return []

    def _save_results(self, results: list[dict[str, Any]]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"results": results[-200:]}), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def run_once(self) -> dict[str, Any]:
        started = self.clock()
        store.ensure_layout(self.root)
        pending = self._load_results()
        report = {
            "agentVersion": VERSION,
            "metrics": store.host_metrics(self.root),
            "units": unit_states(self.units),
            "inventory": store.inventory(self.root),
            "results": pending,
        }
        status, answer = self.hub.json("POST", "/node/v1/report", report)
        if status != 200 or not isinstance(answer, dict):
            # Итоги остаются в state.json до следующего удачного отчёта.
            logger.warning("node report rejected status=%s", status)
            return {"status": status, "done": 0}
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
                  os.getenv("NODE_AGENT_UNITS", "").split(), float(os.getenv("NODE_AGENT_BUDGET_SECONDS", "50")))
    try:
        summary = agent.run_once()
    except (OSError, ssl.SSLError) as error:
        logger.warning("node agent unreachable hub class=%s", type(error).__name__)
        return 0
    logger.info("node agent run status=%s done=%s", summary.get("status"), summary.get("done"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
