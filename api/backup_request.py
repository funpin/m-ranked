"""Запрос «обновить резервную копию» из панели управления.

API не запускает дамп сам: у его службы нет и не должно быть прав на
systemd и базу целиком. Он кладёт файл-запрос в отдельный каталог, а
юнит m-ranked-target-dump-backup-request.path от root запускает
m-ranked-target-dump-backup-refresh.service. Повторное нажатие, пока запрос
не взят, ничего не меняет.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

REQUEST_NAME = "refresh"


def request_directory() -> Path:
    return Path(os.environ.get("MRANKED_BACKUP_REQUEST_DIR", "/var/lib/m-ranked/backup-request"))


def request_refresh(username: str, correlation: str, directory: Path | None = None) -> bool:
    """True — запрос записан (или уже ждёт); False — каталог недоступен."""
    root = directory or request_directory()
    target = root / REQUEST_NAME
    if target.exists():
        return True
    try:
        temporary = root / f".{REQUEST_NAME}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps({"requestedBy": username, "correlationId": correlation,
                                         "requestedAt": time.time()}), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        return False
    return True
