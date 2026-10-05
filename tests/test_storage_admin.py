from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from api import storage_admin as admin
from api.storage_admin import StorageCommandError

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def code(call, *args, **kwargs) -> str:
    with pytest.raises(StorageCommandError) as error:
        call(*args, **kwargs)
    return error.value.code


def test_new_server_requires_certificate_name_role_and_name() -> None:
    fields = {"id": "server-3", "display_name": "Сервер 3 · сбор", "role": "collector",
              "platform_vk": "on", "platform_max": "on", "stores_objects": "on", "reserve_gb": "3"}
    server = admin.new_server(fields)
    assert server == {"id": "server-3", "role": "collector", "state": "active", "display_name": "Сервер 3 · сбор",
                      "platforms": ["vk", "max"], "stores_objects": True, "reserve_bytes": 3 * 1024 ** 3}
    assert code(admin.new_server, {**fields, "id": "Server 3"}) == "server-id"
    assert code(admin.new_server, {**fields, "role": "main"}) == "server-role"
    assert code(admin.new_server, {**fields, "display_name": " "}) == "server-name"
    assert code(admin.new_server, {**fields, "state": "disabled"}) == "server-state"
    # Площадки собирает только сборщик: у сервера хранения их быть не может.
    assert code(admin.new_server, {**fields, "role": "storage"}) == "server-platforms"
    assert code(admin.new_server, {**fields, "reserve_gb": "-1"}) == "server-reserve"


def test_collection_policy_blank_means_environment_value() -> None:
    value = admin.collection_policy({"trackPostDays": "40", "pollIntervalMinutes": ""})
    assert value["trackPostDays"] == 40
    assert value["pollIntervalMinutes"] is None
    assert value["heartbeatMaxAgeDays"] is None
    assert code(admin.collection_policy, {"trackPostDays": "0"}) == "policy-collection"
    assert code(admin.collection_policy, {"pollIntervalMinutes": "5.5"}) == "policy-collection"


def test_storage_policy_keeps_retired_archive_fields_as_they_were() -> None:
    # Холодный архив выведен (0063): его поля остаются прежними и формой не меняются.
    nodes = ["server-1", "server-2", "server-3"]
    fields = {"coldAfterDays": "45", "backupCopies": "2", "backup_server-2": "on", "archive_server-3": "on"}
    current = {"browseCacheBytes": 7, "coldAfterDays": 30, "archiveNodes": ["server-1", "server-2"]}
    value = admin.storage_policy(fields, nodes, current)
    assert value == {"coldAfterDays": 30, "backupCopies": 2, "browseCacheBytes": 7,
                     "backupNodes": ["server-2"], "archiveNodes": ["server-1", "server-2"]}
    no_backup = {key: item for key, item in fields.items() if key != "backup_server-2"}
    assert code(admin.storage_policy, no_backup, nodes, current) == "policy-backup-nodes"

def test_analysis_policy_bounds() -> None:
    assert admin.analysis_policy({"finalAnalysisDays": ""}) == {"finalAnalysisDays": None}
    assert admin.analysis_policy({"finalAnalysisDays": "45"}) == {"finalAnalysisDays": 45}
    assert code(admin.analysis_policy, {"finalAnalysisDays": "1"}) == "policy-analysis"

def test_storage_paths() -> None:
    for path in ("/manage/servers", "/manage/servers/server-3", "/manage/policies/storage"):
        assert admin.is_storage_path(path)
    for path in ("/manage/channels", "/manage/servers/a/b", "/manage/archive/run", "/manage/archive/analysis"):
        assert not admin.is_storage_path(path)

def test_server_view_reports_disk_and_staleness() -> None:
    row = {"id": "server-1", "display_name": "Сервер 1", "role": "collector", "platforms": ["max", "telegram"],
           "state": "active", "stores_objects": True, "reserve_bytes": 3, "last_seen_at": NOW - timedelta(minutes=5),
           "agent_version": "1", "updated_at": NOW, "updated_by": None,
           "report": {"metrics": {"diskTotalBytes": 30, "diskFreeBytes": 6, "storeBytes": 1, "load1": 0.5,
                                  "memoryTotalBytes": True}, "units": {"collector@vk.service": "active"}}}
    totals = [{"node_id": "server-1", "state": "verified", "objects": 2, "bytes": 10},
              {"node_id": "server-2", "state": "verified", "objects": 5, "bytes": 50}]
    view = admin.server_view(row, totals, NOW)
    assert view["platforms"] == ["telegram", "max"]
    assert view["disk"]["totalBytes"] == 30 and view["disk"]["freeBytes"] == 6
    # Логическое значение — не число байт.
    assert view["memory"]["totalBytes"] is None
    assert view["online"] is False
    assert view["copies"] == {"verified": {"objects": 2, "bytes": 10}}



class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, answers):
        self.answers, self.executed = answers, []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        for marker, rows in self.answers:
            if marker in sql:
                return FakeCursor(rows)
        return FakeCursor([])


def test_storage_policy_command_saves_the_policy() -> None:
    connection = FakeConnection([
        ("name = %(name)s FOR UPDATE", [{"value": {"coldAfterDays": 30, "archiveNodes": ["server-1", "server-2"]}}]),
        ("SELECT id FROM ops_and_admin.server_node", [{"id": "server-1"}, {"id": "server-2"}]),
    ])
    fields = {"backupCopies": "1", "backup_server-2": "on"}
    location = asyncio.run(admin.execute(connection, "/manage/policies/storage", fields, "admin"))
    assert location == "/manage?tab=servers&storage_status=policy-storage"
    statements = [sql for sql, _ in connection.executed]
    assert not any("retention_policy" in sql for sql in statements)
    assert any("UPDATE ops_and_admin.runtime_policy" in sql for sql in statements)

def test_command_errors_return_to_the_tab_with_a_code() -> None:
    connection = FakeConnection([])
    location = asyncio.run(admin.execute(connection, "/manage/servers", {"id": "x"}, "admin"))
    assert location == "/manage?tab=servers&storage_error=server-id"
    location = asyncio.run(admin.execute(FakeConnection([]), "/manage/archive/run", {}, "admin"))
    assert location == "/manage?tab=servers&storage_error=unknown"
