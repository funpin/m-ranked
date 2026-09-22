"""Конфигурация процесса. Значения читаются из окружения один раз при старте."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit


def _int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} должен быть в диапазоне {low}..{high}, получено {value}")
    return value


def _dsn(prefix: str) -> str | None:
    host = os.environ.get(f"{prefix}_DB_HOST")
    if not host:
        return None
    password = os.environ.get(f"{prefix}_DB_PASSWORD")
    password_file = os.environ.get(f"{prefix}_DB_PASSWORD_FILE")
    if password is None and password_file:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError(f"{prefix}_DB_PASSWORD или {prefix}_DB_PASSWORD_FILE обязателен")
    return (
        f"host={host} port={os.environ.get(f'{prefix}_DB_PORT', '5432')} "
        f"dbname={os.environ.get(f'{prefix}_DB_NAME', 'mranked')} "
        f"user={os.environ[f'{prefix}_DB_USER']} "
        f"password={password} "
        f"application_name={os.environ.get('APP_NAME', 'm-ranked-api')}"
    )


def _warmup_targets() -> tuple[str, ...]:
    raw = os.environ.get("API_CACHE_WARMUP_TARGETS", "[]")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("API_CACHE_WARMUP_TARGETS должен быть JSON-массивом") from error
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("API_CACHE_WARMUP_TARGETS должен быть массивом строк")
    result: list[str] = []
    for value in values:
        parsed = urlsplit(value)
        path = unquote(parsed.path).casefold()
        if (
            not value.startswith("/api/v1/") or parsed.scheme or parsed.netloc
            or parsed.fragment or any(
                segment in {"admin", "session", "sessions", "csrf"}
                for segment in path.split("/")
            )
            or any(
                re_name in name.casefold()
                for name, _item in parse_qsl(parsed.query, keep_blank_values=True)
                for re_name in ("token", "authorization", "cookie", "session", "password")
            )
        ):
            raise ValueError("warmup target должен быть публичным относительным API path")
        result.append(value)
    return tuple(dict.fromkeys(result))


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
    deployment_profile: str = field(
        default_factory=lambda: os.environ.get("API_DEPLOYMENT_PROFILE", "a").strip().lower() or "a"
    )
    workers: int = field(default_factory=lambda: _int("API_WORKERS", 1, 1, 32))

    # Верхняя граница тела запроса не зависит от настройки обратного прокси.
    max_body_bytes: int = field(
        default_factory=lambda: _int("API_MAX_BODY_BYTES", 1_048_576, 4_096, 16_777_216))

    # Записей — по одной на логический запрос. Прогрев профиля B держит весь
    # каталог, около тысячи карточек аккаунтов и списков плюс свежие посты,
    # поэтому там значение поднимается в окружении; в памяти одного процесса
    # профиля A хватает прежних 512.
    cache_entries: int = field(default_factory=lambda: _int("API_CACHE_ENTRIES", 512, 0, 65536))
    # Сколько живёт запись. Это же предел несвежести: старше неё ответ не
    # отдаётся, и читатель ждёт пересборку.
    cache_ttl_seconds: int = field(default_factory=lambda: _int("API_CACHE_TTL_SECONDS", 600, 1, 86_400))
    # Сколько запись отдаётся без пересчёта. Старше — отдаётся сразу, а
    # пересчёт идёт фоном.
    cache_fresh_seconds: int = field(default_factory=lambda: _int("API_CACHE_FRESH_SECONDS", 60, 1, 3600))
    # Нижняя граница возраста, раньше которой уведомление о записи не делает
    # запись несвежей: на проде уведомления приходят чаще раза в секунду, и
    # без границы ответ пересчитывался бы непрерывно.
    cache_min_age_seconds: int = field(default_factory=lambda: _int("API_CACHE_MIN_AGE_SECONDS", 60, 0, 600))
    # Сколько держится опубликованная ревизия набора данных. Пересчёты и
    # /revision берут её, а не самую свежую, которая на проде меняется каждые
    # полторы секунды.
    cache_revision_hold_seconds: int = field(
        default_factory=lambda: _int("API_CACHE_REVISION_HOLD_SECONDS", 60, 1, 3600)
    )
    # Сколько фоновых пересчётов процесс ведёт одновременно.
    cache_refresh_concurrency: int = field(
        default_factory=lambda: _int("API_CACHE_REFRESH_CONCURRENCY", 2, 1, 64)
    )
    cache_refresh_lock_seconds: int = field(
        default_factory=lambda: _int("API_CACHE_REFRESH_LOCK_SECONDS", 150, 1, 3600)
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get("API_REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    )
    redis_timeout_ms: int = field(
        default_factory=lambda: _int("API_REDIS_TIMEOUT_MS", 250, 10, 10_000)
    )
    cache_warmup_targets: tuple[str, ...] = field(default_factory=_warmup_targets)
    cache_warmup_interval_seconds: int = field(
        default_factory=lambda: _int("API_CACHE_WARMUP_INTERVAL_SECONDS", 300, 5, 86_400)
    )
    # Греть ли весь каталог: карточки аккаунтов и страницы свежих постов.
    cache_warmup_catalog: bool = field(default_factory=lambda: os.environ.get(
        "API_CACHE_WARMUP_CATALOG", "false").strip().lower() in {"1", "true", "yes", "on"})
    # Посты не старше этого числа часов греются вместе с каталогом.
    cache_warmup_recent_hours: int = field(
        default_factory=lambda: _int("API_CACHE_WARMUP_RECENT_HOURS", 6, 0, 24 * 14)
    )
    # Ответ моложе этого возраста прогрев не пересобирает. Задаёт темп
    # пересборки каталога, а значит и то, насколько он может отставать.
    cache_warmup_max_age_seconds: int = field(
        default_factory=lambda: _int("API_CACHE_WARMUP_MAX_AGE_SECONDS", 600, 1, 86_400)
    )
    # Пересборка каталога — сотни карточек по 0.2–2 с каждая. Один запрос за
    # раз ограничивает прогрев одним ядром: второе остаётся посетителям и
    # приёмнику переноса.
    cache_warmup_concurrency: int = field(
        default_factory=lambda: _int("API_CACHE_WARMUP_CONCURRENCY", 1, 1, 16)
    )
    cache_warmup_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "API_CACHE_WARMUP_BASE_URL", "http://127.0.0.1:8080"
        ).strip().rstrip("/")
    )
    cache_metrics_directory: Path | None = field(default_factory=lambda: (
        Path(value) if (value := os.environ.get("API_CACHE_METRICS_DIRECTORY", "").strip())
        else None
    ))
    cache_warmup_metrics_file: Path | None = field(default_factory=lambda: (
        Path(value) if (value := os.environ.get("API_CACHE_WARMUP_METRICS_FILE", "").strip())
        else None
    ))
    retention_days: int = field(default_factory=lambda: _int("PUBLICATION_RETENTION_DAYS", 70, 1, 3650))

    health_mode: str = field(default_factory=lambda: os.environ.get("HEALTH_DATA_SOURCE", "public_web"))
    poll_interval_minutes: int = field(default_factory=lambda: _int("HEALTH_POLL_INTERVAL_MINUTES", 60, 1, 1440))

    def __post_init__(self) -> None:
        if self.health_mode not in ("public_web", "telegram_web", "mtproto"):
            raise ValueError(f"неизвестный HEALTH_DATA_SOURCE: {self.health_mode}")
        if self.read_pool_min > self.read_pool_max:
            raise ValueError("API_READ_POOL_MIN больше API_READ_POOL_MAX")
        if self.deployment_profile not in {"a", "b"}:
            raise ValueError("API_DEPLOYMENT_PROFILE должен быть a или b")
        redis = urlsplit(self.redis_url)
        if self.deployment_profile == "b" and (
            redis.scheme not in {"redis", "rediss"} or not redis.hostname
        ):
            raise ValueError("API_REDIS_URL должен быть redis:// или rediss:// URL")
        if self.cache_refresh_lock_seconds * 1000 <= self.statement_timeout_ms:
            raise ValueError(
                "API_CACHE_REFRESH_LOCK_SECONDS должен превышать API_STATEMENT_TIMEOUT_MS"
            )
        warmup = urlsplit(self.cache_warmup_base_url)
        if (
            warmup.scheme not in {"http", "https"} or not warmup.hostname
            or warmup.username is not None or warmup.password is not None
            or warmup.query or warmup.fragment
        ):
            raise ValueError("API_CACHE_WARMUP_BASE_URL должен быть HTTP(S) URL")
        if self.cache_metrics_directory is not None and not self.cache_metrics_directory.is_absolute():
            raise ValueError("API_CACHE_METRICS_DIRECTORY должен быть абсолютным путём")
        if self.cache_warmup_metrics_file is not None and not self.cache_warmup_metrics_file.is_absolute():
            raise ValueError("API_CACHE_WARMUP_METRICS_FILE должен быть абсолютным путём")

    @property
    def freshness_seconds(self) -> int:
        """Тот же порог, что был в Java: два интервала опроса, но не меньше 10 минут."""
        return max(self.poll_interval_minutes * 120, 600)
