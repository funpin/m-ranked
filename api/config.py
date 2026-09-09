"""Конфигурация процесса. Значения читаются из окружения один раз при старте."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} должен быть в диапазоне {low}..{high}, получено {value}")
    return value


def _dsn(prefix: str) -> str | None:
    host = os.environ.get(f"{prefix}_DB_HOST")
    if not host:
        return None
    return (
        f"host={host} port={os.environ.get(f'{prefix}_DB_PORT', '5432')} "
        f"dbname={os.environ.get(f'{prefix}_DB_NAME', 'mranked')} "
        f"user={os.environ[f'{prefix}_DB_USER']} "
        f"password={os.environ[f'{prefix}_DB_PASSWORD']} "
        f"application_name={os.environ.get('APP_NAME', 'm-ranked-api')}"
    )


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: os.environ.get("SERVER_ADDRESS", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("SERVER_PORT", 8080, 1, 65535))

    # Чтение и админские команды ходят под разными ролями: публичный путь не
    # должен иметь прав на запись даже теоретически.
    read_dsn: str = field(default_factory=lambda: _dsn("API_READ") or "")
    admin_dsn: str | None = field(default_factory=lambda: _dsn("API_WRITE_ADMIN"))
    # Отдельное соединение помечает события outbox доставленными.
    outbox_dsn: str | None = field(default_factory=lambda: _dsn("OUTBOX_WORKER"))

    read_pool_min: int = field(default_factory=lambda: _int("API_READ_POOL_MIN", 2, 1, 32))
    read_pool_max: int = field(default_factory=lambda: _int("API_READ_POOL_MAX", 8, 1, 64))
    statement_timeout_ms: int = field(default_factory=lambda: _int("API_STATEMENT_TIMEOUT_MS", 15_000, 100, 120_000))

    cache_entries: int = field(default_factory=lambda: _int("API_CACHE_ENTRIES", 512, 0, 65536))
    cache_ttl_seconds: int = field(default_factory=lambda: _int("API_CACHE_TTL_SECONDS", 600, 1, 86_400))
    retention_days: int = field(default_factory=lambda: _int("PUBLICATION_RETENTION_DAYS", 70, 1, 3650))

    health_mode: str = field(default_factory=lambda: os.environ.get("HEALTH_DATA_SOURCE", "public_web"))
    poll_interval_minutes: int = field(default_factory=lambda: _int("HEALTH_POLL_INTERVAL_MINUTES", 60, 1, 1440))

    def __post_init__(self) -> None:
        if self.health_mode not in ("public_web", "telegram_web", "mtproto"):
            raise ValueError(f"неизвестный HEALTH_DATA_SOURCE: {self.health_mode}")
        if self.read_pool_min > self.read_pool_max:
            raise ValueError("API_READ_POOL_MIN больше API_READ_POOL_MAX")

    @property
    def freshness_seconds(self) -> int:
        """Тот же порог, что был в Java: два интервала опроса, но не меньше 10 минут."""
        return max(self.poll_interval_minutes * 120, 600)
