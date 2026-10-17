from api.config import Settings
import pytest


def test_public_publication_window_defaults_to_100_days(monkeypatch) -> None:
    monkeypatch.delenv("PUBLICATION_RETENTION_DAYS", raising=False)

    assert Settings().retention_days == 100


def test_public_publication_window_follows_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PUBLICATION_RETENTION_DAYS", "70")

    assert Settings().retention_days == 70


@pytest.mark.parametrize("value", ["0", "3651"])
def test_public_publication_window_rejects_out_of_range_values(monkeypatch, value) -> None:
    monkeypatch.setenv("PUBLICATION_RETENTION_DAYS", value)

    with pytest.raises(ValueError, match="PUBLICATION_RETENTION_DAYS"):
        Settings()
