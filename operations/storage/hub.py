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

from . import store

logger = logging.getLogger("transfer_ingest.node")

MAX_CHUNK = store.CHUNK_BYTES
SAMPLE_EVERY_SECONDS = 300


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
SAMPLE_SQL = """
INSERT INTO ops_and_admin.server_node_sample (node_id, disk_total_bytes, disk_free_bytes, store_bytes,
       memory_total_bytes, memory_available_bytes, load1)
VALUES (%(node)s, %(diskTotalBytes)s, %(diskFreeBytes)s, %(storeBytes)s, %(memoryTotalBytes)s,
        %(memoryAvailableBytes)s, %(load1)s)
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
    """Строка COLLECTOR_MEMBERSHIP из реестра: подключённые сборщики и их площадки."""
    entries = [f"{node['id']}:{'|'.join(sorted(node['platforms']))}" for node in sorted(nodes, key=lambda n: n["id"])
               if node["role"] == "collector" and node["state"] == "active" and node["platforms"]]
    return ",".join(entries) or None


def _clean_report(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    numeric = {key: metrics.get(key) for key in (
        "diskTotalBytes", "diskFreeBytes", "storeBytes", "rootTotalBytes", "rootFreeBytes",
        "memoryTotalBytes", "memoryAvailableBytes", "load1", "cpus")
        if isinstance(metrics.get(key), (int, float)) and not isinstance(metrics.get(key), bool)}
    units = report.get("units") if isinstance(report.get("units"), dict) else {}
    units = {str(key)[:80]: str(value)[:20] for key, value in list(units.items())[:40]}
    inventory = report.get("inventory") if isinstance(report.get("inventory"), list) else []
    files = [{"name": str(item.get("name"))[:200], "size": int(item.get("size") or 0)}
             for item in inventory[:2000] if isinstance(item, dict)]
    return {"metrics": numeric, "units": units, "files": files, "transfers": report.get("transfers") or {}}


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
                last = connection.execute(LAST_SAMPLE_SQL, {"node": node["id"]}).fetchone()
                if last is None or last["at"] is None or (time.time() - last["at"].timestamp()) >= SAMPLE_EVERY_SECONDS:
                    metrics = {key: cleaned["metrics"].get(key) for key in (
                        "diskTotalBytes", "diskFreeBytes", "storeBytes", "memoryTotalBytes",
                        "memoryAvailableBytes", "load1")}
                    connection.execute(SAMPLE_SQL, {"node": node["id"], **metrics})
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
