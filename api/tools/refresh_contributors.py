"""Авторы репозитория для шапки сайта: обновление раз в трое суток.

Список, число коммитов и аватары берутся из GitHub и кладутся на сервер: сайт
читает их без пересборки, а посетители по-прежнему не ходят на GitHub за
картинками. Аватар получает в имени хеш содержимого — файл можно кэшировать
навсегда, а смена картинки на GitHub даёт новое имя.

При любой ошибке прежние данные остаются как есть: шапка не должна терять
авторов из-за недоступности GitHub.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("contributors")

REPOSITORY = "funpin/m-ranked"
LIMIT = 8
AVATAR_PIXELS = 64
MAX_AVATAR_BYTES = 512 * 1024
TIMEOUT_SECONDS = 20
STALE_SECONDS = 7 * 86400
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "m-ranked-contributors"}

Fetch = Callable[[str], tuple[bytes, str]]


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 — адреса GitHub
        body = response.read(MAX_AVATAR_BYTES + 1)
        return body, response.headers.get_content_type()


def people(raw: Any) -> list[dict[str, Any]]:
    """Люди из ответа GitHub: без ботов, с проверенными логинами и ссылками."""
    if not isinstance(raw, list):
        raise ValueError("GitHub вернул не список")
    result = []
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "User":
            continue
        login, avatar = str(item.get("login", "")), str(item.get("avatar_url", ""))
        contributions = item.get("contributions")
        if (not LOGIN.match(login) or not avatar.startswith("https://avatars.githubusercontent.com/")
                or not isinstance(contributions, int) or contributions < 0):
            continue
        result.append({"login": login, "contributions": contributions, "avatar_url": avatar})
    return result[:LIMIT]


def refresh(directory: Path, get: Fetch = fetch, now: float | None = None) -> int:
    now = time.time() if now is None else now
    body, _ = get(f"https://api.github.com/repos/{REPOSITORY}/contributors?per_page={LIMIT * 2}")
    found = people(json.loads(body))
    if not found:
        raise ValueError("GitHub не вернул ни одного автора")
    avatars = directory / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    contributors, keep = [], set()
    for person in found:
        separator = "&" if "?" in person["avatar_url"] else "?"
        image, content_type = get(f"{person['avatar_url']}{separator}s={AVATAR_PIXELS}")
        extension = EXTENSIONS.get(content_type)
        if extension is None or not image or len(image) > MAX_AVATAR_BYTES:
            raise ValueError(f"аватар {person['login']}: {content_type}, {len(image)} байт")
        name = f"{person['login']}-{hashlib.sha256(image).hexdigest()[:12]}.{extension}"
        path = avatars / name
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(image)
            os.replace(temporary, path)
        keep.add(name)
        contributors.append({"login": person["login"], "contributions": person["contributions"],
                             "url": f"https://github.com/{person['login']}",
                             "avatar": f"/contributors/live/{name}"})
    listing = directory / "contributors.json"
    temporary = listing.with_suffix(".tmp")
    temporary.write_text(json.dumps(contributors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, listing)
    # Прежние картинки живут ещё неделю: на них ссылаются страницы в кэше nginx
    # и браузеров, собранные со старым списком.
    for stale in avatars.iterdir():
        if stale.name not in keep and now - stale.stat().st_mtime > STALE_SECONDS:
            stale.unlink(missing_ok=True)
    return len(contributors)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    directory = Path(os.environ.get("MRANKED_CONTRIBUTORS_DIR", "/var/lib/m-ranked/contributors"))
    try:
        count = refresh(directory)
    except Exception as error:  # noqa: BLE001 — прежние данные остаются, причина в журнал
        logger.error("авторы не обновлены: %s: %s", type(error).__name__, error)
        return 1
    logger.info("авторов: %d", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
