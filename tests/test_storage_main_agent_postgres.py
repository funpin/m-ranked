"""Агент основного сервера: резервные копии, размещение копий (ADR-016).

Нужна одноразовая база со схемой:

    MRANKED_TEST_STORAGE_MAINTENANCE_DSN=postgresql://maintenance:…@127.0.0.1:…/mranked
"""
from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from operations.storage import main_agent, store  # noqa: E402

MAINTENANCE = os.environ.get("MRANKED_TEST_STORAGE_MAINTENANCE_DSN", "")
pytestmark = pytest.mark.skipif(not MAINTENANCE, reason="disposable PostgreSQL DSN is required")


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def test_main_agent_registers_dumps_and_places_copies(tmp_path):
    root, dumps = tmp_path / "store", tmp_path / "dumps"
    store.ensure_layout(root)
    dumps.mkdir()
    name = f"mranked-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}Z.dump"
    (dumps / name).write_bytes(b"pg_dump custom format" * 1000)
    with connect(MAINTENANCE) as connection:
        metrics = main_agent.record_heartbeat(connection, "server-2", root, [])
        assert main_agent.register_backups(connection, "server-2", root, dumps, tmp_path / "sha.json", None) == 1
        assert main_agent.register_backups(connection, "server-2", root, dumps, tmp_path / "sha.json", None) == 0
        # Без второй копии — жёсткая ссылка на тот же файл.
        assert (root / "backups" / name).stat().st_ino == (dumps / name).stat().st_ino
        plan = main_agent.apply_plan(connection, "server-2", root, metrics)
        object_id = connection.execute("SELECT id::text FROM ops_and_admin.storage_object WHERE name = %s",
                                       (name,)).fetchone()["id"]
        assert (object_id, "server-1") in plan.want
        replica = connection.execute("SELECT state FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                     "AND node_id = 'server-1'", (object_id,)).fetchone()
        assert replica["state"] == "wanted"
        # Копия основного сервера пропала с диска — она снова нужна.
        (root / "backups" / name).unlink()
        assert main_agent.check_local_copies(connection, "server-2", root) >= 1
        lost = connection.execute("SELECT state, error FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                  "AND node_id = 'server-2'", (object_id,)).fetchone()
        assert lost == {"state": "wanted", "error": "lost_local_copy"}
        connection.execute("UPDATE ops_and_admin.storage_replica SET state = 'failed', attempts = 1, "
                           "updated_at = now() - interval '1 hour' WHERE node_id = 'server-1'")
        main_agent.retry_failed(connection)
        assert connection.execute("SELECT state FROM ops_and_admin.storage_replica WHERE object_id = %s::uuid "
                                  "AND node_id = 'server-1'", (object_id,)).fetchone()["state"] == "wanted"
