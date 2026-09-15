"""Аутентификация админки: разовый вход с паролем и кодом, дальше — сессия.

Пароль и одноразовый код предъявляются ровно один раз, в теле POST на вход.
Дальше клиент носит непрозрачный токен сессии в куке `__Host-`, а сервер на
каждом запросе проверяет сессию в базе: срок простоя, абсолютный срок, отзыв
и совпадение ролей с конфигурацией. Код тратится при создании сессии, а не на
каждом запросе, поэтому обычный многозапросный сценарий администратора
работает, а перехваченный код второй раз не подходит.

Замедление перебора считается по адресу источника. Учётную запись оно не
блокирует: иначе пять чужих неудачных попыток закрывали бы вход владельцу.

Неизвестное и известное имя проходят одинаковый путь: одна проверка пароля тем
же алгоритмом и тем же числом раундов, затем одинаковое число проверок кода.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import bcrypt
from fastapi import Depends, Header, Request

from .errors import ApiProblem
from .security_events import SecurityTelemetry, source_address
from .sessions import SESSION_COOKIE, SessionRecord, SessionStore

TOTP_DIGITS = 6
TOTP_STEP_SECONDS = 30
TOTP_DRIFT_STEPS = 1
TOTP_MIN_SECRET_BYTES = 16
MIN_BCRYPT_COST = 10
# Секрет из примера локального стенда не должен уехать в продуктовую среду.
DEMO_SECRETS = frozenset({"local-demo-csrf-secret-change-in-production"})
CSRF_HEADER = "X-XSRF-TOKEN"
_COST = re.compile(r"^\$2[aby]?\$(\d{2})\$")


def _environment_or_file(name: str, default: str = "") -> str:
    direct = os.environ.get(name)
    if direct is not None:
        return direct
    path = os.environ.get(f"{name}_FILE")
    if not path:
        return default
    return Path(path).read_text(encoding="utf-8").strip()


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Principal:
    username: str
    roles: frozenset[str]
    session_id: uuid.UUID


@dataclass(frozen=True)
class AuthUser:
    password_hash: bytes
    roles: frozenset[str]
    totp_secret: bytes | None


@dataclass(frozen=True)
class Attempt:
    """Итог проверки пары «пароль и код» без деления на «нет записи» и «не тот пароль»."""

    user: AuthUser | None
    counter: int | None
    reason: str

    @property
    def accepted(self) -> bool:
        return self.reason == "none"


def totp_code(secret: bytes, counter: int) -> str:
    """RFC 6238 поверх RFC 4226: HMAC-SHA1, шаг 30 секунд, шесть цифр."""
    mac = hmac.new(secret, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    truncated = int.from_bytes(mac[offset:offset+4], "big") & 0x7FFF_FFFF
    return str(truncated % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def _totp_secret(value: Any) -> bytes | None:
    if value is None or not str(value).strip():
        return None
    text = "".join(str(value).split()).upper()
    try:
        secret = base64.b32decode(text+"="*(-len(text) % 8), casefold=False)
    except (binascii.Error, ValueError) as error:
        raise ValueError("ADMIN_AUTH_USERS: totpSecret должен быть в base32") from error
    if len(secret) < TOTP_MIN_SECRET_BYTES:
        raise ValueError(f"ADMIN_AUTH_USERS: totpSecret короче {TOTP_MIN_SECRET_BYTES} байт")
    return secret


def _bcrypt_cost(encoded: bytes) -> int:
    match = _COST.match(encoded.decode("ascii", "ignore"))
    if match is None:
        raise ValueError("ADMIN_AUTH_USERS: passwordHash не похож на bcrypt")
    return int(match.group(1))


class AuthConfig:
    """Учётные записи админки и их единая парольная политика.

    Число раундов bcrypt обязано совпадать у всех записей: разные стоимости
    дали бы разное время ответа и подсказали бы перебирающему, какие имена
    существуют. По той же причине несуществующее имя проверяется фиктивным
    хешем той же стоимости.
    """

    def __init__(self, users: dict[str, AuthUser], csrf_secret: bytes,
                 cost: int = MIN_BCRYPT_COST, verifiers: int = 2) -> None:
        self.users = users
        self.csrf_secret = csrf_secret
        self.cost = cost
        self.dummy_hash = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=cost))
        # Фиктивный секрет длиной с самый длинный настоящий: HMAC всё равно
        # разворачивает ключ до блока, но одинаковая длина снимает вопрос.
        self.dummy_secret = secrets.token_bytes(max(
            [TOTP_MIN_SECRET_BYTES]+[len(user.totp_secret) for user in users.values()
                                     if user.totp_secret]))
        # Проверка пароля стоит десятки миллисекунд процессора. Без границы
        # параллелизма поток неудачных входов съел бы ядро целиком.
        self.verifiers = asyncio.Semaphore(max(1, verifiers))

    @classmethod
    def from_environment(cls) -> "AuthConfig":
        raw_value: Any = json.loads(_environment_or_file("ADMIN_AUTH_USERS", "[]"))
        if not isinstance(raw_value, list):
            raise ValueError("ADMIN_AUTH_USERS должен быть JSON-массивом")
        require_mfa = _flag("ADMIN_REQUIRE_MFA", True)
        minimum = int(os.environ.get("ADMIN_MIN_BCRYPT_COST", MIN_BCRYPT_COST))
        users: dict[str, AuthUser] = {}
        costs: set[int] = set()
        for item in raw_value:
            if not isinstance(item, dict):
                raise ValueError("некорректная конфигурация ADMIN_AUTH_USERS")
            username = str(item.get("username", "")).strip()
            encoded = str(item.get("passwordHash", item.get("password-hash", "")))
            if encoded.startswith("{bcrypt}"):
                encoded = encoded.removeprefix("{bcrypt}")
            roles = frozenset(str(role).upper() for role in item.get("roles", []))
            if (not username or len(username) > 200 or username in users
                    or not encoded.startswith("$2") or not roles
                    or not roles <= {"VIEWER", "EDITOR", "ADMIN"}
                    or any(ord(character) < 32 for character in username)):
                raise ValueError("некорректная конфигурация ADMIN_AUTH_USERS")
            cost = _bcrypt_cost(encoded.encode("ascii"))
            if cost < minimum:
                raise ValueError(
                    f"ADMIN_AUTH_USERS: passwordHash слабее {minimum} раундов bcrypt")
            costs.add(cost)
            secret = _totp_secret(item.get("totpSecret", item.get("totp-secret")))
            if secret is None and require_mfa:
                raise ValueError(
                    "ADMIN_AUTH_USERS: у записи нет totpSecret, а ADMIN_REQUIRE_MFA включён")
            users[username] = AuthUser(encoded.encode("ascii"), roles, secret)
        if len(costs) > 1:
            raise ValueError(
                "ADMIN_AUTH_USERS: все записи обязаны иметь одинаковое число раундов bcrypt")
        configured_secret = _environment_or_file("ADMIN_CSRF_SECRET")
        if configured_secret:
            csrf_secret = configured_secret.encode()
            if len(csrf_secret) < 32:
                raise ValueError("ADMIN_CSRF_SECRET короче 32 байт")
            if (configured_secret in DEMO_SECRETS
                    and not _flag("ADMIN_ALLOW_DEMO_SECRETS", False)):
                raise ValueError("ADMIN_CSRF_SECRET взят из примера для локального стенда")
        elif users and not _flag("ADMIN_ALLOW_EPHEMERAL_CSRF_SECRET", False):
            # Без общего секрета CSRF-токены не пережили бы перезапуск и не
            # сошлись бы между воркерами. Пустой список записей — не настроенная
            # админка, там и проверять нечего.
            raise ValueError("ADMIN_CSRF_SECRET обязателен при настроенных учётных записях")
        else:
            csrf_secret = secrets.token_bytes(32)
        return cls(users, csrf_secret, max(costs) if costs else minimum,
                   int(os.environ.get("ADMIN_PASSWORD_VERIFIERS", 2)))

    def _match_code(self, secret: bytes, code: str, now: float) -> int | None:
        """Перебрать окно допуска целиком: выход по первому совпадению измерим."""
        counter = int(now//TOTP_STEP_SECONDS)
        matched: int | None = None
        for drift in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS+1):
            candidate = counter+drift
            if hmac.compare_digest(totp_code(secret, candidate), code) and matched is None:
                matched = candidate
        return matched

    async def verify(self, username: str, password: str, code: str, now: float) -> Attempt:
        """Один и тот же объём работы для известного и неизвестного имени."""
        user = self.users.get(username)
        password_hash = user.password_hash if user is not None else self.dummy_hash
        try:
            async with asyncio.timeout(5):
                async with self.verifiers:
                    valid = await asyncio.to_thread(
                        bcrypt.checkpw, password.encode("utf-8"), password_hash)
        except TimeoutError as error:
            raise ApiProblem(429, "Too Many Requests", "Сервис входа перегружен, повторите позже",
                             "urn:m-ranked:problem:too-many-requests",
                             headers={"Retry-After": "5"}) from error
        except ValueError:
            valid = False
        secret = user.totp_secret if user is not None and user.totp_secret else self.dummy_secret
        shaped = code if len(code) == TOTP_DIGITS and code.isdigit() else "\x00"*TOTP_DIGITS
        counter = self._match_code(secret, shaped, now)
        if user is None or not valid:
            return Attempt(None, None, "credentials")
        if user.totp_secret is None:
            return Attempt(user, None, "none")
        if counter is None:
            return Attempt(user, None, "otp")
        return Attempt(user, counter, "none")


def csrf_token(secret: bytes, session_id: uuid.UUID) -> str:
    """Синхронизирующий токен, привязанный к сессии: чужой не подойдёт."""
    mac = hmac.new(secret, b"csrf:"+session_id.bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _unauthorized() -> ApiProblem:
    return ApiProblem(401, "Unauthorized", "Требуется вход администратора",
                      "urn:m-ranked:problem:unauthorized")


def _telemetry(request: Request) -> SecurityTelemetry:
    existing = getattr(request.app.state, "security", None)
    if existing is None:
        existing = SecurityTelemetry()
        request.app.state.security = existing
    return existing


def _store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "sessions", None)
    if store is None:
        raise ApiProblem(503, "Service Unavailable", "Хранилище сессий не настроено")
    return store


async def current_session(request: Request) -> SessionRecord:
    record = await _store(request).resolve(request.cookies.get(SESSION_COOKIE) or "")
    if record is None:
        _telemetry(request).record("auth.failure", request, reason="session")
        raise _unauthorized()
    return record


async def principal(
    request: Request,
    record: Annotated[SessionRecord, Depends(current_session)],
) -> Principal:
    config: AuthConfig = request.app.state.auth
    user = config.users.get(record.subject)
    if user is None or user.roles != record.roles:
        # Запись убрали или роли изменили — сессия больше не отражает права.
        await _store(request).revoke(record.id, "identity_changed")
        _telemetry(request).record("session.revoked", request, username=record.subject,
                                   reason="identity")
        raise _unauthorized()
    return Principal(record.subject, record.roles, record.id)


def require_roles(*roles: str):
    allowed = frozenset(roles)

    async def dependency(request: Request,
                         user: Annotated[Principal, Depends(principal)]) -> Principal:
        if not (user.roles & allowed):
            _telemetry(request).record("authz.denied", request, username=user.username,
                                       reason="role")
            raise ApiProblem(403, "Forbidden", "Недостаточно прав",
                             "urn:m-ranked:problem:forbidden")
        return user

    return dependency


async def require_csrf(
    request: Request,
    user: Annotated[Principal, Depends(principal)],
    header: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> None:
    expected = csrf_token(request.app.state.auth.csrf_secret, user.session_id)
    if not header or not hmac.compare_digest(header, expected):
        _telemetry(request).record("csrf.rejected", request, username=user.username,
                                   reason="token-mismatch")
        raise ApiProblem(403, "Forbidden", "CSRF-токен отсутствует или не принадлежит сессии",
                         "urn:m-ranked:problem:forbidden")


def same_origin(request: Request) -> bool:
    """Отсечь вход по запросу с чужого сайта, не доверяя переданному authority.

    Браузер сам сообщает происхождение запроса в Sec-Fetch-Site, и подделать
    этот заголовок со страницы нельзя. Origin проверяется только там, где
    Sec-Fetch-Site нет — у клиентов, которые браузером не являются, — и только
    против явно настроенного значения: заголовок Host сюда приходит от клиента.
    """
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site:
        return site in ("same-origin", "none")
    origin = (request.headers.get("origin") or "").strip()
    expected = os.environ.get("ADMIN_EXPECTED_ORIGIN", "").strip()
    return not (origin and expected) or origin.rstrip("/") == expected.rstrip("/")


def throttled(seconds: int) -> ApiProblem:
    return ApiProblem(429, "Too Many Requests",
                      "Слишком много неудачных попыток входа, повторите позже",
                      "urn:m-ranked:problem:too-many-requests",
                      headers={"Retry-After": str(max(1, seconds))})


__all__ = ["Attempt", "AuthConfig", "AuthUser", "Principal", "SESSION_COOKIE",
           "csrf_token", "current_session", "principal", "require_csrf", "require_roles",
           "same_origin", "source_address", "throttled", "totp_code"]
