"""Парольная политика, равное время ответа и журнал событий безопасности."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import statistics
import time
import uuid

import bcrypt
import pytest

from api.security import (
    MIN_BCRYPT_COST,
    AuthConfig,
    AuthUser,
    csrf_token,
    same_origin,
    totp_code,
)
from api.security_events import SecurityTelemetry, fingerprint

SECRET = base64.b32decode("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
SECRET_TEXT = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
CSRF_SECRET = "0123456789abcdef0123456789abcdef"


def entry(username: str = "admin", *, cost: int = MIN_BCRYPT_COST,
          password: str = "correct-password", secret: str | None = SECRET_TEXT) -> dict:
    item = {"username": username,
            "passwordHash": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=cost)).decode(),
            "roles": ["ADMIN"]}
    if secret is not None:
        item["totpSecret"] = secret
    return item


def configured(monkeypatch, *items: dict) -> AuthConfig:
    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps(list(items)))
    monkeypatch.setenv("ADMIN_CSRF_SECRET", CSRF_SECRET)
    return AuthConfig.from_environment()


class Request:
    """Минимальный запрос: телеметрии нужны только заголовки и адрес."""

    def __init__(self, headers: dict[str, str] | None = None, host: str = "127.0.0.1") -> None:
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}
        self.client = type("Peer", (), {"host": host})()
        self.method = "POST"
        self.url = type("Url", (), {"path": "/api/v1/admin/session"})()


def test_a_weak_or_uneven_password_policy_is_refused(monkeypatch) -> None:
    with pytest.raises(ValueError, match="раундов bcrypt"):
        configured(monkeypatch, entry(cost=4))
    with pytest.raises(ValueError, match="одинаковое число раундов"):
        configured(monkeypatch, entry("admin"), entry("editor", cost=MIN_BCRYPT_COST+1))
    with pytest.raises(ValueError, match="totpSecret"):
        configured(monkeypatch, entry(secret=None))
    assert configured(monkeypatch, entry()).cost == MIN_BCRYPT_COST


def test_a_short_or_missing_csrf_secret_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([entry()]))
    monkeypatch.setenv("ADMIN_CSRF_SECRET", "too-short")
    with pytest.raises(ValueError, match="короче 32"):
        AuthConfig.from_environment()
    monkeypatch.delenv("ADMIN_CSRF_SECRET")
    with pytest.raises(ValueError, match="ADMIN_CSRF_SECRET обязателен"):
        AuthConfig.from_environment()
    monkeypatch.setenv("ADMIN_AUTH_USERS", "[]")
    assert AuthConfig.from_environment().users == {}


def test_an_unknown_name_costs_exactly_the_same_work(monkeypatch) -> None:
    """Дешёвый фиктивный хеш выдавал бы существование учётной записи временем."""
    config = configured(monkeypatch, entry())
    calls: list[tuple[str, int]] = []
    original_checkpw, original_code = bcrypt.checkpw, totp_code

    def counting_checkpw(password: bytes, encoded: bytes) -> bool:
        calls.append(("bcrypt", int(encoded.decode("ascii")[4:6])))
        return original_checkpw(password, encoded)

    def counting_code(secret: bytes, counter: int) -> str:
        calls.append(("totp", len(secret)))
        return original_code(secret, counter)

    monkeypatch.setattr(bcrypt, "checkpw", counting_checkpw)
    monkeypatch.setattr("api.security.totp_code", counting_code)

    async def attempt(username: str) -> list[tuple[str, int]]:
        calls.clear()
        await config.verify(username, "correct-password", "000000", 1_800_000_000.0)
        return list(calls)

    known = asyncio.run(attempt("admin"))
    unknown = asyncio.run(attempt("does-not-exist"))
    assert known == unknown, "разный путь выдал бы существование имени"
    assert [kind for kind, _ in known] == ["bcrypt", "totp", "totp", "totp"]
    assert {cost for kind, cost in known if kind == "bcrypt"} == {MIN_BCRYPT_COST}
    assert config.dummy_hash.decode()[:7] == config.users["admin"].password_hash.decode()[:7]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_the_answer_takes_a_comparable_time_for_both(monkeypatch) -> None:
    """Порог широкий: тест ловит разницу в разы, а не дрожание планировщика."""
    config = configured(monkeypatch, entry())

    def median_for(username: str) -> float:
        samples = []
        for _ in range(5):
            started = time.perf_counter()
            asyncio.run(config.verify(username, "wrong-password", "000000", 1_800_000_000.0))
            samples.append(time.perf_counter()-started)
        return statistics.median(samples)

    known, unknown = median_for("admin"), median_for("nobody")
    assert 0.5 <= known/unknown <= 2.0, (known, unknown)


def test_a_correct_pair_reports_the_step_it_belongs_to(monkeypatch) -> None:
    config = configured(monkeypatch, entry())
    now = 1_800_000_000.0
    counter = int(now//30)

    async def attempt(code: str, password: str = "correct-password"):
        return await config.verify("admin", password, code, now)

    assert asyncio.run(attempt(totp_code(SECRET, counter))).counter == counter
    assert asyncio.run(attempt(totp_code(SECRET, counter-1))).counter == counter-1
    assert asyncio.run(attempt(totp_code(SECRET, counter+9))).reason == "otp"
    assert asyncio.run(attempt("")).reason == "otp"
    assert asyncio.run(attempt(totp_code(SECRET, counter), "wrong")).reason == "credentials"
    # Пароль и код не склеиваются: приписанный к паролю код не открывает вход.
    assert asyncio.run(attempt("", "correct-password"+totp_code(SECRET, counter))).reason \
        == "credentials"


def test_a_csrf_token_is_bound_to_one_session(monkeypatch) -> None:
    config = configured(monkeypatch, entry())
    first, second = uuid.uuid4(), uuid.uuid4()
    assert csrf_token(config.csrf_secret, first) != csrf_token(config.csrf_secret, second)
    assert csrf_token(config.csrf_secret, first) == csrf_token(config.csrf_secret, first)
    assert csrf_token(b"another-secret-of-thirty-two-byt", first) \
        != csrf_token(config.csrf_secret, first)


def test_a_cross_site_sign_in_request_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_EXPECTED_ORIGIN", "https://m.example.org")
    assert same_origin(Request({"Sec-Fetch-Site": "same-origin"}))
    assert same_origin(Request({"Sec-Fetch-Site": "none"}))
    assert same_origin(Request({"Origin": "https://m.example.org"}))
    assert not same_origin(Request({"Sec-Fetch-Site": "cross-site"}))
    assert not same_origin(Request({"Sec-Fetch-Site": "same-site"}))
    assert not same_origin(Request({"Origin": "https://evil.example"}))
    # Браузер с no-referrer шлёт Origin: null, но Sec-Fetch-Site остаётся верным.
    assert same_origin(Request({"Sec-Fetch-Site": "same-origin", "Origin": "null"}))
    monkeypatch.delenv("ADMIN_EXPECTED_ORIGIN")
    assert same_origin(Request({"Origin": "https://anything.example"}))


def test_security_events_are_logged_and_counted_without_secrets(caplog) -> None:
    telemetry = SecurityTelemetry()
    request = Request({"X-Request-Id": "r-1"})
    with caplog.at_level(logging.INFO, logger="api.security"):
        telemetry.record("auth.success", request, username="sigrid-9f")
        telemetry.record("auth.failure", request, username="sigrid-9f", reason="credentials")
        telemetry.record("session.opened", request, username="sigrid-9f")
    events = [json.loads(record.message.split(" ", 1)[1])
              for record in caplog.records if record.message.startswith("security_event ")]
    assert [item["event"] for item in events] == ["auth.success", "auth.failure",
                                                  "session.opened"]
    assert all(item["account"] == fingerprint("sigrid-9f") for item in events)
    assert "sigrid-9f" not in json.dumps(events)
    rendered = telemetry.render()
    assert 'event="auth.failure",reason="credentials"} 1' in rendered
    assert 'event="session.opened",reason="none"} 1' in rendered


def test_metrics_are_published_atomically_to_a_textfile(tmp_path) -> None:
    target = tmp_path/"security.prom"
    telemetry = SecurityTelemetry(target, interval=0)
    telemetry.counters[("auth.failure", "credentials")] = 3
    telemetry.publish(force=True)
    assert 'reason="credentials"} 3' in target.read_text(encoding="utf-8")
    assert target.stat().st_mode & 0o777 == 0o640
    assert not [item for item in tmp_path.iterdir() if item.name.startswith(".")]


def test_unknown_security_events_are_refused() -> None:
    with pytest.raises(ValueError):
        SecurityTelemetry().record("auth.invented", Request(), reason="none")


def test_a_role_set_is_carried_verbatim(monkeypatch) -> None:
    config = configured(monkeypatch, entry())
    assert config.users["admin"] == AuthUser(config.users["admin"].password_hash,
                                             frozenset({"ADMIN"}), SECRET)


def test_a_broken_admin_configuration_closes_the_admin_surface_only(monkeypatch) -> None:
    """Ошибка настройки админки не должна ронять публичное чтение.

    Ровно это и случилось на выкатке: у записи не было totpSecret, приложение
    отказывалось стартовать целиком, и вместе с админкой переставали отвечать
    страницы рейтинга.
    """
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.config import Settings

    monkeypatch.setenv("ADMIN_AUTH_USERS", json.dumps([
        {"username": "admin", "passwordHash": "$2b$10$"+"a"*53, "roles": ["ADMIN"]},
    ]))
    monkeypatch.delenv("ADMIN_REQUIRE_MFA", raising=False)
    monkeypatch.setenv("ADMIN_CSRF_SECRET", CSRF_SECRET)
    monkeypatch.setenv("API_READ_DB_HOST", "")

    application = create_app(Settings())
    assert application.state.auth.failure is not None
    assert "totpSecret" in application.state.auth.failure

    client = TestClient(application)
    assert client.get("/api/v1/health/live").status_code == 200
    for path in ("/api/v1/admin/csrf", "/api/v1/admin/jobs?limit=1"):
        closed = client.get(path)
        assert closed.status_code == 503, path
        assert "totpSecret" in closed.json()["detail"]
    opened = client.post("/api/v1/admin/session",
                         json={"username": "admin", "password": "whatever", "otp": "123456"})
    assert opened.status_code == 503
    assert application.state.security.counters[("config.rejected", "config")] >= 1
