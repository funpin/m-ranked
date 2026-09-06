"""Receipt-bound reverse admission: unsupported configuration remains closed."""
from uuid import uuid4

import pytest

from operations.reverse_sync.postgres import PostgresReverseSource


def fixture_input():
    account = {"id": uuid4(), "institution_id": uuid4(), "platform": "max",
               "canonical_external_id": "immutable", "access_mode": "user_session", "enabled": True}
    original = {"action": "account.upsert", "target": None, "expected": 2,
                "body": {"institutionId": str(account["institution_id"]), "platform": "max",
                         "externalKey": "immutable", "username": "new_name", "title": "New title",
                         "url": "https://max.ru/new_name", "accessMode": "user_session"}}
    return account, original


@pytest.mark.parametrize("field,value", [("institutionId",str(uuid4())), ("platform","vk"),
    ("externalKey","replacement"), ("accessMode","official_api"), ("enabled",False),
    ("unexpected", "unsafe"), ("username", {"injected": True}), ("expected",True)])
def test_identity_input_rejects_administrative_or_unrecognized_change(field,value):
    account, original = fixture_input()
    if field == "enabled": account[field] = value
    elif field == "expected": original[field] = value
    else: original["body"][field] = value
    with pytest.raises(RuntimeError):
        PostgresReverseSource._validate_identity_input(original, account)


def test_identity_input_accepts_only_same_canonical_account_presentation():
    account, original = fixture_input()
    PostgresReverseSource._validate_identity_input(original, account)


@pytest.mark.parametrize("value", [None,"-20001","-20002"])
def test_native_receipt_accepts_explicit_clear_and_changes(value):
    account, _ = fixture_input()
    original = {"action":"account.native_id", "target":str(account["id"]),
                "expected":2,"body":{"nativeId":value}}
    PostgresReverseSource._validate_identity_input(original, account)
    original["target"] = str(uuid4())
    with pytest.raises(RuntimeError, match="target"):
        PostgresReverseSource._validate_identity_input(original, account)


@pytest.mark.parametrize("authoritative,expected", [(False,"200"),(True,None)])
def test_native_unknown_retains_but_original_admin_clear_removes(authoritative,expected,tmp_path):
    from migration.bridge.fixture import build_golden_fixture
    from migration.bridge.normalize import access_mode
    from operations.reverse_sync.sqlite_target import LegacySqliteTarget
    path=tmp_path/"legacy.sqlite"
    build_golden_fixture(path)
    target=LegacySqliteTarget(path,"receipt-unit",min_free_bytes=0)
    target.account_identity_baseline=target.capture_account_baseline()
    with target.connect(write=True) as connection:
        legacy=connection.execute("SELECT * FROM platform_accounts WHERE platform='max'").fetchone()
        institution=connection.execute("SELECT * FROM institutions WHERE id=?",(legacy["institution_id"],)).fetchone()
        account={"platform":"max","account_legacy_id":legacy["id"],"institution_legacy_id":legacy["institution_id"],
                 "canonical_external_id":str(legacy["native_id"] or legacy["external_key"]),
                 "institution_name":institution["name"],"institution_short_name":institution["short_name"],
                 "enabled":bool(legacy["enabled"]),"access_mode":access_mode("max",legacy["access_mode"]),
                 "native_external_id":None,"native_identity_authoritative":authoritative}
        target._apply_account(connection,account)
        target._verify_account(connection,account)
        assert connection.execute("SELECT native_id FROM platform_accounts WHERE id=?",(legacy["id"],)).fetchone()[0]==expected
