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
    update = AsyncMock()
    monkeypatch.setattr(official_rating, "_update_coverage", update)
    monkeypatch.setattr(official_rating, "_institution_codes", AsyncMock(return_value={"a": "1"}))
    importer = AsyncMock()
    monkeypatch.setattr(official_rating, "_import_month", importer)
    correlation = uuid.uuid4()
    asyncio.run(official_rating.refresh(request, "operator" if button else "schedule", correlation, update_coverage=button))
    importer.assert_not_awaited()
    if button:
        update.assert_awaited_once_with(database, parsed, "operator", correlation)
    else:
        update.assert_not_awaited()


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
