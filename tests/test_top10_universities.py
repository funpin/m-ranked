from app.database import Database
from app.m_rating import CHANNEL_TO_M_RATING_CODE
from app.top10_universities import TOP10_UNIVERSITIES, sync_top10_universities


def test_top10_manifest_is_complete_and_unique() -> None:
    assert len(TOP10_UNIVERSITIES) == 40
    assert len({university.m_rating_code for university in TOP10_UNIVERSITIES}) == 40
    assert len({university.name.casefold() for university in TOP10_UNIVERSITIES}) == 40

    identities: set[tuple[str, str]] = set()
    for university in TOP10_UNIVERSITIES:
        assert university.source_url.startswith("https://")
        assert {platform for platform, _ in university.accounts()} >= {"telegram", "vk"}
        for platform, url in university.accounts():
            assert platform in {"telegram", "vk", "max", "rutube"}
            assert url.startswith("https://")
            identity = (platform, url.rstrip("/").split("/")[-1].casefold())
            assert identity not in identities
            identities.add(identity)


def test_top10_telegram_accounts_map_to_m_rating_codes() -> None:
    for university in TOP10_UNIVERSITIES:
        username = university.telegram_url.rstrip("/").split("/")[-1].casefold()
        assert CHANNEL_TO_M_RATING_CODE[username] == university.m_rating_code


def test_sync_top10_universities_is_idempotent(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.migrate()

    first = sync_top10_universities(db)
    second = sync_top10_universities(db)

    expected_accounts = sum(len(university.accounts()) for university in TOP10_UNIVERSITIES)
    assert first == {"institutions": 40, "created": 40, "accounts": expected_accounts}
    assert second == {"institutions": 40, "created": 0, "accounts": expected_accounts}
    assert len(db.list_institutions()) == 40
    assert len(db.list_channels()) == 40
    assert len(db.list_platform_accounts()) == expected_accounts
    assert all(row["institution_id"] is not None for row in db.list_channels())
