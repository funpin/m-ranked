from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from api.identity_receipts import persist_admin_envelope
from api.official_rating import _filled_months, _parse_month
from api.routes import admin
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


def test_project_size_does_not_break_status_after_release_directory_is_removed(
        monkeypatch) -> None:
    class MissingWorkingDirectory:
        @staticmethod
        def cwd() -> Path:
            raise FileNotFoundError("release was removed")

    monkeypatch.setattr(admin, "Path", MissingWorkingDirectory)
    monkeypatch.setattr(admin, "_PROJECT_SIZE", (0.0, None))
    assert admin._project_bytes() is None


SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
# Политика требует единой стоимости bcrypt, поэтому заглушка тоже в десять раундов.
HASH = "$2b$10$" + "a"*53
CSRF_SECRET = "0123456789abcdef0123456789abcdef"


def test_admin_auth_rejects_plaintext_or_unknown_roles(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_REQUIRE_MFA", "false")
    monkeypatch.setenv("ADMIN_CSRF_SECRET", CSRF_SECRET)
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


def test_admin_auth_requires_a_second_factor_by_default(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_CSRF_SECRET", CSRF_SECRET)
    without_secret = json.dumps([
        {"username": "admin", "passwordHash": HASH, "roles": ["ADMIN"]},
    ])
    monkeypatch.delenv("ADMIN_REQUIRE_MFA", raising=False)
    monkeypatch.setenv("ADMIN_AUTH_USERS", without_secret)
    with pytest.raises(ValueError, match="totpSecret"):
        AuthConfig.from_environment()
    monkeypatch.setenv("ADMIN_REQUIRE_MFA", "false")
    assert AuthConfig.from_environment().users["admin"].totp_secret is None
    monkeypatch.delenv("ADMIN_REQUIRE_MFA", raising=False)
    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([
        {"username": "admin", "passwordHash": HASH, "roles": ["ADMIN"],
         "totpSecret": SECRET},
    ]))
    assert len(AuthConfig.from_environment().users["admin"].totp_secret) >= 16
    for broken in ("SHORTSECRET", "не base32", "JBSWY3DPEHPK3PX!"):
        monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([
            {"username": "admin", "passwordHash": HASH, "roles": ["ADMIN"],
             "totpSecret": broken},
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


def test_account_rutube_url_is_confined_to_rutube() -> None:
    institution = __import__("uuid").uuid4()
    channel = _account_body("rutube", "https://rutube.ru/channel/123", None, None, institution)
    assert channel["url"] == "https://rutube.ru/channel/123/"
    assert channel["externalKey"] == "123"
    assert _account_body("rutube", "123", None, None,
                         institution)["url"] == "https://rutube.ru/channel/123/"
    assert _account_body("rutube", "https://www.rutube.ru/u/studio/", None, None,
                         institution)["url"] == "https://rutube.ru/u/studio/"
    for hostile in ("http://rutube.ru/channel/123/", "https://rutube.ru:8080/channel/123/",
                    "https://127.0.0.1/channel/123/", "https://[::1]/channel/123/",
                    "https://169.254.169.254/latest/meta-data/",
                    "https://rutube.ru@127.0.0.1/channel/123/",
                    "https://rutube.ru.evil.example/channel/123/",
                    "https://rutube.ru/channel/123/?next=http://127.0.0.1"):
        with pytest.raises(Exception):
            _account_body("rutube", hostile, None, None, institution)
        with pytest.raises(Exception):
            _account_body("rutube", "123", None, hostile, institution)


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
