"""Серверы, хранение и холодный архив в панели управления (ADR-016).

Чтение — одна сводка для вкладки «Серверы»: реестр серверов с дисками и
памятью из последнего отчёта агента, политики, резервные копии и месяцы
архива с копиями по серверам, задания панели.

Команды приходят формами через фасад /manage/... (как команды каталога) и
отвечают адресом возврата. Ошибку проверки форма показывает по коду в адресе
(storage_error=...), а не страницей ошибки: администратор видит, какое поле
не так, и данные формы не теряются в истории браузера.

Решения о размещении принимает сверщик основного сервера
(operations/storage/main_agent.py); здесь только реестр и политики.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import re
from typing import Any, Iterable, Mapping

from collector_target.runtime_policy import LIMITS as COLLECTION_LIMITS, validate_collection_policy
from operations.storage.reconcile import validate_storage_policy

PLATFORMS = ("telegram", "vk", "max", "rutube")
NODE_ID = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
GIB = 1024 ** 3
# Агент отчитывается раз в минуту; три пропуска подряд — сервер не на связи.
ONLINE_SECONDS = 180
FINAL_ANALYSIS_LIMITS = (3, 3650)

SERVERS_SQL = """
SELECT node.id, node.display_name, node.role, node.platforms, node.state, node.stores_objects,
       node.reserve_bytes, node.last_seen_at, node.agent_version, node.report, node.updated_at, node.updated_by
  FROM ops_and_admin.server_node node
 ORDER BY node.role <> 'main', node.id
"""
REPLICA_TOTALS_SQL = """
SELECT replica.node_id, replica.state, count(*)::integer AS objects, coalesce(sum(object.size_bytes), 0)::bigint AS bytes
  FROM ops_and_admin.storage_replica replica
  JOIN ops_and_admin.storage_object object ON object.id = replica.object_id
 WHERE replica.state <> 'deleted'
 GROUP BY 1, 2
"""
POLICIES_SQL = "SELECT name, value, version, updated_at, updated_by FROM ops_and_admin.runtime_policy"
OBJECTS_SQL = """
SELECT object.id::text, object.kind, object.name, object.size_bytes, object.created_at, object.retired_at,
       object.published_month, object.generation,
       coalesce(jsonb_agg(jsonb_build_object(
           'node', replica.node_id, 'state', replica.state, 'bytesDone', replica.bytes_done,
           'error', replica.error, 'verifiedAt', replica.verified_at) ORDER BY replica.node_id)
         FILTER (WHERE replica.node_id IS NOT NULL AND replica.state <> 'deleted'), '[]') AS replicas
  FROM ops_and_admin.storage_object object
  LEFT JOIN ops_and_admin.storage_replica replica ON replica.object_id = object.id
 WHERE (object.kind = 'backup' AND (object.retired_at IS NULL OR object.retired_at > now() - interval '2 days'))
    OR object.kind <> 'backup'
 GROUP BY object.id
 ORDER BY object.created_at DESC
 LIMIT 400
"""
class StorageCommandError(ValueError):
    """Ошибка проверки формы; code уходит в адрес возврата."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def server_view(row: Mapping[str, Any], totals: Iterable[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    report = row["report"] if isinstance(row["report"], dict) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    seen = row["last_seen_at"]
    copies: dict[str, dict[str, int]] = {}
    for item in totals:
        if item["node_id"] == row["id"]:
            copies[item["state"]] = {"objects": item["objects"], "bytes": item["bytes"]}
    return {
        "id": row["id"], "displayName": row["display_name"], "role": row["role"],
        "platforms": sorted(row["platforms"] or [], key=PLATFORMS.index), "state": row["state"],
        "storesObjects": row["stores_objects"], "reserveBytes": row["reserve_bytes"],
        "lastSeenAt": _iso(seen), "online": bool(seen and (now - seen).total_seconds() <= ONLINE_SECONDS),
        "agentVersion": row["agent_version"],
        "disk": {"totalBytes": _int(metrics.get("diskTotalBytes")), "freeBytes": _int(metrics.get("diskFreeBytes")),
                 "storeBytes": _int(metrics.get("storeBytes")), "rootTotalBytes": _int(metrics.get("rootTotalBytes")),
                 "rootFreeBytes": _int(metrics.get("rootFreeBytes"))},
        "memory": {"totalBytes": _int(metrics.get("memoryTotalBytes")),
                   "availableBytes": _int(metrics.get("memoryAvailableBytes"))},
        "load1": metrics.get("load1") if isinstance(metrics.get("load1"), (int, float)) else None,
        "cpus": _int(metrics.get("cpus")),
        "units": {str(key): str(value) for key, value in (report.get("units") or {}).items()},
        "copies": copies, "updatedAt": _iso(row["updated_at"]), "updatedBy": row["updated_by"],
    }


def _object_view(row: Mapping[str, Any]) -> dict[str, Any]:
    replicas = row["replicas"] if isinstance(row["replicas"], list) else json.loads(row["replicas"] or "[]")
    return {"id": row["id"], "kind": row["kind"], "name": row["name"], "sizeBytes": row["size_bytes"],
            "createdAt": _iso(row["created_at"]), "retired": row["retired_at"] is not None,
            "replicas": replicas}


async def overview(connection: Any, now: datetime) -> dict[str, Any]:
    async def rows(sql: str) -> list[dict[str, Any]]:
        return await (await connection.execute(sql)).fetchall()

    servers, totals, policies = await rows(SERVERS_SQL), await rows(REPLICA_TOTALS_SQL), await rows(POLICIES_SQL)
    objects = [_object_view(row) for row in await rows(OBJECTS_SQL)]
    by_id = {item["id"]: item for item in objects}
    policy = {row["name"]: {"value": row["value"], "version": row["version"],
                            "updatedAt": _iso(row["updated_at"]), "updatedBy": row["updated_by"]}
              for row in policies}
    return {
        "servers": [server_view(row, totals, now) for row in servers],
        "policies": policy,
        "limits": {"collection": {key: list(value) for key, value in COLLECTION_LIMITS.items()},
                   "finalAnalysisDays": list(FINAL_ANALYSIS_LIMITS)},
        "backups": [item for item in objects if item["kind"] == "backup"][:30],
    }


# --- проверка форм ----------------------------------------------------------

def _checked(fields: Mapping[str, str], name: str) -> bool:
    return fields.get(name, "") in {"on", "true", "1"}


def _whole(fields: Mapping[str, str], name: str, low: int, high: int, code: str, *,
           optional: bool = False) -> int | None:
    raw = fields.get(name, "").strip()
    if not raw and optional:
        return None
    if not re.fullmatch(r"[0-9]{1,6}", raw) or not low <= int(raw) <= high:
        raise StorageCommandError(code)
    return int(raw)


def server_fields(fields: Mapping[str, str], *, role: str) -> dict[str, Any]:
    name = fields.get("display_name", "").strip()
    if not name or len(name) > 80:
        raise StorageCommandError("server-name")
    platforms = [platform for platform in PLATFORMS if _checked(fields, f"platform_{platform}")]
    if platforms and role != "collector":
        raise StorageCommandError("server-platforms")
    reserve = _whole(fields, "reserve_gb", 0, 1000, "server-reserve")
    return {"display_name": name, "platforms": platforms, "stores_objects": _checked(fields, "stores_objects"),
            "reserve_bytes": int(reserve or 0) * GIB}


def new_server(fields: Mapping[str, str]) -> dict[str, Any]:
    node_id = fields.get("id", "").strip()
    if not NODE_ID.fullmatch(node_id):
        raise StorageCommandError("server-id")
    role = fields.get("role", "")
    if role not in {"collector", "storage"}:
        raise StorageCommandError("server-role")
    state = fields.get("state", "active")
    if state not in {"pending", "active"}:
        raise StorageCommandError("server-state")
    return {"id": node_id, "role": role, "state": state, **server_fields(fields, role=role)}


def collection_policy(fields: Mapping[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, (low, high) in COLLECTION_LIMITS.items():
        value[key] = _whole(fields, key, low, high, "policy-collection", optional=True)
    value["heartbeatMaxAgeDays"] = _whole(fields, "heartbeatMaxAgeDays", 1, 3650, "policy-collection",
                                          optional=True)
    try:
        return validate_collection_policy(value)
    except ValueError as error:
        raise StorageCommandError("policy-collection") from error


def storage_policy(fields: Mapping[str, str], node_ids: Iterable[str], current: Mapping[str, Any]) -> dict[str, Any]:
    nodes = list(node_ids)
    # Холодный архив выведен (0063): его поля политики остаются прежними —
    # схему читают агенты обоих серверов, — но из формы больше не меняются.
    value = {
        "coldAfterDays": int(current.get("coldAfterDays", 30)),
        "backupCopies": _whole(fields, "backupCopies", 1, 14, "policy-backup-copies"),
        "backupNodes": [node for node in nodes if _checked(fields, f"backup_{node}")],
        # Последняя проверенная восстановлением копия — отдельно (0064).
        "verifiedBackupNodes": [node for node in nodes if _checked(fields, f"verified_{node}")],
        "archiveNodes": [node for node in current.get("archiveNodes", nodes) if node in nodes] or nodes,
        "browseCacheBytes": current.get("browseCacheBytes", 2 * GIB),
    }
    if len(value["backupNodes"]) < 1:
        raise StorageCommandError("policy-backup-nodes")
    try:
        return validate_storage_policy(value, nodes)
    except ValueError as error:
        raise StorageCommandError("policy-storage") from error


def analysis_policy(fields: Mapping[str, str]) -> dict[str, Any]:
    return {"finalAnalysisDays": _whole(fields, "finalAnalysisDays", *FINAL_ANALYSIS_LIMITS, "policy-analysis",
                                        optional=True)}


# --- команды ----------------------------------------------------------------

SERVER_PATH = re.compile(r"/manage/servers/([a-z][a-z0-9-]{1,39})")
POLICY_PATH = re.compile(r"/manage/policies/(collection|storage|analysis)")
STORAGE_PATHS = re.compile(r"/manage/(?:servers(?:/[^/]+)?|policies/[a-z]+)")


def is_storage_path(path: str) -> bool:
    return bool(STORAGE_PATHS.fullmatch(path))


def _back(status: str | None = None, error: str | None = None) -> str:
    query = "tab=servers"
    if status:
        query += f"&storage_status={status}"
    if error:
        query += f"&storage_error={error}"
    return f"/manage?{query}"


async def _policy(connection: Any, name: str) -> dict[str, Any]:
    row = await (await connection.execute(
        "SELECT value FROM ops_and_admin.runtime_policy WHERE name = %(name)s FOR UPDATE", {"name": name})).fetchone()
    return dict(row["value"]) if row else {}


async def _save_policy(connection: Any, name: str, value: Mapping[str, Any], actor: str) -> None:
    # Строки политик создаёт миграция 0057; у роли панели только UPDATE.
    await connection.execute("""
        UPDATE ops_and_admin.runtime_policy
           SET value = %(value)s::jsonb, version = version + 1, updated_at = transaction_timestamp(),
               updated_by = %(actor)s
         WHERE name = %(name)s""", {"name": name, "value": json.dumps(value), "actor": actor})


async def execute(connection: Any, path: str, fields: Mapping[str, str], actor: str) -> str:
    """Выполнить команду вкладки «Серверы»; вернуть адрес возврата."""
    try:
        async with connection.transaction():
            return await _execute(connection, path, fields, actor)
    except StorageCommandError as error:
        return _back(error=error.code)


async def _execute(connection: Any, path: str, fields: Mapping[str, str], actor: str) -> str:
    if path == "/manage/servers":
        server = new_server(fields)
        row = await (await connection.execute("""
            INSERT INTO ops_and_admin.server_node (id, display_name, role, platforms, state, stores_objects,
                   reserve_bytes, updated_by)
            VALUES (%(id)s, %(display_name)s, %(role)s, %(platforms)s, %(state)s, %(stores_objects)s,
                    %(reserve_bytes)s, %(actor)s)
            ON CONFLICT (id) DO NOTHING RETURNING id""", {**server, "actor": actor})).fetchone()
        if row is None:
            raise StorageCommandError("server-exists")
        return _back("server-added")

    match = SERVER_PATH.fullmatch(path)
    if match:
        current = await (await connection.execute(
            "SELECT id, role, state FROM ops_and_admin.server_node WHERE id = %(id)s FOR UPDATE",
            {"id": match.group(1)})).fetchone()
        if current is None:
            raise StorageCommandError("server-missing")
        values = server_fields(fields, role=current["role"])
        state = fields.get("state", current["state"])
        allowed = {"active"} if current["role"] == "main" else {"pending", "active", "draining", "disabled"}
        if state not in allowed:
            raise StorageCommandError("server-state")
        await connection.execute("""
            UPDATE ops_and_admin.server_node
               SET display_name = %(display_name)s, platforms = %(platforms)s, state = %(state)s,
                   stores_objects = %(stores_objects)s, reserve_bytes = %(reserve_bytes)s,
                   updated_at = transaction_timestamp(), updated_by = %(actor)s
             WHERE id = %(id)s""", {**values, "state": state, "id": current["id"], "actor": actor})
        return _back("server-updated")

    match = POLICY_PATH.fullmatch(path)
    if match:
        name = match.group(1)
        storage = await _policy(connection, "storage")
        if name == "collection":
            await _policy(connection, "collection")
            value = collection_policy(fields)
        elif name == "storage":
            nodes = [row["id"] for row in await (await connection.execute(
                "SELECT id FROM ops_and_admin.server_node ORDER BY id")).fetchall()]
            value = storage_policy(fields, nodes, storage)
        else:
            value = analysis_policy(fields)
        await _save_policy(connection, name, value, actor)
        return _back(f"policy-{name}")

    raise StorageCommandError("unknown")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
