"""Жизненный цикл административной сессии на живой базе.

Проверяется то, ради чего состояние вынесено из памяти процесса: обычный
многозапросный сценарий, одноразовость кода при гонке и при перезапуске,
немедленный отзыв и невозможность заблокировать вход чужими неудачами.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient

from conftest import requires_admin_database

pytestmark = requires_admin_database

SECRET = base64.b32decode("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
OTHER = base64.b32decode("MFRGGZDFMZTWQ2LKNNWG23TPOBYXE43U")
PASSWORD = "correct horse battery staple"
CSRF_SECRET = "0123456789abcdef0123456789abcdef"


SECRETS = {"admin": SECRET, "editor": SECRET, "viewer": OTHER}
ROLES = {"admin": ["ADMIN"], "editor": ["EDITOR"], "viewer": ["VIEWER"]}
# Один хеш на весь модуль: bcrypt в десять раундов стоит десятки миллисекунд,
# а проверяем мы здесь не его.
HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode()


def _users(suffix: str, *names: str) -> str:
    return json.dumps([
        {"username": f"{name}-{suffix}", "passwordHash": HASH, "roles": ROLES[name],
         "totpSecret": base64.b32encode(SECRETS[name]).decode().rstrip("=")}
        for name in names
    ])


class Clock:
    """Управляемые часы: шаг TOTP и сроки сессии двигаются явно, а не секундомером.

    Начинают от настоящего времени, чтобы сходиться с часами базы, и дальше
    двигаются только явным вызовом.
    """

    def __init__(self, start: float | None = None) -> None:
        self.value = time.time() if start is None else start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def code(clock: Clock, secret: bytes = SECRET, drift: int = 0) -> str:
    from api.security import totp_code
    return totp_code(secret, int(clock()//30)+drift)


def build(monkeypatch, suffix: str, *names: str, clock: Clock | None = None) -> TestClient:
    """Отдельный экземпляр приложения: так же выглядит и перезапуск процесса."""
    from api.app import create_app
    from api.config import Settings

    monkeypatch.setenv("ADMIN_AUTH_USERS", _users(suffix, *names))
    monkeypatch.setenv("ADMIN_CSRF_SECRET", CSRF_SECRET)
    monkeypatch.setenv("API_READ_DB_HOST", os.environ["API_WRITE_ADMIN_DB_HOST"])
    monkeypatch.setenv("API_READ_DB_PORT", os.environ.get("API_WRITE_ADMIN_DB_PORT", "5432"))
    monkeypatch.setenv("API_READ_DB_NAME", os.environ["API_WRITE_ADMIN_DB_NAME"])
    monkeypatch.setenv("API_READ_DB_USER", os.environ["API_WRITE_ADMIN_DB_USER"])
    monkeypatch.setenv("API_READ_DB_PASSWORD", os.environ["API_WRITE_ADMIN_DB_PASSWORD"])
    # https в базовом адресе нужен, чтобы клиент действительно хранил и
    # возвращал куку, помеченную Secure, — как это делает браузер.
    application = create_app(Settings())
    application.state.clock = clock or Clock()
    # Клиент приходит с петли, поэтому X-Real-IP принимается ровно так же, как
    # от обратного прокси на проде: каждый тест получает свой адрес источника.
    return TestClient(application, base_url="https://testserver",
                      client=("127.0.0.1", 40000))


@pytest.fixture
def clock() -> "Clock":
    return Clock()


@pytest.fixture
def address(suffix: str) -> str:
    return f"2001:db8::{suffix[:4]}"


@pytest.fixture
def suffix() -> str:
    # Учёт кодов ключуется парой «субъект и шаг», поэтому у каждого теста свои
    # имена: иначе код соседнего теста в том же тридцатисекундном окне уже
    # оказался бы потраченным.
    return uuid.uuid4().hex[:12]


@pytest.fixture
def client(monkeypatch, clock, suffix):
    with build(monkeypatch, suffix, "admin", "editor", "viewer", clock=clock) as http:
        yield http


def login(client: TestClient, suffix: str, username: str = "admin", *,
          password: str = PASSWORD, otp: str | None = None, secret: bytes = SECRET):
    return client.post("/api/v1/admin/session",
                       headers={"X-Real-IP": f"2001:db8::{suffix[:4]}"}, json={
        "username": f"{username}-{suffix}", "password": password,
        "otp": code(client.app.state.clock, secret) if otp is None else otp,
    })


def test_one_login_carries_a_whole_multi_request_workflow(client: TestClient, suffix: str) -> None:
    opened = login(client, suffix)
    assert opened.status_code == 201, opened.text
    session = opened.json()
    assert session["canEdit"] and session["canDelete"]
    csrf = session["token"]

    assert client.get("/api/v1/admin/csrf").status_code == 200
    assert client.get("/api/v1/admin/catalog/session").status_code == 200
    assert client.get("/api/v1/admin/catalog/institutions?limit=1").status_code == 200
    assert client.get("/api/v1/admin/jobs?limit=1").status_code == 200

    revoked = client.request("DELETE", "/api/v1/admin/sessions",
                             headers={"X-XSRF-TOKEN": csrf}, json={"subject": f"editor-{suffix}"})
    assert revoked.status_code == 200 and revoked.json()["outcome"] == "revoked"

    closed = client.request("DELETE", "/api/v1/admin/session", headers={"X-XSRF-TOKEN": csrf})
    assert closed.status_code == 200
    assert client.get("/api/v1/admin/csrf").status_code == 401


def test_the_session_cookie_carries_every_required_flag(client: TestClient, suffix: str) -> None:
    header = login(client, suffix).headers["set-cookie"]
    assert header.startswith("__Host-mranked-admin=")
    for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
        assert flag.casefold() in header.casefold(), flag
    assert "Domain=" not in header


def test_a_code_opens_one_session_and_never_a_second(client: TestClient, suffix: str) -> None:
    current = code(client.app.state.clock)
    assert login(client, suffix, otp=current).status_code == 201
    client.cookies.clear()
    replayed = login(client, suffix, otp=current)
    assert replayed.status_code == 401
    assert "token" not in replayed.text


def test_concurrent_logins_with_one_code_leave_exactly_one_session(client: TestClient, suffix: str) -> None:
    current = code(client.app.state.clock)
    statuses = []
    for _ in range(4):
        client.cookies.clear()
        statuses.append(login(client, suffix, otp=current).status_code)
    assert statuses.count(201) == 1
    assert set(statuses) == {201, 401}


def test_replay_and_revocation_survive_a_restart(monkeypatch, clock, suffix, tmp_path) -> None:
    """Учёт кодов и отзыв живут в базе, поэтому перезапуск их не обнуляет."""
    monkeypatch.setenv("MRANKED_EXPORTS_SPOOL_DIRECTORY", str(tmp_path/"first"))
    with build(monkeypatch, suffix, "admin", "editor", "viewer", clock=clock) as first:
        current = code(clock)
        assert login(first, suffix, otp=current).status_code == 201
        token = first.cookies["__Host-mranked-admin"]

    monkeypatch.setenv("MRANKED_EXPORTS_SPOOL_DIRECTORY", str(tmp_path/"second"))
    with build(monkeypatch, suffix, "admin", "editor", "viewer", clock=clock) as restarted:
        restarted.cookies.set("__Host-mranked-admin", token)
        assert restarted.get("/api/v1/admin/csrf").status_code == 200
        restarted.cookies.clear()
        assert login(restarted, suffix, otp=current).status_code == 401

        restarted.cookies.set("__Host-mranked-admin", token)
        csrf = restarted.get("/api/v1/admin/csrf").json()["token"]
        assert restarted.request("DELETE", "/api/v1/admin/session",
                                 headers={"X-XSRF-TOKEN": csrf}).status_code == 200

    monkeypatch.setenv("MRANKED_EXPORTS_SPOOL_DIRECTORY", str(tmp_path/"third"))
    with build(monkeypatch, suffix, "admin", "editor", "viewer", clock=clock) as third:
        third.cookies.set("__Host-mranked-admin", token)
        assert third.get("/api/v1/admin/csrf").status_code == 401


def test_unknown_expired_revoked_and_broken_tokens_are_refused_alike(client: TestClient, suffix: str) -> None:
    from api.sessions import digest

    assert login(client, suffix).status_code == 201
    live = client.cookies["__Host-mranked-admin"]
    bodies = set()
    for token in ("", "not-a-token", "%00", "a"*512, uuid.uuid4().hex):
        client.cookies.set("__Host-mranked-admin", token)
        response = client.get("/api/v1/admin/csrf")
        assert response.status_code == 401
        bodies.add(response.json()["detail"])
    assert len(bodies) == 1

    async def expire() -> None:
        await client.app.state.db.admin_execute(
            "UPDATE ops_and_admin.admin_session SET idle_expires_at = %(moment)s "
            "WHERE token_digest = %(digest)s",
            {"moment": datetime.now(timezone.utc)-timedelta(minutes=1), "digest": digest(live)})

    client.portal.call(expire)
    client.cookies.set("__Host-mranked-admin", live)
    expired = client.get("/api/v1/admin/csrf")
    assert expired.status_code == 401 and expired.json()["detail"] in bodies


def test_a_csrf_token_belongs_to_one_session_only(monkeypatch, suffix, client: TestClient) -> None:
    assert login(client, suffix, "admin").status_code == 201
    admin_csrf = client.get("/api/v1/admin/csrf").json()["token"]
    admin_cookie = client.cookies["__Host-mranked-admin"]

    client.cookies.clear()
    assert login(client, suffix, "editor").status_code == 201
    editor_csrf = client.get("/api/v1/admin/csrf").json()["token"]
    assert editor_csrf != admin_csrf
    assert client.request("DELETE", "/api/v1/admin/session",
                          headers={"X-XSRF-TOKEN": admin_csrf}).status_code == 403

    client.cookies.set("__Host-mranked-admin", admin_cookie)
    assert client.request("DELETE", "/api/v1/admin/session",
                          headers={"X-XSRF-TOKEN": editor_csrf}).status_code == 403


def test_roles_keep_their_exact_authorization_matrix(monkeypatch, suffix, client: TestClient) -> None:
    expected = {
        "viewer": {"read": 200, "revoke": 403},
        "editor": {"read": 200, "revoke": 403},
        "admin": {"read": 200, "revoke": 200},
    }
    for username, wanted in expected.items():
        client.cookies.clear()
        secret = OTHER if username == "viewer" else SECRET
        assert login(client, suffix, username, secret=secret).status_code == 201, username
        csrf = client.get("/api/v1/admin/catalog/session").json()["token"]
        assert client.get("/api/v1/admin/jobs?limit=1").status_code == wanted["read"]
        revoke = client.request("DELETE", "/api/v1/admin/sessions",
                                headers={"X-XSRF-TOKEN": csrf}, json={"subject": "nobody"})
        assert revoke.status_code == wanted["revoke"], username
        # Пауза до следующего шага: код тратится один раз на вход.
        time.sleep(0)


def test_removing_the_account_or_changing_roles_kills_the_session(monkeypatch, suffix,
                                                                  client: TestClient) -> None:
    assert login(client, suffix, "editor").status_code == 201
    assert client.get("/api/v1/admin/csrf").status_code == 200
    monkeypatch.setenv("ADMIN_AUTH_USERS", _users(suffix, "admin"))
    from api.security import AuthConfig
    client.app.state.auth = AuthConfig.from_environment()
    assert client.get("/api/v1/admin/csrf").status_code == 401


def test_failed_logins_elsewhere_cannot_lock_a_correct_login_out(client: TestClient, suffix: str) -> None:
    for index in range(12):
        client.cookies.clear()
        attacker = client.post("/api/v1/admin/session",
                               headers={"X-Real-IP": f"203.0.113.{index}"},
                               json={"username": f"admin-{suffix}", "password": "wrong", "otp": "000000"})
        assert attacker.status_code == 401
    client.cookies.clear()
    assert login(client, suffix).status_code == 201


def test_a_single_address_is_slowed_down_after_a_run_of_failures(client: TestClient, suffix: str) -> None:
    from api.sessions import SessionPolicy

    threshold = SessionPolicy().address_failures
    for _ in range(threshold+1):
        client.cookies.clear()
        response = client.post("/api/v1/admin/session",
                               headers={"X-Real-IP": "198.51.100.7"},
                               json={"username": f"admin-{suffix}", "password": "wrong", "otp": "000000"})
        if response.status_code == 429:
            break
    else:
        response = client.post("/api/v1/admin/session",
                               headers={"X-Real-IP": "198.51.100.7"},
                               json={"username": f"admin-{suffix}", "password": PASSWORD, "otp": code(client.app.state.clock)})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    # Другой адрес по-прежнему входит: замедление не трогает учётную запись.
    client.cookies.clear()
    assert client.post("/api/v1/admin/session", headers={"X-Real-IP": "198.51.100.8"}, json={
        "username": f"admin-{suffix}", "password": PASSWORD, "otp": code(client.app.state.clock)}).status_code == 201


def test_no_response_or_log_carries_a_secret(client: TestClient, suffix: str, caplog) -> None:
    import logging
    with caplog.at_level(logging.INFO, logger="api.security"):
        opened = login(client, suffix)
    token = client.cookies["__Host-mranked-admin"]
    for text in (opened.text, caplog.text):
        assert PASSWORD not in text
        assert token not in text
        assert base64.b32encode(SECRET).decode().rstrip("=") not in text
    assert "__Host-mranked-admin" not in opened.text


def test_idle_and_absolute_limits_end_the_session_on_the_clock(clock, suffix,
                                                               client: TestClient) -> None:
    from api.sessions import SessionPolicy

    policy = SessionPolicy()
    assert login(client, suffix).status_code == 201
    clock.advance(policy.idle_seconds-5)
    assert client.get("/api/v1/admin/csrf").status_code == 200, "запрос продлевает простой"
    clock.advance(policy.idle_seconds+5)
    assert client.get("/api/v1/admin/csrf").status_code == 401, "простой закончился"

    client.cookies.clear()
    clock.advance(60)
    assert login(client, suffix, "editor").status_code == 201
    for _ in range(policy.absolute_seconds//(policy.idle_seconds-60)+2):
        clock.advance(policy.idle_seconds-60)
        response = client.get("/api/v1/admin/csrf")
        if response.status_code == 401:
            break
    assert response.status_code == 401, "абсолютный срок обрывает даже активную сессию"


def test_parallel_reads_and_a_page_refresh_keep_the_session(suffix, client: TestClient) -> None:
    assert login(client, suffix).status_code == 201
    paths = ["/api/v1/admin/csrf", "/api/v1/admin/catalog/session",
             "/api/v1/admin/jobs?limit=1", "/api/v1/admin/catalog/status",
             "/api/v1/admin/catalog/institutions?limit=1"]
    assert [client.get(path).status_code for path in paths*3] == [200]*len(paths)*3


def test_a_stand_without_a_second_factor_still_opens_sessions(monkeypatch, suffix,
                                                              tmp_path) -> None:
    """Выключенный второй фактор не должен делать вход одноразовым."""
    monkeypatch.setenv("ADMIN_REQUIRE_MFA", "false")
    monkeypatch.setenv("MRANKED_EXPORTS_SPOOL_DIRECTORY", str(tmp_path/"stand"))
    users = json.dumps([{"username": f"admin-{suffix}", "passwordHash": HASH,
                         "roles": ["ADMIN"]}])
    monkeypatch.setenv("ADMIN_AUTH_USERS", users)
    with build(monkeypatch, suffix, "admin") as stand:
        monkeypatch.setenv("ADMIN_AUTH_USERS", users)
        from api.security import AuthConfig
        stand.app.state.auth = AuthConfig.from_environment()
        for _ in range(2):
            stand.cookies.clear()
            opened = stand.post("/api/v1/admin/session",
                                headers={"X-Real-IP": f"2001:db8::{suffix[:4]}"},
                                json={"username": f"admin-{suffix}", "password": PASSWORD})
            assert opened.status_code == 201, opened.text
        assert stand.get("/api/v1/admin/csrf").status_code == 200
