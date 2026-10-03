"""Решение о размещении копий: чистые функции без базы и файлов.

Правила (ADR-016):

* Резервные копии лежат на серверах из backupNodes, полные файлы архива — на
  archiveNodes, просмотровые файлы архива — ещё и на основном сервере всегда:
  без них архивный пост не открыть быстро.
* Хранятся последние backupCopies резервных копий; более старые выводятся из
  оборота, только когда у каждой из новых есть подтверждённая копия.
* Лишняя копия удаляется, лишь когда все нужные копии объекта подтверждены по
  SHA-256. Пока это не так, она остаётся — объект не может потерять последнюю
  проверенную копию ни при какой смене политики.
* Если ни у одного нужного сервера копии нет, а основной не хранит объект, он
  получает временную копию-перевалку: все передачи идут через основной сервер.
* Сервер получает новую копию, только если после неё на диске останется его
  запас (reserve_bytes); иначе копия ждёт и панель показывает нехватку места.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Sequence

ONLINE_ACTIVE = frozenset({"active"})
LIVE_REPLICA = frozenset({"wanted", "transferring", "verified"})


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    role: str
    state: str
    stores_objects: bool
    free_bytes: int | None
    reserve_bytes: int


@dataclass(frozen=True, slots=True)
class StoredObject:
    id: str
    kind: str
    size_bytes: int
    created_at: datetime
    retired: bool = False


@dataclass(slots=True)
class Plan:
    want: list[tuple[str, str]] = field(default_factory=list)
    delete: list[tuple[str, str]] = field(default_factory=list)
    retire: list[str] = field(default_factory=list)
    blocked: list[tuple[str, str, str]] = field(default_factory=list)


def targets(kind: str, policy: Mapping[str, object], nodes: Mapping[str, Node]) -> list[str]:
    wanted = list(policy.get("backupNodes" if kind == "backup" else "archiveNodes") or [])  # type: ignore[arg-type]
    if kind == "archive_browse":
        wanted += [node.id for node in nodes.values() if node.role == "main"]
    result: list[str] = []
    for node_id in wanted:
        node = nodes.get(node_id)
        if node and node.state in ONLINE_ACTIVE and node.stores_objects and node_id not in result:
            result.append(node_id)
    return result


def plan(nodes: Sequence[Node], objects: Sequence[StoredObject],
         replicas: Mapping[tuple[str, str], str], policy: Mapping[str, object]) -> Plan:
    by_id = {node.id: node for node in nodes}
    main = next((node.id for node in nodes if node.role == "main"), None)
    result = Plan()
    # Место, которое уже обещано копиям в пути, не считается свободным дважды.
    committed: dict[str, int] = {node.id: 0 for node in nodes}
    sizes = {item.id: item.size_bytes for item in objects}
    for (object_id, node_id), state in replicas.items():
        if state in {"wanted", "transferring"} and node_id in committed:
            committed[node_id] += sizes.get(object_id, 0)

    backups = sorted((item for item in objects if item.kind == "backup" and not item.retired),
                     key=lambda item: item.created_at, reverse=True)
    keep = max(1, int(policy.get("backupCopies") or 1))  # type: ignore[arg-type]
    newest = backups[:keep]
    if all(any(replicas.get((item.id, node)) == "verified" for node in by_id) for item in newest):
        result.retire.extend(item.id for item in backups[keep:])
    retiring = set(result.retire)

    for item in objects:
        holders = {node for (object_id, node), state in replicas.items()
                   if object_id == item.id and state == "verified"}
        live = {node for (object_id, node), state in replicas.items()
                if object_id == item.id and state in LIVE_REPLICA}
        if item.retired or item.id in retiring:
            # Выведенный объект удаляется везде, кроме недоступных серверов.
            for node in sorted(live):
                if by_id.get(node) and by_id[node].state != "disabled":
                    result.delete.append((item.id, node))
            continue
        wanted = targets(item.kind, policy, by_id)
        for node in wanted:
            if node in live:
                continue
            spec = by_id[node]
            if spec.free_bytes is not None and spec.free_bytes - committed[node] - item.size_bytes < spec.reserve_bytes:
                result.blocked.append((item.id, node, "no_space"))
                continue
            committed[node] += item.size_bytes
            result.want.append((item.id, node))
            live.add(node)
        # Перевалка: копировать между серверами можно только через основной.
        if main and main not in live and any(node not in holders for node in wanted) and holders:
            result.want.append((item.id, main))
            live.add(main)
        complete = bool(wanted) and all(node in holders for node in wanted)
        if complete:
            for node in sorted(holders - set(wanted)):
                if by_id.get(node) and by_id[node].state != "disabled":
                    result.delete.append((item.id, node))
            for node in sorted((live - holders) - set(wanted)):
                result.delete.append((item.id, node))
    return result


def validate_storage_policy(value: Mapping[str, object], node_ids: Iterable[str]) -> dict[str, object]:
    known = set(node_ids)
    unknown = set(value) - {"coldAfterDays", "backupCopies", "backupNodes", "archiveNodes", "browseCacheBytes"}
    if unknown:
        raise ValueError(f"unknown storage policy keys: {sorted(unknown)}")
    cold = value.get("coldAfterDays")
    if isinstance(cold, bool) or not isinstance(cold, int) or not 30 <= cold <= 3650:
        raise ValueError("coldAfterDays must be an integer in [30; 3650]")
    copies = value.get("backupCopies")
    if isinstance(copies, bool) or not isinstance(copies, int) or not 1 <= copies <= 14:
        raise ValueError("backupCopies must be an integer in [1; 14]")
    result: dict[str, object] = {"coldAfterDays": cold, "backupCopies": copies,
                                 "browseCacheBytes": value.get("browseCacheBytes", 2 * 1024 ** 3)}
    for key, minimum in (("backupNodes", 1), ("archiveNodes", 2)):
        nodes = value.get(key)
        if not isinstance(nodes, list) or not all(isinstance(item, str) for item in nodes):
            raise ValueError(f"{key} must be a list of server ids")
        cleaned = list(dict.fromkeys(nodes))
        if set(cleaned) - known:
            raise ValueError(f"{key} names unknown servers")
        # Полный архив после удаления партиции — единственная полная копия
        # месяца, поэтому серверов для него не меньше двух.
        if len(cleaned) < minimum:
            raise ValueError(f"{key} needs at least {minimum} server(s)")
        result[key] = cleaned
    return result
