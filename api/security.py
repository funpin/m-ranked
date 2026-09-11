"""Stateless HTTP Basic roles and signed double-submit CSRF tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import bcrypt
from fastapi import Cookie, Depends, Header, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .errors import ApiProblem

_basic = HTTPBasic(auto_error=False)
_dummy_hash = bcrypt.hashpw(b"m-ranked-dummy-password", bcrypt.gensalt(rounds=4))


def _environment_or_file(name: str, default: str = "") -> str:
    direct = os.environ.get(name)
    if direct is not None:
        return direct
    path = os.environ.get(f"{name}_FILE")
    if not path:
        return default
    return Path(path).read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class Principal:
    username: str
    roles: frozenset[str]


class AuthConfig:
    def __init__(self, users: dict[str, tuple[bytes, frozenset[str]]], csrf_secret: bytes) -> None:
        self.users = users
        self.csrf_secret = csrf_secret

    @classmethod
    def from_environment(cls) -> "AuthConfig":
        raw_value: Any = json.loads(_environment_or_file("ADMIN_AUTH_USERS", "[]"))
        if not isinstance(raw_value, list):
            raise ValueError("ADMIN_AUTH_USERS должен быть JSON-массивом")
        users: dict[str, tuple[bytes, frozenset[str]]] = {}
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
            users[username] = (encoded.encode("ascii"), roles)
        configured_secret = _environment_or_file("ADMIN_CSRF_SECRET")
        secret = configured_secret.encode() if configured_secret else secrets.token_bytes(32)
        return cls(users, secret)


def _unauthorized() -> ApiProblem:
    return ApiProblem(401, "Unauthorized", "Требуется HTTP Basic аутентификация",
                      "urn:m-ranked:problem:unauthorized",
                      headers={"WWW-Authenticate": 'Basic realm="m-ranked-admin"'})


async def principal(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
) -> Principal:
    config: AuthConfig = request.app.state.auth
    username = credentials.username if credentials else ""
    configured = config.users.get(username)
    password_hash = configured[0] if configured else _dummy_hash
    password = credentials.password.encode() if credentials else b""
    try:
        valid = bcrypt.checkpw(password, password_hash)
    except ValueError:
        valid = False
    if configured is None or not valid:
        raise _unauthorized()
    return Principal(username, configured[1])


def require_roles(*roles: str):
    allowed = frozenset(roles)

    async def dependency(user: Annotated[Principal, Depends(principal)]) -> Principal:
        if not (user.roles & allowed):
            raise ApiProblem(403, "Forbidden", "Недостаточно прав",
                             "urn:m-ranked:problem:forbidden")
        return user

    return dependency


def issue_csrf(config: AuthConfig) -> str:
    payload = f"{int(time.time())}:{secrets.token_urlsafe(24)}"
    signature = hmac.new(config.csrf_secret, payload.encode(), hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return encoded_payload+"."+encoded_signature


async def require_csrf(
    request: Request,
    header: Annotated[str | None, Header(alias="X-XSRF-TOKEN")] = None,
    cookie: Annotated[str | None, Cookie(alias="XSRF-TOKEN")] = None,
) -> None:
    if not header or not cookie or not hmac.compare_digest(header, cookie):
        raise ApiProblem(403, "Forbidden", "CSRF-токен отсутствует или не совпадает",
                         "urn:m-ranked:problem:forbidden")
    try:
        encoded_payload, encoded_signature = header.split(".", 1)
        payload = base64.b64decode(encoded_payload+"="*(-len(encoded_payload) % 4),
                                   altchars=b"-_", validate=True)
        signature = base64.b64decode(encoded_signature+"="*(-len(encoded_signature) % 4),
                                     altchars=b"-_", validate=True)
        timestamp = int(payload.split(b":", 1)[0])
        expected = hmac.new(request.app.state.auth.csrf_secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected) or abs(time.time()-timestamp) > 12*3600:
            raise ValueError
    except (ValueError, TypeError) as error:
        raise ApiProblem(403, "Forbidden", "CSRF-токен повреждён или устарел",
                         "urn:m-ranked:problem:forbidden") from error
