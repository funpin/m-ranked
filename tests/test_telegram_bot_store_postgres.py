"""Схема Telegram-бота (миграция 0087) на одноразовом кластере; без DSN пропускается.

MRANKED_TEST_TELEGRAM_BOT_DSN — суперпользователь одноразовой базы с применёнными
миграциями (infra/compose.yaml). Контракт хранилища (tests/telegram_bot_store_contract.py)
идёт через PostgresStore, который работает под ролью telegram_bot, как в проде:
нехватка прав в SQL хранилища проявится ошибкой, а не пройдёт под суперпользователем.

Две переменные окружения:
- MRANKED_TEST_TELEGRAM_BOT_DSN — подключение; с ним одним идут только тесты схемы,
  они откатываются и ничего не меняют.
- MRANKED_TEST_TELEGRAM_BOT_DESTRUCTIVE=1 — разрешение тестам хранилища очищать (TRUNCATE)
  таблицы ops_and_admin.bot_*. Имя базы у одноразового кластера такое же, как у боевой,
  поэтому защита другая: тесты отказываются работать, если в catalog.institution есть
  строки (на только что созданном кластере их нет, в любой копии боевой базы — много).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from telegram_bot.store import PostgresStore
from tests.telegram_bot_store_contract import CASES

BOT_TABLES = ("bot_alert_mute", "bot_announced", "bot_held_alert", "bot_job",
              "bot_recipient", "bot_setting", "bot_week_snapshot")


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("MRANKED_TEST_TELEGRAM_BOT_DSN", "")
    if not value:
        pytest.skip("MRANKED_TEST_TELEGRAM_BOT_DSN is required")
    return value


@pytest.fixture(scope="module")
def destructive_dsn(dsn: str) -> str:
    if os.environ.get("MRANKED_TEST_TELEGRAM_BOT_DESTRUCTIVE") != "1":
        pytest.skip("MRANKED_TEST_TELEGRAM_BOT_DESTRUCTIVE=1 is required: the store tests TRUNCATE ops_and_admin.bot_*")
    with psycopg.connect(dsn) as connection:
        has_data = connection.execute("SELECT EXISTS (SELECT 1 FROM catalog.institution)").fetchone()[0]
    if has_data:
        pytest.fail("catalog.institution is not empty: this is not a freshly initialised disposable "
                    "cluster, refusing to TRUNCATE ops_and_admin.bot_*", pytrace=False)
    return dsn


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


# --- Контракт хранилища на PostgresStore -----------------------------------------

def _bot_dsn(dsn: str) -> str:
    return make_conninfo(dsn, options="-c role=telegram_bot")


def test_contract_session_runs_as_telegram_bot(dsn) -> None:
    with psycopg.connect(_bot_dsn(dsn)) as connection:
        assert connection.execute("SELECT current_user").fetchone()[0] == "telegram_bot"


async def _run(dsn: str, case) -> None:
    admin = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    seeded: list = []
    try:
        await admin.execute("TRUNCATE " + ", ".join(f"ops_and_admin.{name}" for name in BOT_TABLES))
        # Хранилище логинится сразу ролью telegram_bot (как в проде); здесь роль
        # выставляется параметром запуска сессии, пароль для неё не нужен.
        store = PostgresStore(_bot_dsn(dsn))

        async def seed_host_sample(observed_at, sample) -> None:
            await admin.execute(
                "INSERT INTO ops_and_admin.host_sample(observed_at, sample) VALUES (%s, %s)",
                (observed_at, Jsonb(sample)))
            seeded.append(observed_at)

        try:
            await case(SimpleNamespace(store=store, seed_host_sample=seed_host_sample))
        finally:
            await store.aclose()
    finally:
        if seeded:
            await admin.execute("DELETE FROM ops_and_admin.host_sample WHERE observed_at = ANY(%s)", (seeded,))
        await admin.execute("TRUNCATE " + ", ".join(f"ops_and_admin.{name}" for name in BOT_TABLES))
        await admin.close()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_postgres_store_contract(destructive_dsn, case) -> None:
    asyncio.run(_run(destructive_dsn, case))


def test_postgres_store_reconnects_once_after_connection_loss(destructive_dsn) -> None:
    dsn = destructive_dsn
    async def scenario() -> None:
        store = PostgresStore(_bot_dsn(dsn))
        try:
            await store.set_setting("reconnect_probe", 1, by=1)
            async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
                pid = store._conn.info.backend_pid
                await admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
                await asyncio.sleep(0.2)
                assert await store.get_setting("reconnect_probe") == 1
                assert store._conn.info.backend_pid != pid
                await admin.execute("DELETE FROM ops_and_admin.bot_setting WHERE key = 'reconnect_probe'")
        finally:
            await store.aclose()
    asyncio.run(scenario())


def _terminate(dsn: str, store: PostgresStore):
    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
            await admin.execute("SELECT pg_terminate_backend(%s)", (store._conn.info.backend_pid,))
        await asyncio.sleep(0.2)
    return run()


def test_non_idempotent_calls_raise_instead_of_retrying_after_connection_loss(destructive_dsn) -> None:
    async def scenario() -> None:
        dsn = destructive_dsn
        store = PostgresStore(_bot_dsn(dsn))
        try:
            await store.hold_alert({"kind": "spike"})
            await _terminate(dsn, store)
            with pytest.raises((psycopg.OperationalError, psycopg.InterfaceError)):
                await store.take_held()
            # Следующий вызов подключается заново, и задержанная тревога на месте.
            assert await store.take_held() == [{"kind": "spike"}]

            pid = "00000000-0000-0000-0000-000000000009"
            await store.get_setting("x")
            await _terminate(dsn, store)
            with pytest.raises((psycopg.OperationalError, psycopg.InterfaceError)):
                await store.mark_announced("spike", pid, 2)
            assert await store.mark_announced("spike", pid, 2) is True
        finally:
            await store.aclose()
    asyncio.run(scenario())


def test_cancelled_query_discards_the_shared_connection(destructive_dsn) -> None:
    async def scenario() -> None:
        store = PostgresStore(_bot_dsn(destructive_dsn))
        try:
            await store.get_setting("x")
            first_pid = store._conn.info.backend_pid
            task = asyncio.create_task(store._rows("SELECT pg_sleep(3)"))
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert store._conn is None
            assert await store.get_setting("x") is None
            assert store._conn.info.backend_pid != first_pid
        finally:
            await store.aclose()
    asyncio.run(scenario())


def _role_guard() -> str:
    from pathlib import Path
    migration = (Path(__file__).parents[1] / "db" / "migrations" / "0087_telegram_bot.sql").read_text(
        encoding="utf-8")
    start = migration.index("DO $$")
    return migration[start:migration.index("$$;", start) + 3]


def test_migration_role_guard_passes_with_role_and_raises_without(connection):
    guard = _role_guard()
    connection.execute(guard)  # роль создана init-скриптом: проходит молча
    missing = guard.replace("'telegram_bot'", "'telegram_bot_absent_for_test'")
    assert missing != guard
    with pytest.raises(psycopg.errors.RaiseException) as raised:
        connection.execute(missing)
    assert "operations/runbooks/DEPLOY.md" in str(raised.value)
