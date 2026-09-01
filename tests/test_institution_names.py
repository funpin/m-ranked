from app.database import Database
from app.institution_names import INSTITUTION_NAMES, sync_institution_names


def test_institution_names_cover_24_unique_universities() -> None:
    assert len(INSTITUTION_NAMES) == 24
    assert len({item.telegram_username.casefold() for item in INSTITUTION_NAMES}) == 24
    assert len({item.name.casefold() for item in INSTITUTION_NAMES}) == 24
    assert all(item.name[:1].isupper() for item in INSTITUTION_NAMES)
    assert all(item.short_name.strip() for item in INSTITUTION_NAMES)


def test_sync_institution_names_updates_linked_universities(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.migrate()
    institution_id = db.add_institution("Старое полное название", "Старое")
    db.add_channel("mephi_of", institution_id=institution_id)

    first = sync_institution_names(db)
    second = sync_institution_names(db)

    institution = db.institution(institution_id)
    assert institution is not None
    assert institution["name"] == "Национальный исследовательский ядерный университет «МИФИ»"
    assert institution["short_name"] == "НИЯУ МИФИ"
    assert first["updated"] == 1
    assert second["updated"] == 1
    assert len(first["missing"]) == 23
