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
import re

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


def icon(slot: str) -> str:
    """Значок слота для текста в режиме HTML; неизвестный слот — KeyError."""
    fallback, custom_id = SLOTS[slot]
    if custom_id is None:
        return fallback
    if not _ID.fullmatch(custom_id):
        raise ValueError(f"id кастомного эмодзи слота {slot!r} — не число")
    return f'<tg-emoji emoji-id="{custom_id}">{html.escape(fallback, quote=True)}</tg-emoji>'


def band(slot: str, label: str) -> str:
    """Лента-разделитель блока. До набора — значок слота и жирная надпись;
    с набором её заменят до пяти слотов подряд, складывающихся в одну полосу."""
    return f"{icon(slot)} <b>{html.escape(label, quote=True)}</b>"


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
