"""Сбой базы не должен ронять сборщик: перезапуск стоит замера."""
from __future__ import annotations

import psycopg
from psycopg_pool import PoolTimeout

from collector_target.__main__ import is_transient


def test_database_outages_are_waited_out_in_process() -> None:
    assert is_transient(psycopg.OperationalError(
        "FATAL: remaining connection slots are reserved for roles with the "
        "SUPERUSER attribute"
    ))
    assert is_transient(psycopg.InterfaceError("the connection is closed"))
    assert is_transient(PoolTimeout("couldn't get a connection after 30 sec"))
    assert is_transient(RuntimeError("GlobalPhaseLeaseLost"))
    assert is_transient(ConnectionResetError())


def test_defects_still_reach_systemd() -> None:
    assert not is_transient(ValueError("broken configuration"))
    assert not is_transient(RuntimeError("database schema contract mismatch"))
    assert not is_transient(psycopg.errors.UndefinedColumn("no such column"))
