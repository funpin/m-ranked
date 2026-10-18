"""Слоты значков: запасное обычное эмодзи и, когда появится набор, кастомное."""
from __future__ import annotations

import pytest

from telegram_bot import emoji

ALL_SLOTS = ("logo", "telegram", "vk", "max", "rutube", "band_ours", "band_others", "band_week",
             "band_forecast", "rank_1", "rank_2", "rank_3", "up", "down", "promo", "anomaly",
             "spike", "alert_urgent")
FAKE_ID = "1234567890123456789"


def test_all_slots_present_with_fallbacks_and_no_ids_yet():
    assert set(emoji.SLOTS) == set(ALL_SLOTS)
    for slot, (fallback, custom_id) in emoji.SLOTS.items():
        assert fallback and "<" not in fallback, slot
        assert custom_id is None, slot  # набор (часть 2) ещё не сделан


def test_fallbacks_are_the_agreed_ones():
    assert {slot: fallback for slot, (fallback, _) in emoji.SLOTS.items()} == {
        "logo": "📊", "telegram": "✈️", "vk": "🔵", "max": "🟣", "rutube": "▶️",
        "band_ours": "🏆", "band_others": "🌐", "band_week": "📅", "band_forecast": "🔮",
        "rank_1": "🥇", "rank_2": "🥈", "rank_3": "🥉", "up": "📈", "down": "📉",
        "promo": "📣", "anomaly": "⚠️", "spike": "🚀", "alert_urgent": "🚨",
    }


def test_icon_without_id_is_plain_fallback():
    assert emoji.icon("vk") == "🔵"
    assert emoji.icon("rank_1") == "🥇"


def test_icon_with_id_is_tg_emoji(monkeypatch):
    monkeypatch.setitem(emoji.SLOTS, "vk", ("🔵", FAKE_ID))
    assert emoji.icon("vk") == f'<tg-emoji emoji-id="{FAKE_ID}">🔵</tg-emoji>'
    monkeypatch.setitem(emoji.SLOTS, "promo", ('<&">', FAKE_ID))
    assert emoji.icon("promo") == f'<tg-emoji emoji-id="{FAKE_ID}">&lt;&amp;&quot;&gt;</tg-emoji>'


@pytest.mark.parametrize("bad", ["", "12a", '1" onclick="x', "-5", "١٢٣"])
def test_icon_rejects_non_digit_id(monkeypatch, bad):
    monkeypatch.setitem(emoji.SLOTS, "vk", ("🔵", bad))
    with pytest.raises(ValueError):
        emoji.icon("vk")


def test_unknown_slot_is_key_error():
    with pytest.raises(KeyError):
        emoji.icon("nope")


def test_band_is_icon_and_bold_label(monkeypatch):
    assert emoji.band("band_ours", "НАШИ ЛУЧШИЕ") == "🏆 <b>НАШИ ЛУЧШИЕ</b>"
    assert emoji.band("band_week", "A<b>") == "📅 <b>A&lt;b&gt;</b>"
    monkeypatch.setitem(emoji.SLOTS, "band_week", ("📅", FAKE_ID))
    assert emoji.band("band_week", "НЕДЕЛЯ") == f'<tg-emoji emoji-id="{FAKE_ID}">📅</tg-emoji> <b>НЕДЕЛЯ</b>'


# --- набор m-ranked: id из telegram_bot/emoji-ids.json, плашки из пяти эмодзи ------

def test_load_ids_keeps_only_digit_ids(tmp_path):
    from telegram_bot.emoji import load_ids
    path = tmp_path / "ids.json"
    path.write_text('{"ids": {"vk": "1234567890123456789", "max": "x1", "logo": 5}}', encoding="utf-8")
    assert load_ids(path) == {"vk": "1234567890123456789"}
    assert load_ids(tmp_path / "missing.json") == {}


def test_band_uses_five_tile_banner_when_all_tiles_loaded(monkeypatch):
    from telegram_bot import emoji
    tiles = {f"band_week_{i}": f"90000000000000000{i:02d}" for i in range(1, 6)}
    monkeypatch.setattr(emoji, "IDS", {**emoji.IDS, **tiles})
    line = emoji.band("band_week", "НЕДЕЛЯ")
    assert line.count("<tg-emoji") == 5 and "НЕДЕЛЯ" not in line  # надпись — внутри плашки
    assert line.startswith('<tg-emoji emoji-id="9000000000000000001">📅</tg-emoji>')
    assert line.count(">➖</tg-emoji>") == 4  # без рендера: «📅➖➖➖➖»


def test_band_falls_back_to_text_when_banner_incomplete(monkeypatch):
    from telegram_bot import emoji
    monkeypatch.setattr(emoji, "IDS", {"band_week_1": "1"})
    assert emoji.band("band_week", "НЕДЕЛЯ") == "📅 <b>НЕДЕЛЯ</b>"
    assert emoji.banner("НЕИЗВЕСТНО") is None


def test_icon_reads_loaded_ids(monkeypatch):
    from telegram_bot import emoji
    monkeypatch.setattr(emoji, "IDS", {"vk": "1234567890123456789"})
    assert emoji.icon("vk") == '<tg-emoji emoji-id="1234567890123456789">🔵</tg-emoji>'
    assert emoji.icon("max") == "🟣"
