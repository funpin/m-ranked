"""Узловая часть приёмника переноса на основном сервере (ADR-016).

Агенты других серверов говорят только с ним, по тому же mTLS, что и перенос
замеров: личность узла — имя в его сертификате, и оно должно быть в реестре
server_node. Приёмник отвечает на отчёт агента заданиями (скачать, отдать,
удалить файл), политикой сбора и составом сборщиков, отдаёт куски файлов
основного сервера и принимает куски файлов, которые основной должен получить.

Решения о размещении принимает сверщик основного сервера (main_agent.py);
здесь только исполнение и учёт.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from . import hostinfo, store

logger = logging.getLogger("transfer_ingest.node")

MAX_CHUNK = store.CHUNK_BYTES
# Агент отчитывается раз в минуту; без очереди точек (агент версии 1) строка
# истории пишется не чаще, чем раз в этот срок.
SAMPLE_EVERY_SECONDS = 50
# Точки из очереди агента: не больше трёх часов назад и не из будущего с
# поправкой на расхождение часов серверов.
SAMPLE_MAX_AGE_SECONDS = 4 * 3600
SAMPLE_MAX_AHEAD_SECONDS = 120
MAX_SAMPLES = 200
SAMPLE_FIELDS = {
    "diskTotalBytes": "disk_total_bytes", "diskFreeBytes": "disk_free_bytes", "storeBytes": "store_bytes",
    "memoryTotalBytes": "memory_total_bytes", "memoryAvailableBytes": "memory_available_bytes", "load1": "load1",
    "cpuPercent": "cpu_percent", "swapUsedBytes": "swap_used_bytes",
    "netRxBytesPerSecond": "net_rx_bytes_per_second", "netTxBytesPerSecond": "net_tx_bytes_per_second",
    "diskReadBytesPerSecond": "disk_read_bytes_per_second", "diskWriteBytesPerSecond": "disk_write_bytes_per_second",
}


class NodeRejected(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True, slots=True)
class NodeResponse:
    status: int
    body: Any
    binary: bytes | None = None


NODE_SQL = "SELECT id, role, state, platforms FROM ops_and_admin.server_node WHERE id = ANY(%(ids)s)"
NODES_SQL = "SELECT id, role, state, platforms FROM ops_and_admin.server_node"
POLICY_SQL = "SELECT name, value, version FROM ops_and_admin.runtime_policy"
HEARTBEAT_SQL = """
UPDATE ops_and_admin.server_node
   SET last_seen_at = transaction_timestamp(), agent_version = %(version)s, report = %(report)s::jsonb
 WHERE id = %(node)s
"""
LAST_SAMPLE_SQL = "SELECT max(observed_at) AS at FROM ops_and_admin.server_node_sample WHERE node_id = %(node)s"
# Время точки — время замера на узле; повтор той же точки (отчёт дошёл, а
# ответ потерялся) отсекает первичный ключ.
SAMPLE_SQL = f"""
INSERT INTO ops_and_admin.server_node_sample (node_id, observed_at, release, {", ".join(SAMPLE_FIELDS.values())})
VALUES (%(node)s, coalesce(to_timestamp(%(at)s), transaction_timestamp()), %(release)s,
        {", ".join(f"%({key})s" for key in SAMPLE_FIELDS)})
ON CONFLICT (node_id, observed_at) DO NOTHING
"""
TASKS_SQL = """
SELECT replica.object_id::text AS object_id, replica.state, object.kind, object.name, object.size_bytes,
       object.sha256, replica.bytes_done,
       EXISTS (SELECT 1 FROM ops_and_admin.storage_replica main_copy
                 JOIN ops_and_admin.server_node main_node ON main_node.id = main_copy.node_id
                WHERE main_copy.object_id = replica.object_id AND main_node.role = 'main'
                  AND main_copy.state = 'verified') AS on_main
  FROM ops_and_admin.storage_replica replica
  JOIN ops_and_admin.storage_object object ON object.id = replica.object_id
 WHERE replica.node_id = %(node)s AND replica.state IN ('wanted', 'transferring', 'deleting')
 ORDER BY object.created_at
"""
# Отдать файл основному: основной ждёт копию, у узла она подтверждена, и из
# всех таких узлов этот — первый по имени (одна выгрузка на объект).
PUSH_SQL = """
SELECT object.id::text AS object_id, object.kind, object.name, object.size_bytes, object.sha256,
       main_copy.bytes_done
  FROM ops_and_admin.storage_replica main_copy
  JOIN ops_and_admin.server_node main_node ON main_node.id = main_copy.node_id AND main_node.role = 'main'
  JOIN ops_and_admin.storage_object object ON object.id = main_copy.object_id
 WHERE main_copy.state IN ('wanted', 'transferring')
   AND %(node)s = (SELECT min(holder.node_id) FROM ops_and_admin.storage_replica holder
                    JOIN ops_and_admin.server_node holder_node ON holder_node.id = holder.node_id
                   WHERE holder.object_id = object.id AND holder.state = 'verified'
                     AND holder_node.state <> 'disabled')
"""
RESULT_SQL = """
UPDATE ops_and_admin.storage_replica
   SET state = %(state)s, error = %(error)s, bytes_done = %(bytes)s,
       verified_at = CASE WHEN %(state)s = 'verified' THEN transaction_timestamp() ELSE verified_at END,
       attempts = attempts + CASE WHEN %(state)s = 'failed' THEN 1 ELSE 0 END,
       updated_at = transaction_timestamp()
 WHERE object_id = %(object)s::uuid AND node_id = %(node)s AND state <> 'deleted'
"""
OBJECT_SQL = """
SELECT object.id::text AS object_id, object.kind, object.name, object.size_bytes, object.sha256,
       (SELECT state FROM ops_and_admin.storage_replica WHERE object_id = object.id AND node_id = %(node)s) AS node_state,
       (SELECT copy.state FROM ops_and_admin.storage_replica copy
          JOIN ops_and_admin.server_node main_node ON main_node.id = copy.node_id AND main_node.role = 'main'
         WHERE copy.object_id = object.id) AS main_state
  FROM ops_and_admin.storage_object object WHERE object.id = %(object)s::uuid
"""


def membership(nodes: list[Mapping[str, Any]]) -> str | None:
    """Строка COLLECTOR_MEMBERSHIP из реестра: подключённые сборщики и их площадки.

    Пока сборщик один, состава нет: он собирает всё, как без размещения, и
    подключение агента не меняет его поведения. Размещение включается со
    вторым сборщиком.
    """
    entries = [f"{node['id']}:{'|'.join(sorted(node['platforms']))}" for node in sorted(nodes, key=lambda n: n["id"])
               if node["role"] == "collector" and node["state"] == "active" and node["platforms"]]
    return ",".join(entries) if len(entries) > 1 else None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value == value and abs(value) < 1e18 else None  # NaN и бесконечности — мимо


def _release(value: Any) -> str | None:
    return value if isinstance(value, str) and hostinfo.RELEASE.fullmatch(value) else None


TASK_TEXT = {"unit": 80, "active": 20, "sub": 20, "result": 30, "timerActive": 20}
TASK_NUMBERS = ("since", "startedAt", "exitedAt", "restarts", "lastAt", "nextAt")


def _clean_processes(value: Any) -> dict[str, Any]:
    """Процессы узла: только известные поля, строки и списки ограничены."""
    if not isinstance(value, dict):
        return {}
    tasks = []
    for item in (value.get("tasks") if isinstance(value.get("tasks"), list) else [])[:hostinfo.MAX_TASKS]:
        if not isinstance(item, dict) or not isinstance(item.get("unit"), str):
            continue
        task: dict[str, Any] = {key: str(item[key])[:limit] for key, limit in TASK_TEXT.items()
                                if isinstance(item.get(key), str)}
        task["scheduled"] = bool(item.get("scheduled"))
        task.update({key: _number(item.get(key)) for key in TASK_NUMBERS if _number(item.get(key)) is not None})
        tasks.append(task)
    collectors = {}
    raw = value.get("collectors") if isinstance(value.get("collectors"), dict) else {}
    for platform in hostinfo.PLATFORMS:
        entry = raw.get(platform)
        if isinstance(entry, dict):
            collectors[platform] = {key: _number(entry.get(key)) for key in (
                "lastSuccessAt", "cycleSeconds", "scheduleLagSeconds", "shutdowns", "providerErrors")
                if _number(entry.get(key)) is not None}
    transfer = value.get("transfer") if isinstance(value.get("transfer"), dict) else None
    return {
        "release": _release(value.get("release")), "bootAt": _number(value.get("bootAt")), "tasks": tasks,
        "collectors": collectors,
        "transfer": {key: _number(transfer.get(key)) for key in ("backlog", "delivered", "failures")
                     if _number(transfer.get(key)) is not None} if transfer else None,
    }


def clean_samples(report: Mapping[str, Any], now: float) -> list[dict[str, Any]]:
    """Минутные точки из очереди агента: числа, время в разумных пределах."""
    samples = report.get("samples") if isinstance(report.get("samples"), list) else []
    result, seen = [], set()
    for item in samples[-MAX_SAMPLES:]:
        if not isinstance(item, dict):
            continue
        at = _number(item.get("at"))
        if at is None or not now - SAMPLE_MAX_AGE_SECONDS <= at <= now + SAMPLE_MAX_AHEAD_SECONDS or at in seen:
            continue
        seen.add(at)
        result.append({"at": at, "release": _release(item.get("release")),
                       **{key: _number(item.get(key)) for key in SAMPLE_FIELDS}})
    return result


def _clean_report(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    numeric = {key: metrics.get(key) for key in (
        "diskTotalBytes", "diskFreeBytes", "storeBytes", "rootTotalBytes", "rootFreeBytes",
        "memoryTotalBytes", "memoryAvailableBytes", "swapUsedBytes", "load1", "load5", "load15", "cpus",
        "cpuPercent", "netRxBytesPerSecond", "netTxBytesPerSecond", "diskReadBytesPerSecond",
        "diskWriteBytesPerSecond")
        if _number(metrics.get(key)) is not None}
    units = report.get("units") if isinstance(report.get("units"), dict) else {}
    units = {str(key)[:80]: str(value)[:20] for key, value in list(units.items())[:40]}
    inventory = report.get("inventory") if isinstance(report.get("inventory"), list) else []
    files = [{"name": str(item.get("name"))[:200], "size": int(item.get("size") or 0)}
             for item in inventory[:2000] if isinstance(item, dict)]
    return {"metrics": numeric, "units": units, "files": files, "transfers": report.get("transfers") or {},
            "processes": _clean_processes(report.get("processes"))}


class NodeHub:
    def __init__(self, connect: Callable[[], Any], root: Path = store.DEFAULT_ROOT,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._connect = connect
        self.root = root
        self._clock = clock

    # --- личность ---------------------------------------------------------
    def node_for(self, identities: tuple[str, ...]) -> Mapping[str, Any]:
        candidates = [identity.split("/", 1)[0] for identity in identities if identity]
        with self._connect() as connection:
            rows = connection.execute(NODE_SQL, {"ids": candidates}).fetchall()
        known = [row for row in rows if row["state"] != "disabled"]
        if not known:
            raise NodeRejected(403, "node_not_registered")
        return known[0]

    def allowed_producers(self) -> tuple[str, ...]:
        """Имена серверов, которым разрешён перенос замеров: подключённые сборщики."""
        with self._connect() as connection:
            rows = connection.execute(NODES_SQL).fetchall()
        return tuple(row["id"] for row in rows if row["role"] == "collector" and row["state"] in {"active", "draining"})

    # --- отчёт ------------------------------------------------------------
    def report(self, identities: tuple[str, ...], body: bytes) -> NodeResponse:
        node = self.node_for(identities)
        try:
            report = json.loads(body or b"{}")
        except ValueError as error:
            raise NodeRejected(400, "malformed_report") from error
        if not isinstance(report, dict):
            raise NodeRejected(400, "malformed_report")
        cleaned = _clean_report(report)
        with self._connect() as connection:
            with connection.transaction():
                connection.execute(HEARTBEAT_SQL, {"node": node["id"], "version": str(report.get("agentVersion", ""))[:40],
                                                   "report": json.dumps(cleaned)})
                samples = clean_samples(report, time.time())
                if samples:
                    with connection.cursor() as cursor:
                        cursor.executemany(SAMPLE_SQL, [{"node": node["id"], **sample} for sample in samples])
                else:
                    last = connection.execute(LAST_SAMPLE_SQL, {"node": node["id"]}).fetchone()
                    if last is None or last["at"] is None or (time.time() - last["at"].timestamp()) >= SAMPLE_EVERY_SECONDS:
                        metrics = {key: cleaned["metrics"].get(key) for key in SAMPLE_FIELDS}
                        connection.execute(SAMPLE_SQL, {"node": node["id"], "at": None, "release": None, **metrics})
                for result in (report.get("results") or [])[:200]:
                    self._apply_result(connection, node["id"], result)
            tasks = self._tasks(connection, node["id"])
            policies = {row["name"]: {"value": row["value"], "version": row["version"]}
                        for row in connection.execute(POLICY_SQL).fetchall()}
            nodes = connection.execute(NODES_SQL).fetchall()
        collection = policies.get("collection", {"value": {}, "version": 0})
        version = f"{collection['version']}:{membership(nodes) or '-'}"
        return NodeResponse(200, {
            "node": node["id"], "state": node["state"], "tasks": tasks,
            "runtime": {"version": version, "membership": membership(nodes),
                        "collection": collection["value"]},
        })

    def _apply_result(self, connection: Any, node: str, result: Any) -> None:
        if not isinstance(result, dict) or not store.OBJECT_ID.fullmatch(str(result.get("objectId", ""))):
            return
        outcome = result.get("state")
        current = connection.execute(OBJECT_SQL, {"object": result["objectId"], "node": node}).fetchone()
        if current is None or current["node_state"] is None:
            return
        if outcome == "verified":
            # Узел сверил свою копию сам; здесь — что сверял с тем же образцом.
            if result.get("sha256") != current["sha256"]:
                outcome, error = "failed", "sha256_mismatch"
            else:
                error = None
        elif outcome == "deleted" and current["node_state"] == "deleting":
            error = None
        elif outcome == "failed":
            error = str(result.get("error", "failed"))[:200]
        elif outcome == "transferring":
            error = None
        else:
            return
        connection.execute(RESULT_SQL, {"object": result["objectId"], "node": node, "state": outcome,
                                        "error": error, "bytes": int(result.get("bytes") or 0)})

    def _tasks(self, connection: Any, node: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for row in connection.execute(TASKS_SQL, {"node": node}).fetchall():
            base = {"objectId": row["object_id"], "kind": row["kind"], "name": row["name"],
                    "size": row["size_bytes"], "sha256": row["sha256"]}
            if row["state"] == "deleting":
                tasks.append({"type": "delete", **base})
            elif row["on_main"]:
                tasks.append({"type": "fetch", **base})
        for row in connection.execute(PUSH_SQL, {"node": node}).fetchall():
            tasks.append({"type": "push", "objectId": row["object_id"], "kind": row["kind"], "name": row["name"],
                          "size": row["size_bytes"], "sha256": row["sha256"]})
        return tasks

    # --- файлы ------------------------------------------------------------
    def _object(self, node: str, object_id: str) -> Mapping[str, Any]:
        if not store.OBJECT_ID.fullmatch(object_id):
            raise NodeRejected(404, "unknown_object")
        with self._connect() as connection:
            row = connection.execute(OBJECT_SQL, {"object": object_id, "node": node}).fetchone()
        if row is None:
            raise NodeRejected(404, "unknown_object")
        return row

    def read_chunk(self, identities: tuple[str, ...], object_id: str, offset: int, length: int) -> NodeResponse:
        node = self.node_for(identities)
        row = self._object(node["id"], object_id)
        # Отдаётся только то, что узлу поручено забрать и что подтверждено здесь.
        if row["node_state"] not in {"wanted", "transferring"} or row["main_state"] != "verified":
            raise NodeRejected(403, "object_not_assigned")
        if offset < 0 or length < 1 or length > MAX_CHUNK or offset > row["size_bytes"]:
            raise NodeRejected(400, "bad_range")
        path = store.object_path(self.root, row["kind"], row["name"])
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
            # Прочитанное не нужно в кэше: страницы файла засчитываются в
            # потолок памяти приёмника, а дамп — гигабайты.
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(handle.fileno(), offset, len(data), os.POSIX_FADV_DONTNEED)
        return NodeResponse(200, None, data)

    def write_chunk(self, identities: tuple[str, ...], object_id: str, offset: int, data: bytes) -> NodeResponse:
        node = self.node_for(identities)
        row = self._object(node["id"], object_id)
        if row["main_state"] not in {"wanted", "transferring"} or row["node_state"] != "verified":
            raise NodeRejected(403, "object_not_assigned")
        if len(data) > MAX_CHUNK:
            raise NodeRejected(413, "chunk_too_large")
        partial = store.incoming_path(self.root, object_id)
        partial.parent.mkdir(parents=True, exist_ok=True)
        current = partial.stat().st_size if partial.exists() else 0
        if offset != current:
            # Докачка с того места, где копия оборвалась: агент спросит заново.
            return NodeResponse(409, {"error": "offset_mismatch", "offset": current})
        if current + len(data) > row["size_bytes"]:
            raise NodeRejected(400, "object_too_large")
        with partial.open("ab") as handle:
            handle.write(data)
        written = current + len(data)
        self._set_main(row["object_id"], "transferring", None, written)
        return NodeResponse(200, {"offset": written})

    def commit(self, identities: tuple[str, ...], object_id: str) -> NodeResponse:
        node = self.node_for(identities)
        row = self._object(node["id"], object_id)
        if row["main_state"] not in {"wanted", "transferring"} or row["node_state"] != "verified":
            raise NodeRejected(403, "object_not_assigned")
        partial = store.incoming_path(self.root, object_id)
        if not partial.exists() or partial.stat().st_size != row["size_bytes"]:
            raise NodeRejected(409, "incomplete_object")
        if store.sha256_file(partial) != row["sha256"]:
            partial.unlink(missing_ok=True)
            self._set_main(row["object_id"], "failed", "sha256_mismatch", 0)
            return NodeResponse(409, {"error": "sha256_mismatch"})
        store.publish(partial, store.object_path(self.root, row["kind"], row["name"]), row["kind"])
        self._set_main(row["object_id"], "verified", None, row["size_bytes"])
        return NodeResponse(200, {"state": "verified"})

    def _set_main(self, object_id: str, state: str, error: str | None, done: int) -> None:
        with self._connect() as connection:
            connection.execute("""
                UPDATE ops_and_admin.storage_replica replica
                   SET state = %(state)s, error = %(error)s, bytes_done = %(bytes)s, updated_at = transaction_timestamp(),
                       verified_at = CASE WHEN %(state)s = 'verified' THEN transaction_timestamp() ELSE verified_at END,
                       attempts = attempts + CASE WHEN %(state)s = 'failed' THEN 1 ELSE 0 END
                  FROM ops_and_admin.server_node node
                 WHERE replica.object_id = %(object)s::uuid AND node.id = replica.node_id AND node.role = 'main'
                   AND replica.state IN ('wanted', 'transferring')""",
                {"object": object_id, "state": state, "error": error, "bytes": done})


def hub_from_environment(dsn: str) -> NodeHub:
    import psycopg
    from psycopg.rows import dict_row

    def connect() -> Any:
        return psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)

    return NodeHub(connect, Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT))))
