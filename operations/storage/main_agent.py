"""Агент основного сервера: учёт файлов, сверка размещения, запуск заданий.

Раз в минуту (таймер systemd, root — ему нужны дампы базы и хранилище):

1. пишет метрики машины в реестр серверов, как агенты других узлов;
2. регистрирует законченные дампы базы как резервные копии (жёсткая ссылка в
   хранилище, без второй копии на диске);
3. сверяет свою опись с базой: пропавшая копия снова становится нужной;
4. возвращает в работу копии, упавшие при передаче, с нарастающей паузой;
5. применяет решение сверщика (reconcile.plan): заказывает копии, удаляет
   лишние, выводит старые резервные копии;
6. запускает задания из панели — архивацию месяца и анализ архива.
"""
from __future__ import annotations

from datetime import datetime, timezone
import errno
import grp
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import uuid

from . import reconcile, store
from .agent import unit_states

logger = logging.getLogger("node-agent-main")
DUMP = re.compile(r"^mranked-[0-9]{8}T[0-9]{6}Z\.dump$")
RETRY_BASE_SECONDS = 120
RETRY_MAX_ATTEMPTS = 40

NODES_SQL = """
SELECT id, role, state, stores_objects, reserve_bytes, last_seen_at,
       (report->'metrics'->>'diskFreeBytes')::bigint AS free_bytes
  FROM ops_and_admin.server_node
"""
OBJECTS_SQL = "SELECT id::text, kind, name, size_bytes, sha256, created_at, retired_at FROM ops_and_admin.storage_object"
REPLICAS_SQL = "SELECT object_id::text, node_id, state FROM ops_and_admin.storage_replica"


def _main_id(connection: Any) -> str:
    row = connection.execute("SELECT id FROM ops_and_admin.server_node WHERE role = 'main'").fetchone()
    if row is None:
        raise RuntimeError("server registry has no main node")
    return row["id"]


def record_heartbeat(connection: Any, node: str, root: Path, units: list[str]) -> dict[str, Any]:
    metrics = store.host_metrics(root)
    report = {"metrics": metrics, "units": unit_states(units), "files": store.inventory(root)}
    connection.execute(
        "UPDATE ops_and_admin.server_node SET last_seen_at = transaction_timestamp(), agent_version = 'main-1',"
        " report = %(report)s::jsonb WHERE id = %(node)s", {"node": node, "report": json.dumps(report)})
    connection.execute("""
        INSERT INTO ops_and_admin.server_node_sample (node_id, disk_total_bytes, disk_free_bytes, store_bytes,
               memory_total_bytes, memory_available_bytes, load1)
        SELECT %(node)s, %(diskTotalBytes)s, %(diskFreeBytes)s, %(storeBytes)s, %(memoryTotalBytes)s,
               %(memoryAvailableBytes)s, %(load1)s
         WHERE NOT EXISTS (SELECT 1 FROM ops_and_admin.server_node_sample
                            WHERE node_id = %(node)s AND observed_at > now() - interval '4 minutes 30 seconds')""",
        {"node": node, **{key: metrics.get(key) for key in (
            "diskTotalBytes", "diskFreeBytes", "storeBytes", "memoryTotalBytes", "memoryAvailableBytes", "load1")}})
    connection.execute("DELETE FROM ops_and_admin.server_node_sample WHERE observed_at < now() - interval '14 days'")
    return metrics


def register_backups(connection: Any, node: str, root: Path, backup_dir: Path, cache_path: Path,
                     group: int | None) -> int:
    """Законченные дампы → резервные копии в хранилище основного сервера."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    known = {row["name"] for row in connection.execute(
        "SELECT name FROM ops_and_admin.storage_object WHERE kind = 'backup'").fetchall()}
    added = 0
    if not backup_dir.is_dir():
        return 0
    for dump in sorted(backup_dir.iterdir()):
        # dump-backup.sh пишет в .partial и переименовывает только проверенный
        # снимок, поэтому файл под окончательным именем уже закончен.
        if not DUMP.fullmatch(dump.name) or dump.name in known or not dump.is_file() or dump.is_symlink():
            continue
        stat = dump.stat()
        key = f"{dump.name}:{stat.st_size}:{int(stat.st_mtime)}"
        digest = cache.get(key) or store.sha256_file(dump)
        cache[key] = digest
        target = store.object_path(root, "backup", dump.name)
        if not target.exists():
            try:
                os.link(dump, target)
            except OSError as error:
                # Дампы на другом разделе: ссылку не сделать, нужна копия.
                if error.errno != errno.EXDEV:
                    raise
                partial = store.incoming_path(root, str(uuid.uuid4()))
                shutil.copyfile(dump, partial)
                store.publish(partial, target, "backup")
        os.chmod(target, 0o640)
        if group is not None:
            os.chown(target, -1, group)
        created = datetime.strptime(dump.name[8:24], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        row = connection.execute("""
            INSERT INTO ops_and_admin.storage_object (kind, name, size_bytes, sha256, origin_node, created_at)
            VALUES ('backup', %(name)s, %(size)s, %(sha)s, %(node)s, %(created)s)
            ON CONFLICT (name) DO NOTHING RETURNING id""",
            {"name": dump.name, "size": stat.st_size, "sha": digest, "node": node, "created": created}).fetchone()
        if row is not None:
            connection.execute("""
                INSERT INTO ops_and_admin.storage_replica (object_id, node_id, state, bytes_done, verified_at)
                VALUES (%(object)s, %(node)s, 'verified', %(size)s, transaction_timestamp())
                ON CONFLICT (object_id, node_id) DO NOTHING""",
                {"object": row["id"], "node": node, "size": stat.st_size})
            added += 1
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({key: value for key, value in cache.items()
                                      if key.split(":", 1)[0] in {p.name for p in backup_dir.iterdir()}}))
    return added


def check_local_copies(connection: Any, node: str, root: Path) -> int:
    """Подтверждённая копия, которой нет на диске, снова нужна."""
    lost = 0
    for row in connection.execute("""
            SELECT object.id::text, object.kind, object.name, object.size_bytes
              FROM ops_and_admin.storage_replica replica
              JOIN ops_and_admin.storage_object object ON object.id = replica.object_id
             WHERE replica.node_id = %(node)s AND replica.state = 'verified'""", {"node": node}).fetchall():
        path = store.object_path(root, row["kind"], row["name"])
        if not path.exists() or path.stat().st_size != row["size_bytes"]:
            connection.execute("""UPDATE ops_and_admin.storage_replica SET state = 'wanted', bytes_done = 0,
                                  error = 'lost_local_copy', updated_at = transaction_timestamp()
                                  WHERE object_id = %(id)s::uuid AND node_id = %(node)s""", {"id": row["id"], "node": node})
            lost += 1
    return lost


def retry_failed(connection: Any) -> None:
    connection.execute("""
        UPDATE ops_and_admin.storage_replica SET state = 'wanted', updated_at = transaction_timestamp()
         WHERE state = 'failed' AND attempts < %(max)s
           AND updated_at < now() - make_interval(secs => %(base)s * least(attempts, 30))""",
        {"max": RETRY_MAX_ATTEMPTS, "base": RETRY_BASE_SECONDS})


def apply_plan(connection: Any, node: str, root: Path, metrics: dict[str, Any]) -> reconcile.Plan:
    policy_row = connection.execute("SELECT value FROM ops_and_admin.runtime_policy WHERE name = 'storage'").fetchone()
    policy = policy_row["value"] if policy_row else {}
    nodes = []
    for row in connection.execute(NODES_SQL).fetchall():
        free = metrics.get("diskFreeBytes") if row["id"] == node else row["free_bytes"]
        nodes.append(reconcile.Node(row["id"], row["role"], row["state"], row["stores_objects"], free,
                                    row["reserve_bytes"]))
    objects = [reconcile.StoredObject(row["id"], row["kind"], row["size_bytes"], row["created_at"],
                                      row["retired_at"] is not None)
               for row in connection.execute(OBJECTS_SQL).fetchall()]
    replicas = {(row["object_id"], row["node_id"]): row["state"]
                for row in connection.execute(REPLICAS_SQL).fetchall()}
    result = reconcile.plan(nodes, objects, replicas, policy)
    meta = {row["id"]: row for row in connection.execute(OBJECTS_SQL).fetchall()}
    for object_id in result.retire:
        connection.execute("UPDATE ops_and_admin.storage_object SET retired_at = transaction_timestamp() "
                           "WHERE id = %(id)s::uuid AND retired_at IS NULL", {"id": object_id})
    for object_id, target in result.want:
        state = "wanted"
        # На основном файл может уже лежать (например, выгрузка архива).
        if target == node:
            row = meta[object_id]
            path = store.object_path(root, row["kind"], row["name"])
            if path.exists() and path.stat().st_size == row["size_bytes"] and store.sha256_file(path) == row["sha256"]:
                state = "verified"
        connection.execute("""
            INSERT INTO ops_and_admin.storage_replica (object_id, node_id, state, verified_at)
            VALUES (%(object)s::uuid, %(node)s, %(state)s,
                    CASE WHEN %(state)s = 'verified' THEN transaction_timestamp() END)
            ON CONFLICT (object_id, node_id) DO UPDATE
               SET state = excluded.state, bytes_done = 0, error = NULL, attempts = 0,
                   verified_at = excluded.verified_at, updated_at = transaction_timestamp()
             WHERE storage_replica.state IN ('deleted', 'failed')""",
            {"object": object_id, "node": target, "state": state})
    for object_id, target in result.delete:
        if target == node:
            row = meta[object_id]
            store.object_path(root, row["kind"], row["name"]).unlink(missing_ok=True)
            store.incoming_path(root, object_id).unlink(missing_ok=True)
            state = "deleted"
        else:
            state = "deleting"
        connection.execute("""UPDATE ops_and_admin.storage_replica SET state = %(state)s,
                              updated_at = transaction_timestamp() WHERE object_id = %(object)s::uuid
                              AND node_id = %(node)s AND state <> 'deleted'""",
                           {"object": object_id, "node": target, "state": state})
    if result.blocked:
        logger.info("storage placement waits for space blocked=%s", len(result.blocked))
    return result


def start_jobs(connection: Any, start: Any = None) -> list[str]:
    """Задания из панели запускают свои службы; службы сами берут очередь."""
    start = start or (lambda unit: subprocess.run(["systemctl", "start", "--no-block", unit], check=False))
    started = []
    for kind, unit in (("archive_now", "m-ranked-target-cold-archive.service"),
                       ("archive_analysis", "m-ranked-target-archive-analysis.service")):
        row = connection.execute("SELECT 1 FROM ops_and_admin.admin_job WHERE kind = %(kind)s AND state = 'queued' LIMIT 1",
                                 {"kind": kind}).fetchone()
        if row is not None:
            start(unit)
            started.append(unit)
    return started


def main() -> int:
    import psycopg
    from psycopg.rows import dict_row

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    root = Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT)))
    state_dir = Path(os.getenv("NODE_AGENT_STATE_DIR", "/var/lib/m-ranked/node-agent"))
    try:
        group = grp.getgrnam(os.getenv("MRANKED_STORE_GROUP", "m-ranked-storage")).gr_gid
    except KeyError:
        group = None
    store.ensure_layout(root, group)
    dsn = os.environ.get("MAINTENANCE_DATABASE_URL", "")
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=10) as connection:
        node = _main_id(connection)
        metrics = record_heartbeat(connection, node, root, os.getenv("NODE_AGENT_UNITS", "").split())
        added = register_backups(connection, node, root, Path(os.getenv("BACKUP_DIR", "/var/backups/m-ranked")),
                                 state_dir / "dump-sha256.json", group)
        lost = check_local_copies(connection, node, root)
        retry_failed(connection)
        with connection.transaction():
            # Один сверщик за раз, даже если запуск затянулся на следующую минуту.
            if connection.execute("SELECT pg_try_advisory_xact_lock(hashtext('storage-reconcile')) AS ok").fetchone()["ok"]:
                plan = apply_plan(connection, node, root, metrics)
            else:
                plan = reconcile.Plan()
        started = start_jobs(connection)
    logger.info("main agent backups_added=%s lost=%s want=%s delete=%s retire=%s blocked=%s started=%s",
                added, lost, len(plan.want), len(plan.delete), len(plan.retire), len(plan.blocked), started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
