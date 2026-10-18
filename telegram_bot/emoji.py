"""Слоты значков бота: запасное обычное эмодзи и id кастомного из нашего набора.

Все значки в тексте берутся отсюда, по имени слота. Пока набора нет (часть 2
спека 2026-10-18), id пустые и выводится обычное эмодзи. Когда набор появится,
id из ответа createNewStickerSet вписываются в таблицу — тексты править не надо.
id кастомных эмодзи публичны, это не секрет. У читателей без Premium и в
уведомлениях Telegram сам покажет запасное эмодзи из тега.

На кнопках кастомных эмодзи нет (решение владельца): кнопки — обычный текст.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

# Слот → (запасное обычное эмодзи, id кастомного или None).
SLOTS: dict[str, tuple[str, str | None]] = {
    "logo": ("📊", None),
    "telegram": ("✈️", None),
    "vk": ("🔵", None),
    "max": ("🟣", None),
    "rutube": ("▶️", None),
    "band_ours": ("🏆", None),
    "band_others": ("🌐", None),
    "band_week": ("📅", None),
    "band_forecast": ("🔮", None),
    "rank_1": ("🥇", None),
    "rank_2": ("🥈", None),
    "rank_3": ("🥉", None),
    "up": ("📈", None),
    "down": ("📉", None),
    "promo": ("📣", None),
    "anomaly": ("⚠️", None),
    "spike": ("🚀", None),
    "alert_urgent": ("🚨", None),
}

_ID = re.compile(r"[0-9]+", re.ASCII)

# Плашки-разделители: надпись нарисована внутри пяти эмодзи подряд (набор
# design/telegram-emoji). Надпись → (слот плашки, запасной значок первого
# квадрата). Без рендера (уведомления, пересылка) плашка читается «📅➖➖➖➖».
BANNERS: dict[str, tuple[str, str]] = {
    "НАШИ ЛУЧШИЕ": ("band_ours", "🏆"),
    "ДРУГИЕ ВУЗЫ": ("band_others", "🌐"),
    "НЕДЕЛЯ": ("band_week", "📅"),
    "ПРОГНОЗ": ("band_forecast", "🔮"),
    "ПОСТЫ": ("band_posts", "📝"),
    "СЕРВЕР": ("band_server", "🖥️"),
    "ПРОБЛЕМЫ": ("band_problems", "⚠️"),
    "СБОР": ("band_collection", "📡"),
    "СЕРВЕР 2": ("band_server2", "🖥️"),
}
BANNER_TILES = 5
BANNER_FILL = "➖"
IDS_FILE = Path(__file__).resolve().parent / "emoji-ids.json"


def load_ids(path: Path) -> dict[str, str]:
    """id набора по слотам из файла, который печатает
    operations/scripts/create-bot-emoji-set.py; нет файла — пусто (обычные эмодзи)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ids = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(ids, dict):
        return {}
    return {slot: value for slot, value in ids.items()
            if isinstance(slot, str) and isinstance(value, str) and _ID.fullmatch(value)}


IDS: dict[str, str] = load_ids(IDS_FILE)


def _tag(custom_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{custom_id}">{html.escape(fallback, quote=True)}</tg-emoji>'


def icon(slot: str) -> str:
    """Значок слота для текста в режиме HTML; неизвестный слот — KeyError."""
    fallback, custom_id = SLOTS[slot]
    custom_id = IDS.get(slot, custom_id)
    if custom_id is None:
        return fallback
    if not _ID.fullmatch(custom_id):
        raise ValueError(f"id кастомного эмодзи слота {slot!r} — не число")
    return _tag(custom_id, fallback)


def banner(label: str) -> str | None:
    """Плашка с надписью из пяти кастомных эмодзи подряд или None, если её
    квадратов в наборе нет (или загружены не все)."""
    entry = BANNERS.get(label)
    if entry is None:
        return None
    slot, first = entry
    ids = [IDS.get(f"{slot}_{index}") for index in range(1, BANNER_TILES + 1)]
    if not all(ids):
        return None
    return "".join(_tag(custom_id, first if index == 0 else BANNER_FILL)  # type: ignore[arg-type]
                   for index, custom_id in enumerate(ids))


def band(slot: str, label: str) -> str:
    """Лента-разделитель блока: плашка из набора, а без неё — значок слота и
    жирная надпись."""
    return banner(label) or f"{icon(slot)} <b>{html.escape(label, quote=True)}</b>"


def describe_custom_emoji(message: dict) -> str:
    """Ответ на /emoji (или на присланный эмодзи-стикер): id каждого кастомного
    эмодзи — их вписывают в SLOTS. Смещения сущностей Telegram — в единицах UTF-16."""
    sticker = message.get("sticker")
    if isinstance(sticker, dict):
        if sticker.get("type") == "custom_emoji" and _ID.fullmatch(str(sticker.get("custom_emoji_id", ""))):
            found = [(str(sticker.get("emoji") or "?"), str(sticker["custom_emoji_id"]))]
        else:
            return ("Это обычный стикер, а не кастомный эмодзи: в тексте его не поставить. "
                    "Пришлите эмодзи из набора эмодзи вместе с командой /emoji.")
    else:
        units = (message.get("text") or "").encode("utf-16-le")
        found = []
        for entity in message.get("entities") or []:
            emoji_id = str(entity.get("custom_emoji_id", ""))
            if entity.get("type") != "custom_emoji" or not _ID.fullmatch(emoji_id):
                continue
            start, length = int(entity.get("offset", 0)), int(entity.get("length", 0))
            glyph = units[start * 2:(start + length) * 2].decode("utf-16-le", errors="replace")
            found.append((glyph or "?", emoji_id))
    if not found:
        return ("В сообщении кастомных эмодзи нет. Пришлите /emoji и сразу за ним "
                "нужные эмодзи из набора (нужен Telegram Premium).")
    lines = ["<b>Кастомные эмодзи в сообщении</b>"]
    lines += [f'<tg-emoji emoji-id="{emoji_id}">{html.escape(glyph, quote=True)}</tg-emoji> — <code>{emoji_id}</code>'
              for glyph, emoji_id in found]
    return "\n".join(lines)
