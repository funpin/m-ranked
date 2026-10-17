"""Настройки бота. Токен лежит в файле, в окружении только путь к нему."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_API_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_SPOOL_DIR = "/var/lib/m-ranked/telegram-bot/inbox"


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Не задана переменная окружения {name}.")
    return value


def _read_token(path: Path) -> str:
    # Сам токен в сообщения не попадает — только путь к файлу.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SystemExit(
            f"Не удалось прочитать файл с токеном бота {path}: "
            f"{type(error).__name__}."
        ) from None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    raise SystemExit(f"Файл с токеном бота {path} пуст.")


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise SystemExit(
                "TELEGRAM_BOT_ADMIN_IDS: ожидается список целых чисел через запятую."
            ) from None
    # Пусто — режим первого запуска: бот отвечает только на /start и /id, чтобы
    # владелец узнал свой ID до того, как впишет его сюда.
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class BotConfig:
    # repr=False: токен не должен попасть ни в лог, ни в трассировку.
    token: str = field(repr=False)
    admin_ids: frozenset[int]
    api_base_url: str
    dsn: str = field(repr=False)
    spool_dir: Path
    timezone: str = "Europe/Moscow"

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "BotConfig":
        token = _read_token(Path(_required(environ, "TELEGRAM_BOT_TOKEN_FILE")))
        return cls(
            token=token,
            admin_ids=_parse_admin_ids(environ.get("TELEGRAM_BOT_ADMIN_IDS", "")),
            api_base_url=(
                environ.get("TELEGRAM_BOT_API_BASE_URL", "").strip()
                or DEFAULT_API_BASE_URL
            ),
            dsn=_required(environ, "TELEGRAM_BOT_DSN"),
            spool_dir=Path(
                environ.get("TELEGRAM_BOT_SPOOL_DIR", "").strip() or DEFAULT_SPOOL_DIR
            ),
        )
