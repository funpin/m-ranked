"""Схема Telegram-бота (миграция 0087) на одноразовом кластере; без DSN пропускается.

MRANKED_TEST_TELEGRAM_BOT_DSN — суперпользователь одноразовой базы с применёнными
миграциями (infra/compose.yaml). Контрактные тесты хранилища бота добавляет Task 9.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

BOT_TABLES = ("bot_alert_mute", "bot_announced", "bot_held_alert", "bot_job",
              "bot_recipient", "bot_setting", "bot_week_snapshot")


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("MRANKED_TEST_TELEGRAM_BOT_DSN", "")
    if not value:
        pytest.skip("MRANKED_TEST_TELEGRAM_BOT_DSN is required")
    return value


@pytest.fixture
def connection(dsn):
    # Каждый тест живёт в транзакции и откатывается: база остаётся пустой.
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def _recipient(connection, chat_id: int, kind: str, *, alerts: bool, is_admin: bool = False) -> None:
    connection.execute(
        "INSERT INTO ops_and_admin.bot_recipient(chat_id, kind, title, is_admin, alerts) "
        "VALUES (%s, %s, 'x', %s, %s)", (chat_id, kind, is_admin, alerts))


def test_chat_cannot_receive_alerts(connection):
    _recipient(connection, 1, "person", alerts=True)
    connection.execute("SAVEPOINT chat")
    with pytest.raises(psycopg.errors.CheckViolation):
        _recipient(connection, -2, "chat", alerts=True)
    connection.execute("ROLLBACK TO SAVEPOINT chat")
    with pytest.raises(psycopg.errors.CheckViolation):
        _recipient(connection, -3, "chat", alerts=False, is_admin=True)


def test_recipient_kind_is_person_or_chat(connection):
    with pytest.raises(psycopg.errors.CheckViolation):
        _recipient(connection, 4, "channel", alerts=False)


def test_telegram_bot_role_is_nologin_with_exact_grants(connection):
    role = connection.execute(
        "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'telegram_bot'"
    ).fetchone()
    assert role == {"rolcanlogin": False, "rolsuper": False, "rolcreaterole": False, "rolcreatedb": False}
    tables = {(row["table_schema"], row["table_name"]): set()
              for row in connection.execute(
                  "SELECT table_schema, table_name FROM information_schema.role_table_grants "
                  "WHERE grantee = 'telegram_bot'")}
    for row in connection.execute(
            "SELECT table_schema, table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'telegram_bot'"):
        tables[(row["table_schema"], row["table_name"])].add(row["privilege_type"])
    crud = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    expected = {("ops_and_admin", name): crud for name in BOT_TABLES}
    expected[("ops_and_admin", "host_sample")] = {"SELECT"}
    assert tables == expected
    sequences = [row["relname"] for row in connection.execute(
        "SELECT relname FROM (SELECT c.oid, c.relname FROM pg_class c WHERE c.relkind = 'S' OFFSET 0) s "
        "WHERE has_sequence_privilege('telegram_bot', s.oid, 'USAGE')")]
    assert sequences == ["bot_held_alert_id_seq"]
    assert connection.execute("SELECT count(*) AS n FROM information_schema.routine_privileges "
                              "WHERE grantee = 'telegram_bot'").fetchone()["n"] == 0


def test_telegram_bot_can_work_with_its_tables_and_nothing_else(connection):
    assert connection.execute(
        "SELECT has_schema_privilege('telegram_bot', 'ops_and_admin', 'USAGE') AS ok").fetchone()["ok"]
    connection.execute("SET LOCAL ROLE telegram_bot")
    connection.execute("SELECT count(*) FROM ops_and_admin.bot_setting")
    connection.execute("SELECT count(*) FROM ops_and_admin.host_sample")
    connection.execute("INSERT INTO ops_and_admin.bot_held_alert(event) VALUES ('{}'::jsonb)")
    connection.execute("DELETE FROM ops_and_admin.bot_held_alert")
    connection.execute("SAVEPOINT denied")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("SELECT 1 FROM catalog.institution LIMIT 1")
    connection.execute("ROLLBACK TO SAVEPOINT denied")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("INSERT INTO ops_and_admin.host_sample(sample) VALUES ('{}'::jsonb)")
