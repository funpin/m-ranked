"""Журнал и счётчики событий безопасности административного API.

Каждое событие уходит одной JSON-строкой в журнал процесса — его забирает
journald и дальше SIEM — и увеличивает счётчик. Счётчики публикуются
текстовым файлом Prometheus тем же способом, что и
operations/observability/exporter.py, поэтому по ним работают алерты.

В событие не попадают ни пароль, ни одноразовый код, ни CSRF-токен: имя
учётной записи сокращается до устойчивого отпечатка, а причина отказа
берётся из закрытого перечня, чтобы метка метрики оставалась ограниченной.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import Request

logger = logging.getLogger("api.security")

EVENTS = frozenset({"auth.success", "auth.failure", "auth.throttled",
                    "authz.denied", "csrf.rejected",
                    "session.opened", "session.closed", "session.revoked"})
REASONS = frozenset({"none", "credentials", "otp", "otp-replay", "otp-missing",
                     "role", "token-mismatch", "token-invalid", "account", "address",
                     "session", "identity", "origin", "overload", "logout", "admin",
                     "csp"})
PUBLISH_INTERVAL_SECONDS = 15
MAX_SERIES = 64


def fingerprint(username: str) -> str:
    """Устойчивый отпечаток учётной записи: журнал не хранит сами логины."""
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:16] if username else ""


def source_address(request: Request) -> str:
    """Адрес клиента; заголовкам доверяем только от локального обратного прокси."""
    peer = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(peer)
        trusted = address.is_loopback or address.is_private
    except ValueError:
        trusted = False
    if trusted:
        forwarded = (request.headers.get("x-real-ip") or "").strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer or "unknown"


class SecurityTelemetry:
    def __init__(self, path: Path | None = None,
                 interval: int = PUBLISH_INTERVAL_SECONDS) -> None:
        self.path = path
        self.interval = interval
        self.counters: dict[tuple[str, str], int] = {}
        self._published = 0.0

    @classmethod
    def from_environment(cls) -> "SecurityTelemetry":
        configured = os.environ.get("MRANKED_SECURITY_METRICS_FILE", "").strip()
        return cls(Path(configured) if configured else None)

    def record(self, event: str, request: Request, *, username: str = "",
               reason: str = "none", **fields: Any) -> None:
        if event not in EVENTS or reason not in REASONS:
            raise ValueError(f"неизвестное событие безопасности: {event}/{reason}")
        key = (event, reason)
        if key in self.counters or len(self.counters) < MAX_SERIES:
            self.counters[key] = self.counters.get(key, 0)+1
        payload = {
            "event": event, "reason": reason, "account": fingerprint(username),
            "source": source_address(request), "method": request.method,
            "path": request.url.path,
            "requestId": (request.headers.get("x-request-id") or "")[:200],
            "correlationId": (request.headers.get("x-correlation-id") or "")[:200],
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        logger.info("security_event %s", line) if event == "auth.success" \
            else logger.warning("security_event %s", line)
        self.publish()

    def render(self) -> str:
        lines = ["# TYPE mranked_api_security_events_total counter"]
        for (event, reason), value in sorted(self.counters.items()):
            lines.append(f'mranked_api_security_events_total{{event="{event}",'
                         f'reason="{reason}"}} {value}')
        lines.append("# TYPE mranked_api_security_sample_unixtime gauge")
        lines.append(f"mranked_api_security_sample_unixtime {time.time():.0f}")
        return "\n".join(lines)+"\n"

    def publish(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if self.path is None or (not force and now-self._published < self.interval):
            return
        self._published = now
        try:
            self._write(self.path, self.render())
        except OSError:
            logger.warning("не удалось опубликовать счётчики безопасности", exc_info=True)

    @staticmethod
    def _write(path: Path, content: str) -> None:
        if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink():
            raise OSError(f"некорректный путь для счётчиков безопасности: {path}")
        descriptor, name = tempfile.mkstemp(prefix="."+path.name, dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
