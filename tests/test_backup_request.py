import json
from pathlib import Path

from api.backup_request import request_refresh


def test_request_is_written_once_and_kept_until_taken(tmp_path: Path) -> None:
    assert request_refresh("admin", "c-1", tmp_path) is True
    first = json.loads((tmp_path / "refresh").read_text())
    assert first["requestedBy"] == "admin" and first["correlationId"] == "c-1"
    # Повторное нажатие не перезаписывает ждущий запрос.
    assert request_refresh("other", "c-2", tmp_path) is True
    assert json.loads((tmp_path / "refresh").read_text())["correlationId"] == "c-1"
    assert not list(tmp_path.glob(".*.tmp"))


def test_missing_directory_reports_unavailable(tmp_path: Path) -> None:
    assert request_refresh("admin", "c-1", tmp_path / "absent") is False
