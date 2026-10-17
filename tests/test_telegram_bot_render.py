"""Тексты и кнопки бота: чистые функции без ввода-вывода."""
from __future__ import annotations

import copy
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from telegram_bot.render import (
    Message,
    decode_callback,
    encode_callback,
    our_week_stats,
    period_label,
    render_digest,
    render_help,
    render_top,
    render_week,
    split_message,
    top_keyboard,
)
from telegram_bot.words import TopQuery

FIXTURES = Path(__file__).parent / "fixtures" / "telegram_bot"
OUR_ID = 4
LABEL = "10–16 окт"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def text_of(messages: list[Message]) -> str:
    return "\n".join(m.text for m in messages)


def with_items(body: dict, items: list[dict]) -> dict:
    body = copy.deepcopy(body)
    body["items"] = items
    return body


def test_render_ours_groups_by_platform():
    body = fixture("findings_institution.json")
    text = text_of(render_top(TopQuery(), body, OUR_ID, LABEL))
    assert "Наши лучшие посты" in text and LABEL in text
    for title in ("Telegram", "ВКонтакте", "Rutube"):
        assert f"<b>{title}</b>" in text
    assert "MAX" not in text  # у площадки нет находок: пустую секцию не рисуем
    assert text.index("<b>Telegram</b>") < text.index("<b>ВКонтакте</b>") < text.index("<b>Rutube</b>")
    # В Telegram четыре поста, показаны три; ВК и Rutube набрали меньше трёх.
    assert text.count("https://t.me/example/") == 3
    assert text.count("выше нормы только") == 2
    assert "выше нормы только 2" in text  # ВКонтакте
    assert "выше нормы только 1" in text  # Rutube


def test_render_counts_follow_query():
    body = fixture("findings_institution.json")
    text = text_of(render_top(TopQuery(count=1), body, OUR_ID, LABEL))
    assert text.count("https://t.me/example/") == 1
    text = text_of(render_top(TopQuery(count=20, platform="telegram"), body, OUR_ID, LABEL))
    assert text.count("https://t.me/example/") == 4
    assert "выше нормы только 4" in text


def test_render_all_marks_us_and_promotion():
    body = fixture("findings_all.json")
    messages = render_top(TopQuery(who="all"), body, OUR_ID, LABEL)
    text = text_of(messages)
    assert "Лучшие посты всех вузов" in text
    lines = [line for line in text.splitlines() if line[:1].isdigit()]
    assert len(lines) == 10
    ours = [line for line in lines if "Дельта" in line]
    assert ours and all("мы" in line for line in ours)
    assert not any("мы" in line for line in lines if "Дельта" not in line)
    promo = [line for line in lines if "📣 продвижение" in line]
    assert len(promo) == 1 and "Бета" in promo[0]
    assert text.rstrip().endswith("Скрыто подозрительных: 4")


def test_hidden_footer_only_when_needed():
    body = fixture("findings_all.json")
    shown = text_of(render_top(TopQuery(who="all", suspicious=True), body, OUR_ID, LABEL))
    assert "Скрыто подозрительных" not in shown
    body["hiddenAnomalous"] = 0
    assert "Скрыто подозрительных" not in text_of(render_top(TopQuery(who="all"), body, OUR_ID, LABEL))


def test_unknown_words_line_and_empty_result():
    body = with_items(fixture("findings_all.json"), [])
    text = text_of(render_top(TopQuery(who="all", unknown=("абв",)), body, OUR_ID, LABEL))
    assert "не понял: абв" in text and "/help" in text
    assert "нет" in text


def test_line_format():
    body = fixture("findings_all.json")
    first = body["items"][0]  # Альфа, Telegram, фото, ×8,4, 9200
    first["interactionIndex"] = 5.1
    text = text_of(render_top(TopQuery(who="all", count=3), body, OUR_ID, LABEL))
    line = next(line for line in text.splitlines() if line.startswith("1."))
    assert "Альфа" in line
    assert f'<a href="{first["publicUrl"]}">' in line
    assert "×5,1" in line
    assert "9,2 тыс." in line
    assert "Telegram" in line and "фото" in line


@pytest.mark.parametrize("views, expected", [
    (0, "0"), (999, "999"), (1000, "1,0 тыс."), (9200, "9,2 тыс."), (999_949, "999,9 тыс."),
    (999_950, "1,0 млн"), (1_300_000, "1,3 млн"),
])
def test_views_format(views, expected):
    body = fixture("findings_all.json")
    body["items"][0]["views"] = views
    text = text_of(render_top(TopQuery(who="all", count=1), body, OUR_ID, LABEL))
    assert f"{expected} просм." in text


def test_html_is_escaped():
    body = fixture("findings_all.json")
    evil = body["items"][0]
    evil["institutionShortName"] = 'A<b>&"c'
    evil["publicUrl"] = 'https://example.org/?a=1&b="2"><script>'
    messages = render_top(TopQuery(who="all", count=1), body, OUR_ID, 'x<i>&"')
    text = text_of(messages)
    assert 'A&lt;b&gt;&amp;&quot;c' in text
    assert 'A<b>' not in text
    assert 'href="https://example.org/?a=1&amp;b=&quot;2&quot;&gt;&lt;script&gt;"' in text
    assert 'x&lt;i&gt;&amp;&quot;' in text


def test_non_http_link_is_not_rendered():
    body = fixture("findings_all.json")
    body["items"][0]["publicUrl"] = "javascript:alert(1)"
    text = text_of(render_top(TopQuery(who="all", count=1), body, OUR_ID, LABEL))
    assert "javascript" not in text


def test_long_output_is_split_on_lines():
    base = fixture("findings_all.json")["items"][0]
    items = []
    for number in range(300):
        item = copy.deepcopy(base)
        item["publicUrl"] = f"https://example.org/post/{number}"
        item["institutionShortName"] = "Очень длинное название " * 3
        items.append(item)
    body = with_items(fixture("findings_all.json"), items)
    messages = render_top(TopQuery(who="all", count=20), body, OUR_ID, LABEL)
    long_text = "\n".join(f"{n}. " + items[0]["institutionShortName"] * 3 for n in range(200))
    parts = split_message(long_text)
    assert len(parts) > 1
    assert all(len(part) <= 4096 for part in parts)
    assert "\n".join(parts) == long_text  # строки целы и ничего не потеряно
    assert all(len(m.text) <= 4096 for m in messages)


def test_split_message_edge_cases():
    assert split_message("") == [""]
    assert split_message("коротко") == ["коротко"]
    parts = split_message("x" * 9000, 4096)  # одна строка длиннее лимита режется жёстко
    assert [len(p) for p in parts] == [4096, 4096, 808]
    parts = split_message("a\nb\n" + "c" * 10, 5)
    assert all(len(p) <= 5 for p in parts)


def test_keyboard_only_on_last_part():
    base = fixture("findings_all.json")["items"][0]
    items = [copy.deepcopy(base) for _ in range(20)]
    body = with_items(fixture("findings_all.json"), items)
    for item in body["items"]:
        item["institutionShortName"] = "Ж" * 300
    messages = render_top(TopQuery(who="all", count=20), body, OUR_ID, LABEL)
    assert len(messages) > 1
    assert all(m.keyboard is None for m in messages[:-1])
    assert messages[-1].keyboard == top_keyboard(TopQuery(who="all", count=20))


QUERY_GRID = [
    TopQuery(who=who, institution=institution, platform=platform, period=period,
             count=count, suspicious=suspicious)
    for (who, institution), platform, period, count, suspicious in itertools.product(
        [("ours", None), ("all", None), ("institution", 7), ("institution", 2_147_483_647)],
        ["all", "telegram", "vk", "max", "rutube"],
        ["1d", "7d", "30d"],
        [None, 1, 3, 10, 20],
        [False, True],
    )
]


def test_callback_roundtrip_under_64_bytes():
    for query in QUERY_GRID:
        data = encode_callback(query)
        assert len(data.encode()) <= 64
        assert data.startswith("t|")
        assert decode_callback(data) == query


def test_callback_ignores_parse_artifacts():
    noisy = TopQuery(who="all", unknown=("абв",), candidates=(1, 2), suggestions=("МФТИ",))
    assert decode_callback(encode_callback(noisy)) == TopQuery(who="all")


@pytest.mark.parametrize("data", [
    "", "t", "t|", "s|a|a|w||0", "t|x|a|w||0", "t|i|a|w||0", "t|i0|a|w||0", "t|i-1|a|w||0",
    "t|a|z|w||0", "t|a|a|q||0", "t|a|a|w|0|0", "t|a|a|w|21|0", "t|a|a|w|03|0", "t|a|a|w||2",
    "t|a|a|w||0|extra", "t|a|a|w|х|0", "t|i99999999999999|a|w||0", "t|ο|a|w||0", "\x00",
])
def test_callback_garbage_is_none(data):
    assert decode_callback(data) is None


def labels(keyboard):
    return [[button["text"] for button in row] for row in keyboard]


def test_keyboard_marks_current_choice():
    query = TopQuery(who="all", platform="vk", period="30d", suspicious=True)
    keyboard = top_keyboard(query)
    marked = [button["text"] for row in keyboard for button in row if button["text"].startswith("✓")]
    assert len(marked) == 4
    assert "✓ Все вузы" in marked
    assert any("ВК" in text for text in marked)
    assert "✓ Месяц" in marked
    assert any("одозр" in text for text in marked)
    # Нажатие даёт запрос с изменённым полем и остальным прежним.
    by_text = {button["text"]: decode_callback(button["callback_data"])
               for row in keyboard for button in row}
    assert by_text["Наши"].who == "ours" and by_text["Наши"].platform == "vk"
    assert by_text["Сутки"].period == "1d" and by_text["Сутки"].who == "all"
    suspicious_button = next(b for row in keyboard for b in row if "одозр" in b["text"])
    assert decode_callback(suspicious_button["callback_data"]).suspicious is False
    for row in keyboard:
        for button in row:
            assert len(button["callback_data"].encode()) <= 64


def test_keyboard_defaults_and_institution_mode():
    keyboard = top_keyboard(TopQuery())
    assert "✓ Наши" in labels(keyboard)[0]
    assert "✓ Неделя" in [text for row in labels(keyboard) for text in row]
    assert any("Показать подозрительные" in text for row in labels(keyboard) for text in row)
    inst = top_keyboard(TopQuery(who="institution", institution=7))
    assert not any(text.startswith("✓") and text in ("✓ Наши", "✓ Все вузы")
                   for text in labels(inst)[0])
    to_all = decode_callback(inst[0][1]["callback_data"])
    assert to_all == TopQuery(who="all")


def test_period_label():
    as_of = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    assert period_label("1d", as_of) == "сутки до 16 окт"
    assert period_label("7d", as_of) == "10–16 окт"
    assert period_label("30d", as_of) == "17 сен – 16 окт"
    assert period_label("7d", datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)) == "27 апр – 3 мая"
    # Дата берётся по Москве: в 22:00 UTC там уже следующий день.
    assert period_label("1d", datetime(2026, 10, 16, 22, 0, tzinfo=timezone.utc)) == "сутки до 17 окт"


def test_our_week_stats_maps_legacy_to_institution():
    stats = our_week_stats(fixture("dashboard.json"), OUR_ID)
    assert stats == {
        "telegram": {"posts": 20, "views": 112000, "reactions": 3400},
        "vk": {"posts": 8, "views": 15000, "reactions": 900},
    }
    assert our_week_stats(fixture("dashboard.json"), 999) == {}


CURRENT = {"telegram": {"posts": 20, "views": 112000, "reactions": 3400},
           "vk": {"posts": 8, "views": 15000, "reactions": 900}}
PREVIOUS = {"telegram": {"posts": 10, "views": 117900, "reactions": 3000},
            "vk": {"posts": 8, "views": 15000, "reactions": 0}}


def test_week_without_previous():
    message = render_week(CURRENT, None, None, OUR_ID)
    assert isinstance(message, Message)
    assert "сравнение появится через неделю" in message.text
    assert "%" not in message.text
    assert "Telegram" in message.text and "112,0 тыс." in message.text
    assert "Прогноз" not in message.text


def test_week_changes():
    text = render_week(CURRENT, PREVIOUS, None, OUR_ID).text
    assert "+100 %" in text   # посты Telegram 10 -> 20
    assert "−5 %" in text     # просмотры Telegram 117900 -> 112000
    assert "0 %" in text      # посты ВК без изменений
    assert "появится" not in text


def test_week_forecast_line():
    forecast = fixture("forecast.json")
    text = render_week(CURRENT, PREVIOUS, forecast, OUR_ID).text
    assert "Прогноз места в М-Рейтинге (соцсети): ≈12-е ± 7" in text
    assert "ранний" not in text
    forecast["early"] = True
    text = render_week(CURRENT, PREVIOUS, forecast, OUR_ID).text
    assert "≈12-е ± 7 — ранний прогноз, месяц только начался" in text


def test_week_forecast_missing_pieces_are_omitted():
    forecast = fixture("forecast.json")
    assert "Прогноз" not in render_week(CURRENT, PREVIOUS, None, OUR_ID).text
    assert "Прогноз" not in render_week(CURRENT, PREVIOUS, forecast, 999).text
    forecast["rows"][0]["categories"]["social"]["rank"] = None
    assert "Прогноз" not in render_week(CURRENT, PREVIOUS, forecast, OUR_ID).text


def digest_args():
    return (fixture("findings_institution.json"), fixture("findings_all.json"))


def test_digest_others_exclude_us():
    ours, others = digest_args()
    messages = render_digest(ours, others, CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID)
    text = text_of(messages)
    head, _, rest = text.partition("Лучшие у других вузов")
    assert rest, "блок «у других» должен быть"
    block = rest.split("Неделя к неделе")[0]
    assert "Дельта" not in block
    assert len([line for line in block.splitlines() if line[:1].isdigit()]) == 10
    assert "Дельта" in head  # свои посты в блоке «наши»
    assert "Неделя к неделе" in text and "≈12-е ± 7" in text
    assert all(len(m.text) <= 4096 for m in messages)


def test_digest_does_not_mutate_inputs_and_is_stable():
    ours, others = digest_args()
    before = copy.deepcopy((ours, others))
    first = render_digest(ours, others, CURRENT, None, None, OUR_ID)
    assert (ours, others) == before
    assert first == render_digest(ours, others, CURRENT, None, None, OUR_ID)


def test_help_lists_all_word_kinds():
    text = render_help(alerts=False, admin=False)
    for word in ("кто", "площадка", "период", "сколько", "/top все тг", "/top мфти месяц",
                 "/week", "/digest", "/id"):
        assert word in text
    assert "/status" not in text and "/settings" not in text
    assert "/status" in render_help(alerts=True, admin=False)
    assert "/settings" not in render_help(alerts=True, admin=False)
    full = render_help(alerts=True, admin=True)
    assert "/status" in full and "/settings" in full
    assert "/settings" in render_help(alerts=False, admin=True)
