import sys

import pytest

from migration.legacy_reference import (
    LegacyReferenceUnavailable,
    create_app,
    reference_metadata,
)


def test_reference_is_never_selected_implicitly(monkeypatch):
    monkeypatch.delenv("MRANKED_LEGACY_REFERENCE_ROOT", raising=False)
    with pytest.raises(LegacyReferenceUnavailable, match="separate trusted legacy checkout"):
        create_app()


def test_reference_imports_are_isolated_and_provenance_changes(tmp_path, monkeypatch):
    web = tmp_path / "app/web"
    web.mkdir(parents=True)
    (tmp_path / "app/value.py").write_text("VALUE = 'reference-only'\n")
    (web / "app.py").write_text(
        "from ..value import VALUE\ndef create_app():\n    return VALUE\n"
    )
    monkeypatch.setenv("MRANKED_LEGACY_REFERENCE_ROOT", str(tmp_path))
    before = reference_metadata()
    import app
    original_app = sys.modules["app"]
    assert create_app() == "reference-only"
    assert sys.modules["app"] is original_app
    assert "app.value" not in sys.modules
    assert reference_metadata() == before  # Generated pycache is not provenance.
    (web / "template.html").write_text("changed template")
    assert reference_metadata()["appTreeSha256"] != before["appTreeSha256"]


def test_invalid_reference_does_not_fall_back_to_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("MRANKED_LEGACY_REFERENCE_ROOT", str(tmp_path))
    with pytest.raises(LegacyReferenceUnavailable, match="separate legacy release"):
        create_app()
