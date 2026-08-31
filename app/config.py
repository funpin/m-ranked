from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Tests for pure modules do not require optional runtime packages.
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


def _int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _float(name: str, default: float) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session_path: Path
    database_path: Path
    initial_channels: tuple[str, ...]
    poll_interval_minutes: int
    track_post_for_hours: int
    complete_history_max_first_age_minutes: int
    jump_min_abs: int
    jump_min_ratio: float
    web_host: str
    web_port: int
    display_timezone: str
    log_path: Path
    discovery_limit: int
    discovery_overlap: int
    data_source: str = "mtproto"
    admin_username: str = "admin"
    admin_password: str | None = None
    admin_csrf_secret: str | None = None
    recent_post_hours: int = 24
    medium_post_hours: int = 168
    medium_poll_interval_minutes: int = 15
    old_poll_interval_minutes: int = 180
    retention_days: int = 40
    subscriber_refresh_hours: int = 24
    archive_dir: Path = Path("data/archives")
    second_day_poll_interval_minutes: int = 15
    third_day_poll_interval_minutes: int = 15
    days_4_to_6_poll_interval_minutes: int = 30
    days_7_to_13_poll_interval_minutes: int = 60
    day_14_plus_poll_interval_minutes: int = 60
    rutube_first_three_days_poll_interval_minutes: int = 60
    rutube_days_4_to_6_poll_interval_minutes: int = 180
    rutube_days_7_to_13_poll_interval_minutes: int = 360
    rutube_day_14_plus_poll_interval_minutes: int = 720
    deletion_confirmation_checks: int = 2
    vk_access_token: str | None = None
    vk_api_version: str = "5.199"
    max_access_token: str | None = None
    max_api_base: str = "https://platform-api2.max.ru"
    rutube_public_api_enabled: bool = True
    rutube_api_base: str = "https://rutube.ru/api"

    @classmethod
    def load(cls, env_file: str | Path = ".env") -> "Settings":
        load_dotenv(env_file, override=False)
        api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
        channels = tuple(
            item.strip() for item in os.getenv("CHANNELS", "").split(",") if item.strip()
        )
        data_source = os.getenv("DATA_SOURCE", "mtproto").strip().lower()
        if data_source not in {"mtproto", "public_web"}:
            raise ValueError("DATA_SOURCE must be mtproto or public_web")
        return cls(
            telegram_api_id=int(api_id_raw) if api_id_raw else None,
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip() or None,
            telegram_session_path=Path(os.getenv("TELEGRAM_SESSION_PATH", "data/telegram.session")),
            database_path=Path(os.getenv("DATABASE_PATH", "data/reactions.db")),
            initial_channels=channels,
            poll_interval_minutes=_int("POLL_INTERVAL_MINUTES", 5),
            track_post_for_hours=_int("TRACK_POST_FOR_HOURS", 960),
            complete_history_max_first_age_minutes=_int(
                "COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES", 6
            ),
            jump_min_abs=_int("JUMP_MIN_ABS", 15),
            jump_min_ratio=_float("JUMP_MIN_RATIO", 2.0),
            web_host=os.getenv("WEB_HOST", "127.0.0.1"),
            web_port=_int("WEB_PORT", 8080),
            display_timezone=os.getenv("DISPLAY_TIMEZONE", "Europe/Moscow"),
            log_path=Path(os.getenv("LOG_PATH", "logs/app.log")),
            discovery_limit=_int("DISCOVERY_LIMIT", 200),
            discovery_overlap=_int("DISCOVERY_OVERLAP", 20),
            data_source=data_source,
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", "").strip() or None,
            admin_csrf_secret=os.getenv("ADMIN_CSRF_SECRET", "").strip() or None,
            recent_post_hours=_int("RECENT_POST_HOURS", 24),
            medium_post_hours=_int("MEDIUM_POST_HOURS", 168),
            medium_poll_interval_minutes=_int("MEDIUM_POLL_INTERVAL_MINUTES", 15),
            old_poll_interval_minutes=_int("OLD_POLL_INTERVAL_MINUTES", 180),
            retention_days=_int("RETENTION_DAYS", 40),
            subscriber_refresh_hours=_int("SUBSCRIBER_REFRESH_HOURS", 24),
            archive_dir=Path(os.getenv("ARCHIVE_DIR", "data/archives")),
            second_day_poll_interval_minutes=_int(
                "SECOND_DAY_POLL_INTERVAL_MINUTES", 15
            ),
            third_day_poll_interval_minutes=_int(
                "THIRD_DAY_POLL_INTERVAL_MINUTES", 15
            ),
            days_4_to_6_poll_interval_minutes=_int(
                "DAYS_4_TO_6_POLL_INTERVAL_MINUTES", 30
            ),
            days_7_to_13_poll_interval_minutes=_int(
                "DAYS_7_TO_13_POLL_INTERVAL_MINUTES", 60
            ),
            day_14_plus_poll_interval_minutes=_int(
                "DAY_14_PLUS_POLL_INTERVAL_MINUTES", 60
            ),
            rutube_first_three_days_poll_interval_minutes=_int(
                "RUTUBE_FIRST_THREE_DAYS_POLL_INTERVAL_MINUTES", 60
            ),
            rutube_days_4_to_6_poll_interval_minutes=_int(
                "RUTUBE_DAYS_4_TO_6_POLL_INTERVAL_MINUTES", 180
            ),
            rutube_days_7_to_13_poll_interval_minutes=_int(
                "RUTUBE_DAYS_7_TO_13_POLL_INTERVAL_MINUTES", 360
            ),
            rutube_day_14_plus_poll_interval_minutes=_int(
                "RUTUBE_DAY_14_PLUS_POLL_INTERVAL_MINUTES", 720
            ),
            deletion_confirmation_checks=_int("DELETION_CONFIRMATION_CHECKS", 2),
            vk_access_token=os.getenv("VK_ACCESS_TOKEN", "").strip() or None,
            vk_api_version=os.getenv("VK_API_VERSION", "5.199").strip() or "5.199",
            max_access_token=os.getenv("MAX_ACCESS_TOKEN", "").strip() or None,
            max_api_base=(
                os.getenv("MAX_API_BASE", "https://platform-api2.max.ru").strip()
                or "https://platform-api2.max.ru"
            ).rstrip("/"),
            rutube_public_api_enabled=_bool("RUTUBE_PUBLIC_API_ENABLED", True),
            rutube_api_base=(
                os.getenv("RUTUBE_API_BASE", "https://rutube.ru/api").strip()
                or "https://rutube.ru/api"
            ).rstrip("/"),
        )

    def require_telegram(self) -> tuple[int, str]:
        if not self.telegram_api_id or not self.telegram_api_hash:
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")
        return self.telegram_api_id, self.telegram_api_hash

    def ensure_directories(self) -> None:
        for path in (self.database_path, self.telegram_session_path, self.log_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
