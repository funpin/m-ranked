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


def test_storage_policy_keeps_two_archive_servers_and_analysis_before_archive() -> None:
    nodes = ["server-1", "server-2", "server-3"]
    fields = {"coldAfterDays": "45", "backupCopies": "2", "backup_server-2": "on",
              "archive_server-1": "on", "archive_server-2": "on"}
    value = admin.storage_policy(fields, nodes, {"browseCacheBytes": 7}, 30)
    assert value == {"coldAfterDays": 45, "backupCopies": 2, "browseCacheBytes": 7,
                     "backupNodes": ["server-2"], "archiveNodes": ["server-1", "server-2"]}
    one_archive = {key: item for key, item in fields.items() if key != "archive_server-1"}
    assert code(admin.storage_policy, one_archive, nodes, {}, None) == "policy-archive-nodes"
    no_backup = {key: item for key, item in fields.items() if key != "backup_server-2"}
    assert code(admin.storage_policy, no_backup, nodes, {}, None) == "policy-backup-nodes"
    assert code(admin.storage_policy, {**fields, "coldAfterDays": "29"}, nodes, {}, None) == "policy-cold-days"
    # Месяц уходит в архив, только когда все его посты прошли финальный анализ.
    assert code(admin.storage_policy, fields, nodes, {}, 60) == "policy-cold-before-analysis"


def test_analysis_policy_is_bounded_by_cold_archive_age() -> None:
    assert admin.analysis_policy({"finalAnalysisDays": ""}, 30) == {"finalAnalysisDays": None}
    assert admin.analysis_policy({"finalAnalysisDays": "21"}, 30) == {"finalAnalysisDays": 21}
    assert code(admin.analysis_policy, {"finalAnalysisDays": "31"}, 30) == "policy-cold-before-analysis"
    assert code(admin.analysis_policy, {"finalAnalysisDays": "1"}, 30) == "policy-analysis"


def test_job_month_and_storage_paths() -> None:
    assert admin.job_month({"month": "2026-08"}, required=True) == "2026-08"
    assert admin.job_month({}, required=False) is None
    assert code(admin.job_month, {"month": "2026-13"}, required=True) == "archive-month"
    assert code(admin.job_month, {}, required=True) == "archive-month"
    for path in ("/manage/servers", "/manage/servers/server-3", "/manage/policies/storage",
                 "/manage/archive/run", "/manage/archive/analysis"):
        assert admin.is_storage_path(path)
    for path in ("/manage/channels", "/manage/servers/a/b", "/manage/archive/drop"):
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


def test_archive_months_join_hot_partitions_and_generations() -> None:
    hot = [{"month": date(2026, 9, 1), "hot_bytes": 900}, {"month": date(2026, 8, 1), "hot_bytes": 8}]
    generations = [{"published_month": date(2026, 8, 1), "generation": 1, "state": "cold", "row_count": 10,
                    "publications": 2, "hot_bytes": 700, "error": None, "started_at": NOW, "finished_at": NOW,
                    "full_object_id": "f", "browse_object_id": "b"}]
    objects = {"f": {"name": "snapshots-2026-08-g1.parquet", "sizeBytes": 70, "replicas": []},
               "b": {"name": "browse-2026-08-g1.sqlite", "sizeBytes": 9, "replicas": []}}
    months = admin.archive_months(hot, generations, {date(2026, 9, 1): "archiving"}, objects, 30)
    assert [item["month"] for item in months] == ["2026-09", "2026-08"]
    assert months[0]["fence"] == "archiving" and months[0]["coldFrom"] == "2026-10-31"
    assert months[1]["generations"][0]["full"]["sizeBytes"] == 70
    assert months[1]["generations"][0]["browse"]["name"] == "browse-2026-08-g1.sqlite"


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


def test_storage_policy_command_updates_retention_threshold_together() -> None:
    connection = FakeConnection([
        ("name = %(name)s FOR UPDATE", [{"value": {"coldAfterDays": 30, "finalAnalysisDays": None}}]),
        ("SELECT id FROM ops_and_admin.server_node", [{"id": "server-1"}, {"id": "server-2"}]),
    ])
    fields = {"coldAfterDays": "60", "backupCopies": "1", "backup_server-2": "on",
              "archive_server-1": "on", "archive_server-2": "on"}
    location = asyncio.run(admin.execute(connection, "/manage/policies/storage", fields, "admin"))
    assert location == "/manage?tab=servers&storage_status=policy-storage"
    statements = [sql for sql, _ in connection.executed]
    assert any("retention_policy SET hot_days" in sql for sql in statements)
    assert any("UPDATE ops_and_admin.runtime_policy" in sql for sql in statements)


def test_command_errors_return_to_the_tab_with_a_code() -> None:
    connection = FakeConnection([])
    location = asyncio.run(admin.execute(connection, "/manage/servers", {"id": "x"}, "admin"))
    assert location == "/manage?tab=servers&storage_error=server-id"
    connection = FakeConnection([("FROM ops_and_admin.admin_job", [{"?column?": 1}])])
    location = asyncio.run(admin.execute(connection, "/manage/archive/run", {}, "admin"))
    assert location == "/manage?tab=servers&storage_error=job-busy"
