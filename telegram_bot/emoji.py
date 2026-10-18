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
