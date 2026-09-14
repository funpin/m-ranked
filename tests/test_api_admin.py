from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from api.identity_receipts import persist_admin_envelope
from api.official_rating import _filled_months, _parse_month
from api.routes.admin import _account_body
from api.security import AuthConfig


def test_admin_identity_receipt_preserves_database_json(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "receipts"
    monkeypatch.setenv("MRANKED_IDENTITY_RECEIPT_DIR", str(root))
    original = '{"body": {"name": "Вуз"}, "action": "institution.create", "target": null, "expected": null}'
    digest = persist_admin_envelope(original)
    receipt = root / "admin" / f"{digest}.json"
    assert digest == hashlib.sha256(original.encode()).hexdigest()
    assert receipt.read_text(encoding="utf-8") == original
    assert os.stat(receipt).st_mode & 0o777 == 0o400
    assert persist_admin_envelope(original) == digest


def test_admin_auth_rejects_plaintext_or_unknown_roles(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([
        {"username": "admin", "passwordHash": "plaintext", "roles": ["ADMIN"]},
    ]))
    with pytest.raises(ValueError):
        AuthConfig.from_environment()
    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([
        {"username": "admin", "passwordHash": "$2b$04$invalid", "roles": ["ROOT"]},
    ]))
    with pytest.raises(ValueError):
        AuthConfig.from_environment()


def test_account_reference_normalization() -> None:
    institution = __import__("uuid").uuid4()
    telegram = _account_body("telegram", "https://t.me/Example_Channel/", None, None,
                             institution)
    assert telegram["externalKey"] == "example_channel"
    assert telegram["username"] == "Example_Channel"
    assert telegram["url"] == "https://t.me/Example_Channel"
    vk = _account_body("vk", "https://m.vk.com/public123?from=groups", " title ", None,
                       institution)
    assert vk["externalKey"] == "public123"
    assert vk["url"] == "https://vk.com/public123"
    with pytest.raises(Exception):
        _account_body("max", "file:///etc/passwd", None, None, institution)


def test_official_rating_parser_builds_all_five_rankings() -> None:
    source = json.dumps({"months": [{"name": "Июль", "items": [
        {"code": "a", "name": "А", "scores": {"social": 1, "tg": 4, "vk": 3,
                                                    "ok": 2, "rt": 1}},
        {"code": "b", "name": "Б", "scores": {"social": 2, "tg": 3, "vk": 2,
                                                    "ok": 1, "rt": 4}},
    ]}]}).encode()
    months = _filled_months(source)
    assert len(months) == 1
    parsed = _parse_month("const config = { year: 2026 };", months[0], source,
                          "https://www.m-rating.ru/data.json")
    assert parsed["period"] == "Июль 2026"
    assert set(parsed["rankings"]) == {"social", "telegram", "vk", "max", "rutube"}
    assert parsed["rankings"]["social"]["b"] == (1, 2.0)


def test_only_months_with_published_scores_are_taken() -> None:
    """Источник держит весь год одним файлом, у будущих месяцев оценки пустые.

    Прежде отсюда брался только последний заполненный месяц, поэтому в базе
    лежал ровно один период и сравнивать место в рейтинге было не с чем.
    """
    def month(name, score):
        return {"name": name, "items": [
            {"code": "a", "name": "А", "scores": {"social": score, "tg": score,
                                                  "vk": score, "ok": score, "rt": score}}]}
    source = json.dumps({"months": [
        month("Май", 5), month("Июнь", 6), month("Июль", 7),
        month("Август", None), month("Сентябрь", None)]}).encode()
    filled = _filled_months(source)
    assert [m["name"] for m in filled] == ["Май", "Июнь", "Июль"], "от старых к новым"

    periods = [_parse_month("const config = { year: 2026 };", m, source,
                            "https://www.m-rating.ru/data.json")["period"] for m in filled]
    assert periods == ["Май 2026", "Июнь 2026", "Июль 2026"]


def test_a_year_without_any_published_month_is_rejected() -> None:
    source = json.dumps({"months": [{"name": "Январь", "items": [
        {"code": "a", "name": "А", "scores": {"social": None, "tg": None,
                                              "vk": None, "ok": None, "rt": None}}]}]}).encode()
    with pytest.raises(ValueError):
        _filled_months(source)
