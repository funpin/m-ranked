from app.database import Database
from app.official_accounts import OFFICIAL_ACCOUNTS, sync_official_accounts


def test_curated_accounts_have_unique_platform_identity() -> None:
    identities: set[tuple[str, str]] = set()
    for accounts in OFFICIAL_ACCOUNTS.values():
        for account in accounts:
            identity = (account.platform, account.url.rstrip("/").split("/")[-1].casefold())
            assert identity not in identities
            identities.add(identity)
            assert account.url.startswith("https://")
            assert account.source_url.startswith("https://")


def test_sync_official_accounts_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("Московский авиационный институт", "МАИ")
    db.add_channel("MAIuniversity", institution_id=institution_id)

    first = sync_official_accounts(db)
    second = sync_official_accounts(db)

    accounts = db.list_platform_accounts(institution_id=institution_id)
    assert first["accounts"] == 3
    assert second["accounts"] == 3
    assert first["uncovered"] == []
    assert len(accounts) == 4  # Telegram plus VK, MAX and RUTUBE.
    assert {row["platform"] for row in accounts} == {"telegram", "vk", "max", "rutube"}
