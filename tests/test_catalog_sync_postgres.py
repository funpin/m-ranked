"""Правила переноса справочника Сервер 2 → Сервер 1 на настоящей базе (0082).

Обе стороны живут в одной базе и одной транзакции, которая в конце
откатывается. Состояние Сервера 2 строится настоящими командами каталога под
точкой сохранения, снимается catalog_sync_snapshot(), затем откат к точке
возвращает базу в состояние Сервера 1, и снимок применяется к ней.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from uuid import UUID, uuid4

import pytest


def _dsn() -> str:
    value = os.getenv("MRANKED_TEST_POSTGRES_ADMIN_DSN", "").strip()
    if not value:
        pytest.skip("MRANKED_TEST_POSTGRES_ADMIN_DSN is not configured")
    return value


@pytest.fixture
def db():
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    connection = psycopg.connect(_dsn(), row_factory=dict_row)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _command(db, action: str, body: dict, *, target=None, expected=None) -> dict:
    row = db.execute(
        "SELECT ops_and_admin.catalog_command(%s,%s,%s,%s::jsonb,'catalog-sync-test',%s) AS r",
        (action, target, expected, json.dumps(body), uuid4()),
    ).fetchone()
    assert row["r"]["outcome"] == "succeeded", row["r"]
    return row["r"]


def _institution(db, name: str) -> UUID:
    return UUID(_command(db, "institution.create", {"name": name})["targetId"])


def _account(db, institution: UUID, platform: str, username: str) -> dict:
    return _command(db, "account.upsert", {
        "institutionId": str(institution), "platform": platform,
        "externalKey": f"{platform}:{username}", "username": username,
        "url": f"https://example.org/{username}", "accessMode": "public_web",
    })


def _version(db, account: UUID) -> int:
    return db.execute("SELECT row_version FROM catalog.platform_account WHERE id=%s",
                      (account,)).fetchone()["row_version"]


def _server2(db, change) -> dict:
    """Сделать правку «на Сервере 2», снять снимок и забыть правку."""
    db.execute("SAVEPOINT server2")
    change()
    snapshot = db.execute("SELECT catalog.catalog_sync_snapshot() AS s").fetchone()["s"]
    db.execute("ROLLBACK TO SAVEPOINT server2")
    return snapshot


def _apply(db, snapshot: dict) -> dict:
    return db.execute("SELECT catalog.apply_catalog_sync(%s::jsonb) AS r",
                      (json.dumps(snapshot),)).fetchone()["r"]


def _history(db, account: UUID) -> list[dict]:
    return db.execute(
        """SELECT id, username, url, valid_from, valid_to, source_run_id
             FROM catalog.account_identity_history
            WHERE platform_account_id=%s ORDER BY valid_from""",
        (account,),
    ).fetchall()


def _quiet(result: dict) -> bool:
    return not any(result.values())


def test_admin_additions_reach_server1_with_the_same_ids(db) -> None:
    created: dict = {}

    def add() -> None:
        institution = _institution(db, f"Синхронизация {uuid4()}")
        telegram = _account(db, institution, "telegram", f"sync_{uuid4().hex[:12]}")
        maximum = _account(db, institution, "max", f"sync_{uuid4().hex[:12]}")
        account = UUID(maximum["targetId"])
        _command(db, "account.native_id", {"nativeId": "-1001234"},
                 target=account, expected=_version(db, account))
        db.execute(
            """INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from)
               VALUES (%s, 'm-rating', %s, transaction_timestamp())""",
            (institution, f"t{uuid4().hex[:8]}"),
        )
        created.update(
            institution=institution, telegram=UUID(telegram["targetId"]),
            telegram_legacy=telegram["legacyId"], max=account,
            history=_history(db, UUID(telegram["targetId"])),
        )

    snapshot = _server2(db, add)
    assert db.execute("SELECT 1 FROM catalog.platform_account WHERE id=%s",
                      (created["telegram"],)).fetchone() is None

    result = _apply(db, snapshot)
    assert result["institutionsInserted"] == 1
    assert result["accountsInserted"] == 2
    assert result["institutionExternalIdsInserted"] == 1
    assert result["externalIdentitiesInserted"] == 1
    assert result["accountConflicts"] == 0

    account = db.execute(
        """SELECT institution_id, enabled, current_username FROM catalog.platform_account WHERE id=%s""",
        (created["telegram"],),
    ).fetchone()
    assert account["institution_id"] == created["institution"] and account["enabled"]
    alias = db.execute(
        """SELECT legacy_id FROM catalog.legacy_entity_alias
            WHERE entity_type='platform_accounts' AND target_uuid=%s""",
        (created["telegram"],),
    ).fetchone()
    assert alias["legacy_id"] == created["telegram_legacy"]
    # История — с теми же значениями и временем, но со своим id: у баз разные
    # последовательности.
    history = _history(db, created["telegram"])
    assert [(row["username"], row["valid_from"], row["valid_to"]) for row in history] == [
        (row["username"], row["valid_from"], row["valid_to"]) for row in created["history"]
    ]
    assert history[0]["id"] != created["history"][0]["id"]
    native = db.execute(
        """SELECT external_id FROM catalog.account_external_identity
            WHERE platform_account_id=%s AND identity_namespace='max:native_id' AND valid_to IS NULL""",
        (created["max"],),
    ).fetchone()
    assert native["external_id"] == "-1001234"

    # Повтор того же снимка ничего не пишет.
    assert _quiet(_apply(db, snapshot))


def test_disable_delete_and_move_follow_server2(db) -> None:
    first = _institution(db, f"Первый {uuid4()}")
    second = _institution(db, f"Второй {uuid4()}")
    one = UUID(_account(db, first, "vk", f"one_{uuid4().hex[:10]}")["targetId"])
    two = UUID(_account(db, first, "vk", f"two_{uuid4().hex[:10]}")["targetId"])
    username = db.execute("SELECT current_username FROM catalog.platform_account WHERE id=%s",
                          (two,)).fetchone()["current_username"]

    def change() -> None:
        _command(db, "account.disable", {}, target=one, expected=_version(db, one))
        _command(db, "account.upsert", {
            "institutionId": str(second), "platform": "vk", "externalKey": f"vk:{username}",
            "username": username, "accessMode": "official_api",
        })

    snapshot = _server2(db, change)
    history_before = _history(db, two)
    result = _apply(db, snapshot)
    assert result["accountsUpdated"] == 2
    rows = {row["id"]: row for row in db.execute(
        "SELECT id, enabled, institution_id, access_mode::text AS mode FROM catalog.platform_account WHERE id = ANY(%s)",
        ([one, two],),
    ).fetchall()}
    assert rows[one]["enabled"] is False
    assert rows[two]["institution_id"] == second and rows[two]["mode"] == "official_api"
    # Переезд не меняет видимую идентичность — новой версии нет.
    assert _history(db, two) == history_before
    assert _quiet(_apply(db, snapshot))

    def delete() -> None:
        _command(db, "account.delete", {}, target=two, expected=_version(db, two))

    _apply(db, _server2(db, delete))
    deleted = db.execute("SELECT enabled, deleted_at FROM catalog.platform_account WHERE id=%s",
                         (two,)).fetchone()
    assert deleted["enabled"] is False and deleted["deleted_at"] is not None


def test_admin_rename_reaches_server1_when_it_is_newer(db) -> None:
    institution = _institution(db, f"Переименование {uuid4()}")
    old = f"old_{uuid4().hex[:10]}"
    account = UUID(_account(db, institution, "telegram", old)["targetId"])
    new = f"new_{uuid4().hex[:10]}"

    snapshot = _server2(db, lambda: _command(db, "account.upsert", {
        "institutionId": str(institution), "platform": "telegram", "externalKey": f"telegram:{old}",
        "username": new, "url": f"https://t.me/{new}", "accessMode": "public_web",
    }))
    result = _apply(db, snapshot)
    assert result["identityVersionsInserted"] == 1
    current = db.execute("SELECT current_username, current_url FROM catalog.platform_account WHERE id=%s",
                         (account,)).fetchone()
    assert current == {"current_username": new, "current_url": f"https://t.me/{new}"}
    history = _history(db, account)
    assert [row["username"] for row in history] == [old, new]
    assert history[0]["valid_to"] == history[1]["valid_from"] and history[1]["valid_to"] is None
    assert _quiet(_apply(db, snapshot))


def test_collector_observation_newer_than_the_admin_edit_is_kept(db) -> None:
    institution = _institution(db, f"Сборщик {uuid4()}")
    old = f"old_{uuid4().hex[:10]}"
    account = UUID(_account(db, institution, "telegram", old)["targetId"])
    snapshot = _server2(db, lambda: _command(db, "account.upsert", {
        "institutionId": str(institution), "platform": "telegram", "externalKey": f"telegram:{old}",
        "username": f"admin_{uuid4().hex[:8]}", "accessMode": "public_web",
    }))
    admin_from = max(datetime.fromisoformat(row["valid_from"]) for row in snapshot["identityHistory"]
                     if row["platform_account_id"] == str(account))

    # Сервер 1 тем временем увидел аккаунт сам, позже правки.
    observed = f"seen_{uuid4().hex[:8]}"
    seen_at = admin_from + timedelta(minutes=5)
    db.execute("UPDATE catalog.account_identity_history SET valid_to=%s WHERE platform_account_id=%s AND valid_to IS NULL",
               (seen_at, account))
    db.execute("""INSERT INTO catalog.account_identity_history(platform_account_id, username, valid_from)
                  VALUES (%s, %s, %s)""", (account, observed, seen_at))
    db.execute("UPDATE catalog.platform_account SET current_username=%s WHERE id=%s", (observed, account))

    result = _apply(db, snapshot)
    assert result["identityVersionsInserted"] == 0
    assert db.execute("SELECT current_username FROM catalog.platform_account WHERE id=%s",
                      (account,)).fetchone()["current_username"] == observed
    assert [row["username"] for row in _history(db, account)] == [old, observed]


def test_a_chain_of_admin_versions_lands_in_order_for_a_new_account(db) -> None:
    names = [f"v{index}_{uuid4().hex[:8]}" for index in range(3)]
    created: dict = {}

    def add() -> None:
        institution = _institution(db, f"Цепочка {uuid4()}")
        created["account"] = UUID(_account(db, institution, "rutube", names[0])["targetId"])
        for name in names[1:]:
            _command(db, "account.upsert", {
                "institutionId": str(institution), "platform": "rutube",
                "externalKey": f"rutube:{names[0]}", "username": name, "accessMode": "public_web",
            })

    _apply(db, _server2(db, add))
    history = _history(db, created["account"])
    assert [row["username"] for row in history] == names
    assert [row["valid_to"] for row in history[:-1]] == [row["valid_from"] for row in history[1:]]
    assert history[-1]["valid_to"] is None
    assert db.execute("SELECT current_username FROM catalog.platform_account WHERE id=%s",
                      (created["account"],)).fetchone()["current_username"] == names[-1]


def test_institution_codes_mirror_server2_including_reopen_and_removal(db) -> None:
    institution = _institution(db, f"Коды {uuid4()}")
    code = f"c{uuid4().hex[:8]}"
    kept = db.execute(
        """INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from)
           VALUES (%s, 'test-sync', %s, transaction_timestamp() - interval '1 day') RETURNING id""",
        (institution, code),
    ).fetchone()["id"]
    stray = db.execute(
        """INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from)
           VALUES (%s, 'test-sync', %s, transaction_timestamp()) RETURNING id""",
        (institution, f"s{uuid4().hex[:8]}"),
    ).fetchone()["id"]
    reopened: dict = {}

    def change() -> None:
        db.execute("DELETE FROM catalog.institution_external_id WHERE id=%s", (stray,))
        db.execute("UPDATE catalog.institution_external_id SET valid_to=transaction_timestamp() WHERE id=%s",
                   (kept,))
        reopened["id"] = db.execute(
            """INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from)
               VALUES (%s, 'test-sync', %s, transaction_timestamp() + interval '1 second') RETURNING id""",
            (institution, code),
        ).fetchone()["id"]

    result = _apply(db, _server2(db, change))
    assert result["institutionExternalIdsDeleted"] >= 1
    rows = {row["id"]: row for row in db.execute(
        "SELECT id, valid_to FROM catalog.institution_external_id WHERE institution_id=%s", (institution,),
    ).fetchall()}
    assert set(rows) == {kept, reopened["id"]}
    assert rows[kept]["valid_to"] is not None and rows[reopened["id"]]["valid_to"] is None


def test_an_account_colliding_with_another_id_is_counted_not_fatal(db) -> None:
    institution = _institution(db, f"Конфликт {uuid4()}")
    username = f"dup_{uuid4().hex[:10]}"
    created: dict = {}

    def add() -> None:
        created["id"] = UUID(_account(db, institution, "vk", username)["targetId"])

    snapshot = _server2(db, add)
    db.execute(
        """INSERT INTO catalog.platform_account(institution_id, platform, canonical_external_id, access_mode)
           VALUES (%s, 'vk', %s, 'public_web')""",
        (institution, f"vk:{username}"),
    )
    result = _apply(db, snapshot)
    assert result["accountConflicts"] == 1
    assert db.execute("SELECT 1 FROM catalog.platform_account WHERE id=%s", (created["id"],)).fetchone() is None


def test_bad_snapshots_are_refused_before_any_write(db) -> None:
    psycopg = pytest.importorskip("psycopg")
    snapshot = db.execute("SELECT catalog.catalog_sync_snapshot() AS s").fetchone()["s"]
    for broken in (
        {**snapshot, "version": 2},
        {key: value for key, value in snapshot.items() if key != "aliases"},
        {**snapshot, "accounts": []},
    ):
        db.execute("SAVEPOINT broken")
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            _apply(db, broken)
        db.execute("ROLLBACK TO SAVEPOINT broken")


def test_only_the_two_transport_roles_may_call_the_functions(db) -> None:
    rows = db.execute(
        """SELECT role, has_function_privilege(role, 'catalog.apply_catalog_sync(jsonb)', 'EXECUTE') AS apply,
                  has_function_privilege(role, 'catalog.catalog_sync_snapshot()', 'EXECUTE') AS export
             FROM unnest(ARRAY['outbox_worker','collector_ingest','api_read','api_write_admin']) role""",
    ).fetchall()
    assert {row["role"]: (row["apply"], row["export"]) for row in rows} == {
        "outbox_worker": (True, False),
        "collector_ingest": (False, True),
        "api_read": (False, False),
        "api_write_admin": (False, False),
    }


def test_apply_waits_for_the_collectors_account_lock_instead_of_racing_it(db) -> None:
    psycopg = pytest.importorskip("psycopg")
    created: dict = {}

    def add() -> None:
        institution = _institution(db, f"Замок {uuid4()}")
        created["id"] = _account(db, institution, "telegram", f"lock_{uuid4().hex[:10]}")["targetId"]

    snapshot = _server2(db, add)
    collector = psycopg.connect(_dsn(), autocommit=True)
    try:
        collector.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                          (f"account-identity:{created['id']}",))
        with pytest.raises(psycopg.errors.LockNotAvailable):
            _apply(db, snapshot)
    finally:
        collector.close()
