"""Тексты и кнопки бота: чистые функции без ввода-вывода."""
from __future__ import annotations

import copy
import itertools
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from telegram_bot.emoji import band, icon
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
    text_only,
    top_keyboard,
    week_label,
)
from telegram_bot.cover import CoverData
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


def post_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "<a href" in line]


def test_render_ours_flat_list_in_platform_order():
    body = fixture("findings_institution.json")
    text = text_of(render_top(TopQuery(), body, OUR_ID, LABEL))
    assert "Наши лучшие посты" in text and LABEL in text
    # Подзаголовков площадок нет: значок площадки — в каждой строке.
    for title in ("Telegram", "ВКонтакте", "MAX", "Rutube"):
        assert title not in text
    assert icon("max") not in text  # у площадки нет постов вовсе: строку не рисуем
    lines = post_lines(text)
    assert [line.split(" ", 1)[0] for line in lines] == [icon("telegram")] * 3 + [icon("vk")] * 2 + [icon("rutube")]
    # Название нашего вуза — только в шапке, в строках его нет.
    assert "Дельта" not in text
    # В Telegram четыре поста, показаны три; ВК и Rutube набрали меньше трёх.
    assert text.count("https://t.me/example/") == 3
    assert text.count("выше нормы только") == 2
    assert f"{icon('vk')} <i>выше нормы только 2</i>" in text
    assert f"{icon('rutube')} <i>выше нормы только 1</i>" in text
    assert text.index("выше нормы только 2") < text.index("https://example.org/rutube/")


def test_own_line_format():
    body = fixture("findings_institution.json")
    lines = post_lines(text_of(render_top(TopQuery(count=4, platform="telegram"), body, OUR_ID, LABEL)))
    assert lines == [
        f'{icon("telegram")} {icon("rank_1")} <a href="https://t.me/example/15">видео</a> · ×7,9 · 15,0 тыс. просм.',
        f'{icon("telegram")} {icon("rank_2")} <a href="https://t.me/example/16">фото</a> · ×5,1 · 9,2 тыс. просм.',
        f'{icon("telegram")} {icon("rank_3")} <a href="https://t.me/example/17">текст</a> · ×3,3 · 700 просм.',
        f'{icon("telegram")} 4. <a href="https://t.me/example/18">текст</a> · ×3,1 · 650 просм.',
    ]
    promo = post_lines(text_of(render_top(TopQuery(platform="vk"), body, OUR_ID, LABEL)))[1]
    assert promo.endswith(f"· {icon('promo')} продвижение")


def test_own_platform_without_posts_above_norm_is_one_line():
    body = fixture("findings_institution.json")
    # Индекса нет (мало истории для нормы) — пост не «выше нормы»: одна строка вместо трёх.
    for item in body["items"]:
        if item["platform"] == "rutube":
            item["interactionIndex"] = None
    text = text_of(render_top(TopQuery(), body, OUR_ID, LABEL))
    assert f"{icon('rutube')} <i>выше нормы постов нет</i>" in text
    assert "example.org/rutube" not in text
    # Явно запрошенная площадка без постов — та же строка.
    single = text_of(render_top(TopQuery(platform="max"), body, OUR_ID, LABEL))
    assert f"{icon('max')} <i>выше нормы постов нет</i>" in single
    inst = text_of(render_top(TopQuery(who="institution", institution=OUR_ID, platform="max"),
                              body, OUR_ID, LABEL))
    assert f"{icon('max')} <i>выше нормы постов нет</i>" in inst


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
    lines = post_lines(text)
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
    lines = post_lines(text)
    assert lines[0] == (f'{icon("rank_1")} <b>Альфа</b> · {icon("telegram")} '
                        f'<a href="{first["publicUrl"]}">фото</a> · ×5,1 · 9,2 тыс. просм.')
    assert lines[1] == (f'{icon("rank_2")} <b>Дельта</b> (мы) · {icon("telegram")} '
                        '<a href="https://t.me/example/2">видео</a> · ×7,9 · 15,0 тыс. просм.')
    assert "Telegram" not in text  # площадка — значком, не текстом


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
    for platform in ("telegram", "vk", "rutube"):
        for number in range(20):
            item = copy.deepcopy(base)
            item.update(platform=platform,
                        publicUrl=f"https://example.org/{platform}/{'длинный-путь-' * 6}{number}")
            items.append(item)
    body = with_items(fixture("findings_all.json"), items)
    query = TopQuery(count=20)
    messages = render_top(query, body, OUR_ID, LABEL)
    assert len(messages) > 1
    assert all(len(m.text) <= 4096 for m in messages)
    assert all(m.keyboard is None for m in messages[:-1])
    assert messages[-1].keyboard == top_keyboard(query)
    # Ни одна строка не порвана: теги внутри каждой строки парные, ссылок всего 60.
    lines = "\n".join(m.text for m in messages).split("\n")
    for line in lines:
        assert line.count("<b>") == line.count("</b>")
        assert line.count("<a ") == line.count("</a>")
    assert sum(line.count("<a ") for line in lines) == 60


def test_split_message_keeps_lines_whole():
    long_text = "\n".join(f"{n}. " + "Очень длинное название " * 9 for n in range(200))
    parts = split_message(long_text)
    assert len(parts) > 1
    assert all(len(part) <= 4096 for part in parts)
    assert "\n".join(parts) == long_text


def test_us_mark_only_when_institutions_are_mixed():
    body = fixture("findings_all.json")
    all_text = text_of(render_top(TopQuery(who="all"), body, OUR_ID, LABEL))
    assert "(мы)" in all_text
    ours_body = fixture("findings_institution.json")
    assert "мы)" not in text_of(render_top(TopQuery(), ours_body, OUR_ID, LABEL))
    single = TopQuery(who="institution", institution=OUR_ID)
    assert "мы)" not in text_of(render_top(single, ours_body, OUR_ID, LABEL))
    ours, others = digest_args()
    assert "мы)" not in text_of(render_digest(ours, others, CURRENT, None, None, OUR_ID))


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
        assert decode_callback(data) == (query, None)
        for author in (42, -1009999999999, -1001234567890, 10**19 - 1, -(10**19 - 1)):
            data = encode_callback(query, author)
            assert len(data.encode("utf-8")) <= 64
            assert decode_callback(data) == (query, author)


def test_callback_old_format_without_author_still_decodes():
    # Кнопки, отправленные до выкатки (шесть полей), работают как раньше.
    assert decode_callback("t|a|v|m||1") == (
        TopQuery(who="all", platform="vk", period="30d", suspicious=True), None)
    assert decode_callback("t|i7|a|w|20|0") == (TopQuery(who="institution", institution=7, count=20), None)
    assert encode_callback(TopQuery(who="all", platform="vk", period="30d", suspicious=True)) == "t|a|v|m||1"
    assert encode_callback(TopQuery(), 42) == "t|o|a|w||0|42"
    assert encode_callback(TopQuery(), -1001234567890) == "t|o|a|w||0|-1001234567890"


@pytest.mark.parametrize("author", [0, True, 10**19, -(10**19), "42"])
def test_callback_rejects_bad_author(author):
    with pytest.raises(ValueError):
        encode_callback(TopQuery(), author)


def test_callback_ignores_parse_artifacts():
    noisy = TopQuery(who="all", unknown=("абв",), candidates=(1, 2), suggestions=("МФТИ",))
    assert decode_callback(encode_callback(noisy)) == (TopQuery(who="all"), None)


@pytest.mark.parametrize("data", [
    "", "t", "t|", "s|a|a|w||0", "t|x|a|w||0", "t|i|a|w||0", "t|i0|a|w||0", "t|i-1|a|w||0",
    "t|a|z|w||0", "t|a|a|q||0", "t|a|a|w|0|0", "t|a|a|w|21|0", "t|a|a|w|03|0", "t|a|a|w||2",
    "t|a|a|w||0|extra", "t|a|a|w|х|0", "t|i99999999999999|a|w||0", "t|ο|a|w||0", "\x00",
    "t|a|a|w||0|", "t|a|a|w||0|0", "t|a|a|w||0|-0", "t|a|a|w||0|--5", "t|a|a|w||0|+5",
    "t|a|a|w||0|042", "t|a|a|w||0|12345678901234567890", "t|a|a|w||0|5|6", "t|a|a|w||0|٥",
])
def test_callback_garbage_is_none(data):
    assert decode_callback(data) is None


def labels(keyboard):
    return [[button["text"] for button in row] for row in keyboard]


def test_keyboard_marks_current_choice():
    query = TopQuery(who="all", platform="vk", period="30d", suspicious=True)
    keyboard = top_keyboard(query)
    assert labels(keyboard) == [
        ["⬜ Наши", "✅ Все вузы"],
        ["⬜ ТГ", "✅ ВК", "⬜ MAX", "⬜ Рутуб"],
        ["⬜ Сутки", "⬜ Неделя", "✅ Месяц"],
        ["✅ Подозрительные"],
    ]
    # Нажатие даёт запрос с изменённым полем и остальным прежним.
    by_text = {button["text"]: decode_callback(button["callback_data"])[0]
               for row in keyboard for button in row}
    assert by_text["⬜ Наши"].who == "ours" and by_text["⬜ Наши"].platform == "vk"
    assert by_text["⬜ Сутки"].period == "1d" and by_text["⬜ Сутки"].who == "all"
    assert by_text["✅ Подозрительные"].suspicious is False
    for row in keyboard:
        for button in row:
            assert len(button["callback_data"].encode()) <= 64


def test_keyboard_defaults_and_institution_mode():
    keyboard = top_keyboard(TopQuery())
    assert labels(keyboard) == [
        ["✅ Наши", "⬜ Все вузы"],
        ["✅ ТГ", "✅ ВК", "✅ MAX", "✅ Рутуб"],
        ["⬜ Сутки", "✅ Неделя", "⬜ Месяц"],
        ["⬜ Подозрительные"],
    ]
    assert decode_callback(keyboard[3][0]["callback_data"])[0].suspicious is True
    assert not any("✓" in text for row in labels(keyboard) for text in row)
    inst = top_keyboard(TopQuery(who="institution", institution=7))
    assert labels(inst)[0] == ["⬜ Наши", "⬜ Все вузы"]
    to_all = decode_callback(inst[0][1]["callback_data"])
    assert to_all == (TopQuery(who="all"), None)


def test_platform_row_toggles_between_all_and_one():
    # Пять кнопок не влезали в ширину телефона («…m», «…be»): четыре площадки,
    # «все» — когда отмечены все четыре; нажатие на выбранную возвращает все.
    def target(query, text):
        button = next(b for b in top_keyboard(query)[1] if b["text"] == text)
        return decode_callback(button["callback_data"])[0].platform

    everything = TopQuery(platform="all")
    assert target(everything, "✅ ТГ") == "telegram"
    assert target(everything, "✅ Рутуб") == "rutube"
    only_vk = TopQuery(platform="vk")
    assert target(only_vk, "✅ ВК") == "all"
    assert target(only_vk, "⬜ MAX") == "max"
    for query in (everything, only_vk):
        row = top_keyboard(query)[1]
        assert len(row) == 4
        # Ряд из четырёх кнопок вмещает около пяти знаков на кнопку.
        assert all(len(button["text"]) <= 7 for button in row)


def test_keyboard_carries_author():
    for author in (42, -1001234567890):
        keyboard = top_keyboard(TopQuery(who="institution", institution=2_147_483_647, count=20,
                                         suspicious=True), author)
        assert len(keyboard) == 4
        for button in (b for row in keyboard for b in row):
            assert len(button["callback_data"].encode("utf-8")) <= 64
            assert decode_callback(button["callback_data"])[1] == author
    messages = render_top(TopQuery(), fixture("findings_institution.json"), OUR_ID, LABEL, author=42)
    assert messages[-1].keyboard == top_keyboard(TopQuery(), 42)
    assert render_top(TopQuery(), fixture("findings_institution.json"), OUR_ID, LABEL)[-1].keyboard \
        == top_keyboard(TopQuery())


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


def week_text(*args, **kwargs) -> str:
    messages = render_week(*args, **kwargs)
    assert isinstance(messages, list) and all(isinstance(m, Message) for m in messages)
    return text_of(messages)


def test_week_without_previous():
    messages = render_week(CURRENT, None, None, OUR_ID)
    assert len(messages) == 1 and messages[0].photo is None
    text = messages[0].text
    assert text.startswith("<b>Неделя к неделе</b>")
    assert "сравнение появится через неделю" in text
    assert "%" not in text
    assert "✈️ <b>112,0 тыс.</b> просм." in text and band("band_week", "НЕДЕЛЯ") in text
    assert "Прогноз" not in text


def test_week_changes():
    text = week_text(CURRENT, PREVIOUS, None, OUR_ID)
    assert "+100 %" in text   # посты Telegram 10 -> 20
    assert "−5 %" in text     # просмотры Telegram 117900 -> 112000
    assert "0 %" in text      # посты ВК без изменений
    assert "появится" not in text


def test_week_forecast_line():
    forecast = fixture("forecast.json")
    text = week_text(CURRENT, PREVIOUS, forecast, OUR_ID)
    assert "Прогноз места в М-Рейтинге (соцсети): ≈12-е ± 7" in text
    assert "ранний" not in text
    forecast["early"] = True
    text = week_text(CURRENT, PREVIOUS, forecast, OUR_ID)
    assert "≈12-е ± 7 — ранний прогноз, месяц только начался" in text


def test_week_forecast_missing_pieces_are_omitted():
    forecast = fixture("forecast.json")
    assert "Прогноз" not in week_text(CURRENT, PREVIOUS, None, OUR_ID)
    assert "Прогноз" not in week_text(CURRENT, PREVIOUS, forecast, 999)
    forecast["rows"][0]["categories"]["social"]["rank"] = None
    assert "Прогноз" not in week_text(CURRENT, PREVIOUS, forecast, OUR_ID)


def digest_args():
    return (fixture("findings_institution.json"), fixture("findings_all.json"))


BANDS = ("🏆 <b>НАШИ ЛУЧШИЕ</b>", "🌐 <b>ДРУГИЕ ВУЗЫ</b>", "📅 <b>НЕДЕЛЯ</b>", "🔮 <b>ПРОГНОЗ</b>")


def test_digest_others_exclude_us():
    ours, others = digest_args()
    messages = render_digest(ours, others, CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID)
    text = text_of(messages)
    head, _, rest = text.partition(BANDS[1])
    assert rest, "блок «Другие вузы» должен быть"
    block = rest.split(BANDS[2])[0]
    assert "Дельта" not in block
    lines = post_lines(block)
    assert len(lines) == 10
    assert all("просм." not in line for line in lines)  # в «Других вузах» без просмотров
    assert lines[0] == (f'{icon("rank_1")} <b>Альфа</b> · {icon("telegram")} '
                        '<a href="https://t.me/example/1">фото</a> · ×8,4')
    assert any(line.endswith(f"· {icon('promo')} продвижение") for line in lines)
    assert "https://t.me/example/15" in head and "просм." in head  # свои посты в блоке «наши»
    assert "Дельта" not in head  # наш вуз в строках не повторяется
    assert "≈12-е ± 7" in text
    assert all(len(m.text) <= 4096 for m in messages)


def test_digest_bands_in_order():
    ours, others = digest_args()
    text = text_of(render_digest(ours, others, CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID))
    assert text.startswith("<b>Дайджест · 10–16 окт</b>")  # имя не передано — без него
    positions = [text.index(band) for band in BANDS]
    assert positions == sorted(positions)
    week = text[positions[2]:positions[3]]
    assert "20 постов (+100 %)" in week and "<b>Всего:</b>" in week
    assert "Неделя к неделе" not in text  # заголовок заменён лентой
    assert text[positions[3]:].strip().endswith("≈12-е ± 7")
    # Прогноза нет — нет и ленты «ПРОГНОЗ».
    bare = text_of(render_digest(ours, others, CURRENT, None, None, OUR_ID))
    assert BANDS[3] not in bare and all(band in bare for band in BANDS[:3])
    assert "сравнение появится через неделю" in bare


def test_digest_does_not_mutate_inputs_and_is_stable():
    ours, others = digest_args()
    before = copy.deepcopy((ours, others))
    first = render_digest(ours, others, CURRENT, None, None, OUR_ID)
    assert (ours, others) == before
    assert first == render_digest(ours, others, CURRENT, None, None, OUR_ID)


# --- обложка: подпись-шапка --------------------------------------------------

CAPTION_LIMIT = 1024


def cover_data(title: str = "Дельта") -> CoverData:
    return CoverData(title, f"{LABEL} · просмотры за неделю", [])


def test_digest_with_cover_starts_with_caption_header():
    ours, others = digest_args()
    messages = render_digest(ours, others, CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID,
                             cover=cover_data())
    assert messages[0] == Message("<b>Дайджест · Дельта · 10–16 окт</b>")  # картинку рисует вызывающий
    rest = text_of(messages[1:])
    assert "Дайджест" not in rest                        # шапка не повторяется в тексте
    assert rest.startswith(BANDS[0])
    assert all(band in rest for band in BANDS)
    plain = text_of(render_digest(ours, others, CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID))
    assert plain.split("\n", 2)[2] == rest              # тело то же, что без обложки


def test_digest_text_only_header_names_the_institution():
    ours, others = digest_args()
    named = render_digest(ours, others, CURRENT, PREVIOUS, None, OUR_ID, name="Дельта <&>")
    assert named[0].text.startswith("<b>Дайджест · Дельта &lt;&amp;&gt; · 10–16 окт</b>\n")
    assert text_of(named).count("Дельта") == 1
    # С обложкой имя уже в подписи; тело не повторяет шапку и имя.
    covered = render_digest(ours, others, CURRENT, PREVIOUS, None, OUR_ID,
                            cover=cover_data(), name="Дельта")
    assert covered[0] == Message("<b>Дайджест · Дельта · 10–16 окт</b>")
    assert "Дайджест" not in text_of(covered[1:])
    assert text_of(covered[1:]) == text_of(named).split("\n", 2)[2]
    # Нет ни имени, ни недели — прежний заголовок.
    assert render_digest(ours, others, CURRENT, None, None, OUR_ID, name=None)[0].text \
        .startswith("<b>Дайджест · 10–16 окт</b>")


def test_week_with_cover_starts_with_caption_header():
    messages = render_week(CURRENT, PREVIOUS, fixture("forecast.json"), OUR_ID,
                           cover=cover_data(), label=LABEL)
    assert messages[0] == Message("<b>Неделя к неделе · Дельта · 10–16 окт</b>")
    rest = text_of(messages[1:])
    assert "Неделя к неделе" not in rest
    assert rest.startswith(band("band_week", "НЕДЕЛЯ")) and "20 постов (+100 %)" in rest
    assert band("band_forecast", "ПРОГНОЗ") in rest and "≈12-е ± 7" in rest
    no_label = render_week(CURRENT, PREVIOUS, None, OUR_ID, cover=cover_data())
    assert no_label[0].text == "<b>Неделя к неделе · Дельта</b>"


def utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2  # так считает длину Telegram


@pytest.mark.parametrize("name", ["Я" * 300, "&" * 300, "<b>" * 150, "😀" * 600],
                         ids=["letters", "amps", "tags", "astral"])
def test_caption_fits_telegram_limit(name):
    ours, others = digest_args()
    captions = [
        render_digest(ours, others, CURRENT, None, None, OUR_ID, cover=cover_data(name))[0].text,
        render_week(CURRENT, None, None, OUR_ID, cover=cover_data(name), label=LABEL)[0].text,
    ]
    for caption in captions:
        assert utf16(caption) <= CAPTION_LIMIT
        assert caption.startswith("<b>") and caption.endswith(" · 10–16 окт</b>")
        assert caption.count("<b>") == 1                  # имя экранировано
    if name == "Я" * 300:
        assert name in captions[0]                        # влезает — не режем
    else:
        assert "…" in captions[0]                         # не влезает — обрезано с «…»


def test_text_only_merges_caption_into_first_text():
    ours, others = digest_args()
    messages = render_digest(ours, others, CURRENT, PREVIOUS, None, OUR_ID, cover=cover_data())
    drawn = [Message(messages[0].text, photo=b"png"), *messages[1:]]
    merged = text_only(drawn)
    assert all(m.photo is None for m in merged)
    assert merged[0].text == messages[0].text + "\n\n" + messages[1].text
    assert merged[1:] == messages[2:]
    # Не влезает в одно сообщение — шапка уходит отдельным текстом.
    long = [Message("<b>шапка</b>", photo=b"png"), Message("x" * 4096)]
    assert text_only(long) == [Message("<b>шапка</b>"), Message("x" * 4096)]
    assert text_only([Message("<b>шапка</b>", photo=b"png")]) == [Message("<b>шапка</b>")]


def test_week_label_from_as_of():
    assert week_label({"asOf": "2026-10-16T12:00:00+00:00"}) == LABEL
    assert week_label({}) is None and week_label({"asOf": "мусор"}) is None


def test_help_lists_all_word_kinds():
    text = render_help(alerts=False, admin=False)
    for word in ("кто", "площадка", "период", "сколько", "/top все тг", "/top мфти месяц",
                 "/week", "/digest", "/id", "мфти", "telegram"):
        assert word in text
    assert "/status" not in text and "/settings" not in text
    assert "/status" in render_help(alerts=True, admin=False)
    assert "/settings" not in render_help(alerts=True, admin=False)
    full = render_help(alerts=True, admin=True)
    assert "/status" in full and "/settings" in full
    assert "/settings" in render_help(alerts=False, admin=True)


def test_help_uses_bands_and_bold_commands():
    text = render_help(alerts=False, admin=False)
    assert band("band_ours", "ПОСТЫ") in text and band("band_week", "НЕДЕЛЯ") in text
    for command in ("/top", "/week", "/digest", "/id"):
        assert f"<b>{command}</b>" in text
    assert "<code>/top все тг</code>" in text and "<code>/top мфти месяц</code>" in text
    for slot in ("logo", "telegram", "vk", "max", "rutube"):
        assert icon(slot) in text


def test_help_server_block_gated():
    plain = render_help(alerts=False, admin=False)
    assert "СЕРВЕР" not in plain and "/status" not in plain and "/settings" not in plain
    alerts_only = render_help(alerts=True, admin=False)
    assert band("alert_urgent", "СЕРВЕР") in alerts_only
    assert "<b>/status</b>" in alerts_only and "/settings" not in alerts_only
    admin_only = render_help(alerts=False, admin=True)
    assert band("alert_urgent", "СЕРВЕР") in admin_only
    assert "<b>/settings</b>" in admin_only and "/status" not in admin_only


@pytest.mark.parametrize("alerts,admin", [(False, False), (True, False), (False, True), (True, True)])
def test_help_html_is_balanced(alerts, admin):
    text = render_help(alerts=alerts, admin=admin)
    stack = []
    for match in re.finditer(r"<(/?)([a-z-]+)[^<>]*>", text):
        closing, name = match.groups()
        if closing:
            assert stack and stack.pop() == name
        else:
            stack.append(name)
    assert not stack
    bare = re.sub(r"<[^<>]*>", "", text)
    assert "<" not in bare and ">" not in bare and "&" not in bare


def test_week_change_is_capped_like_the_cover():
    text = render_week({"telegram": {"posts": 20, "views": 112_000, "reactions": 3400}},
                       {"telegram": {"posts": 1, "views": 10, "reactions": 1}}, None, OUR_ID)[0].text
    assert "(>+999 %)" in text and "1119900" not in text


def test_week_lines_have_platform_icons_and_plurals():
    text = render_week({"telegram": {"posts": 21, "views": 900, "reactions": 1},
                        "vk": {"posts": 13, "views": 5, "reactions": 3}}, None, None, OUR_ID)[0].text
    assert "✈️ <b>900</b> просм. · 21 пост · 1 реакция" in text
    assert "🔵 <b>5</b> просм. · 13 постов · 3 реакции" in text
