import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from api import official_rating


@pytest.mark.parametrize("button", [False, True])
def test_only_admin_button_refreshes_coverage_even_when_the_month_is_known(monkeypatch, button):
    parsed = {"period": "Сентябрь 2026", "evidence": {"items": []}, "rankings": {"social": {str(i): (i, 1.0) for i in range(233)}}}
    database = SimpleNamespace(admin_fetch_one=AsyncMock(return_value=None),
                               admin_fetch_all=AsyncMock(return_value=[{"period": parsed["period"],
                                                                         "institution_id": "a"}]))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=database)))
    monkeypatch.setattr(official_rating, "_fetch", AsyncMock(side_effect=[
        (b'year: 2026, ratingsJson: "ratings.json"', "https://m-rating.ru/js/config.js"),
        (b'{}', "https://m-rating.ru/ratings.json")]))
    monkeypatch.setattr(official_rating, "_filled_months", lambda _: [{}])
    monkeypatch.setattr(official_rating, "_parse_month", lambda *_: parsed)
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(official_rating, "_update_coverage", update)
    monkeypatch.setattr(official_rating, "_institution_codes", AsyncMock(return_value={"a": "1"}))
    importer = AsyncMock()
    monkeypatch.setattr(official_rating, "_import_month", importer)
    correlation = uuid.uuid4()
    recounted = asyncio.run(official_rating.refresh(request, "operator", correlation, update_coverage=button))
    importer.assert_not_awaited()
    if button:
        update.assert_awaited_once_with(database, parsed, "operator", correlation)
        assert recounted is True
    else:
        update.assert_not_awaited()
        assert recounted is None


def test_no_scheduled_m_rating_job_remains():
    """М-Рейтинг обновляется только вручную: ночного задания в релизе нет."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert not list((root / "operations" / "systemd").glob("*official-rating*"))
    assert not (root / "api" / "tools" / "refresh_official_rating.py").exists()


class _Cursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class _Connection:
    """Записывает запросы снимка покрытия; checkpoint «свежий» или нет."""

    def __init__(self, recent: bool, rated: int):
        self.recent, self.rated, self.statements = recent, rated, []

    def transaction(self):
        return _Context(self)

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if "operational_checkpoint" in statement and statement.lstrip().startswith("SELECT"):
            return _Cursor({"?column?": 1} if self.recent else None)
        if "rated_institutions" in statement:
            return _Cursor({"rated_institutions": self.rated})
        return _Cursor(None)


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return False


@pytest.mark.parametrize("recent", [False, True])
def test_coverage_snapshot_is_taken_at_most_every_two_weeks(recent):
    import json
    from datetime import datetime, timezone
    connection = _Connection(recent, rated=100)
    database = SimpleNamespace(admin=lambda: _Context(connection))
    parsed = {"period": "Сентябрь 2026", "sourceUrl": "https://www.m-rating.ru/data/r.json",
              "fetchedAt": datetime(2026, 10, 16, tzinfo=timezone.utc),
              "rankings": {"social": {str(i): (i, 1.0) for i in range(233)}}}
    recounted = asyncio.run(official_rating._update_coverage(database, parsed, "operator", uuid.uuid4()))
    writes = [params for statement, params in connection.statements if "INSERT" in statement]
    if recent:
        assert recounted is False and writes == []
    else:
        assert recounted is True
        assert json.loads(writes[0]["value"]) | {} == {
            "institutions": 233, "ratedInstitutions": 100, "period": "Сентябрь 2026",
            "sourceUrl": "https://www.m-rating.ru/data/r.json", "updatedAt": "2026-10-16T00:00:00+00:00"}
        guard = connection.statements[1]
        assert guard[1] == {"days": 14} and "ratedInstitutions" in guard[0]


def test_failed_source_does_not_replace_the_reference_count(monkeypatch):
    database = SimpleNamespace(admin_fetch_one=AsyncMock(return_value=None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=database)))
    monkeypatch.setattr(official_rating, "_fetch", AsyncMock(side_effect=ValueError("unavailable")))
    update = AsyncMock()
    monkeypatch.setattr(official_rating, "_update_coverage", update)
    failure = AsyncMock()
    monkeypatch.setattr(official_rating, "_report_failure", failure)
    with pytest.raises(ValueError):
        asyncio.run(official_rating.refresh(request, "operator", uuid.uuid4(), update_coverage=True))
    update.assert_not_awaited()
    failure.assert_awaited_once()


def test_evidence_keeps_the_consolidated_score():
    import json
    source = json.dumps({"months": [{"name": "Сентябрь", "items": [
        {"code": "37", "name": "Вуз", "scores": {"consolidated": 22.0, "social": 46.9, "vk": 56.7,
                                                "tg": None, "ok": 60.4, "rt": 19.2}}]}]}).encode()
    month = official_rating._filled_months(source)[0]
    parsed = official_rating._parse_month("year: 2026", month, source, "https://www.m-rating.ru/data/r.json")
    assert parsed["evidence"]["items"][0]["scores"] == {"consolidated": 22.0, "social": 46.9, "vk": 56.7,
                                                         "ok": 60.4, "rt": 19.2}
    # Сводный балл — справка, в места категорий он не входит.
    assert set(parsed["rankings"]) == {"social", "telegram", "vk", "max", "rutube"}
