#!/usr/bin/env python3
"""Создать набор кастомных эмодзи m-ranked от имени бота и вывести id по слотам.

Запуск на Сервере 2 (там токен бота), из корня релиза:

    .venv/bin/python operations/scripts/create-bot-emoji-set.py \\
        --owner <Telegram ID админа> --files <каталог с out/emoji> \\
        --manifest design/telegram-emoji/emoji-manifest.json

Владелец набора — админ бота (должен был хотя бы раз написать боту). Имя набора
`mranked_emoji_by_<username бота>` (так требует Telegram). Если набор уже есть —
скрипт ничего не меняет и только печатает id (--rebuild удаляет и создаёт заново).
На выходе — JSON «слот → custom_emoji_id» для telegram_bot/emoji.py; токен не
печатается и не пишется в журнал.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN_FILE = "/etc/m-ranked/credentials/telegram-bot-token"
FIRST_BATCH = 50  # createNewStickerSet принимает до 50 стикеров, остальные — addStickerToSet


class TelegramError(Exception):
    pass


def read_token(path: str) -> str:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            return line.strip()
    raise SystemExit(f"в {path} нет токена")


def call(client: httpx.Client, token: str, method: str, *, data: dict | None = None,
         files: dict | None = None) -> object:
    for _ in range(3):
        try:
            response = client.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files)
        except httpx.HTTPError as error:
            raise TelegramError(f"{method}: {type(error).__name__}") from None
        body = response.json()
        if body.get("ok"):
            return body["result"]
        retry = (body.get("parameters") or {}).get("retry_after")
        if response.status_code == 429 and isinstance(retry, int) and retry <= 60:
            time.sleep(retry + 1)
            continue
        raise TelegramError(f"{method}: {body.get('error_code')} {body.get('description')}")
    raise TelegramError(f"{method}: слишком много запросов")


def input_sticker(file_id: str, item: dict) -> dict:
    return {"sticker": file_id, "format": item["format"], "emoji_list": [item["emoji"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner", type=int, required=True)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--token-file", default=TOKEN_FILE)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = manifest["items"]
    missing = [item["file"] for item in items if not (args.files / item["file"]).is_file()]
    if missing:
        raise SystemExit(f"нет файлов: {', '.join(missing)}")
    token = read_token(args.token_file)
    with httpx.Client(timeout=60, trust_env=False) as client:
        username = call(client, token, "getMe")["username"]
        name = f"mranked_emoji_by_{username}"
        try:
            existing = call(client, token, "getStickerSet", data={"name": name})
        except TelegramError:
            existing = None
        if existing and args.rebuild:
            call(client, token, "deleteStickerSet", data={"name": name})
            existing = None
        if existing is None:
            stickers = []
            for item in items:
                path = args.files / item["file"]
                uploaded = call(client, token, "uploadStickerFile",
                                data={"user_id": args.owner, "sticker_format": item["format"]},
                                files={"sticker": (path.name, path.read_bytes())})
                stickers.append(input_sticker(uploaded["file_id"], item))
                print(f"uploaded {item['slot']}", file=sys.stderr)
            call(client, token, "createNewStickerSet", data={
                "user_id": args.owner, "name": name, "title": manifest["title"],
                "sticker_type": "custom_emoji", "stickers": json.dumps(stickers[:FIRST_BATCH])})
            for sticker in stickers[FIRST_BATCH:]:
                call(client, token, "addStickerToSet", data={
                    "user_id": args.owner, "name": name, "sticker": json.dumps(sticker)})
            existing = call(client, token, "getStickerSet", data={"name": name})
        found = existing["stickers"]
        if len(found) != len(items):
            raise SystemExit(f"в наборе {len(found)} эмодзи, в манифесте {len(items)}: пересоздайте с --rebuild")
        ids = {item["slot"]: sticker["custom_emoji_id"] for item, sticker in zip(items, found)}
    print(json.dumps({"set": name, "ids": ids}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
