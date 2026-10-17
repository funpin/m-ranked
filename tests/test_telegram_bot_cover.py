"""Обложка бота: данные строк, плашки и раскладка зон (без рисования)."""
from __future__ import annotations

import random

import pytest

from telegram_bot import cover
from telegram_bot.cover import (
    BAR_MIN,
    BAR_SHARE,
    HEIGHT,
    LOGO_SIZE,
    MARGIN,
    TITLE_MAX,
    TITLE_MIN,
    WIDTH,
    Box,
    CoverData,
    Row,
    badge,
    cover_rows,
    layout,
    pil_measure,
)

PLATFORMS = ("telegram", "vk", "max", "rutube")
SUBTITLE = "просмотры за неделю · 10–16 окт"
CHART_PREFIXES = ("icon:", "bar:", "label:", "badge:")


# --- данные -------------------------------------------------------------------

def test_rows_mapping() -> None:
    current = {"vk": {"views": 6400}, "telegram": {"views": 2100}}
    previous = {"max": {"views": 900}, "vk": {"views": 6000}}
    assert cover_rows(current, previous) == [
        Row("vk", 6400, 6000), Row("telegram", 2100, None), Row("max", None, 900)]
    # Есть в текущей сводке с нулём — строка «0», а не «нет данных».
    assert cover_rows({"rutube": {"views": 0}}, None) == [Row("rutube", 0, None)]
    assert cover_rows({"rutube": {"views": 0}}, {"rutube": {"views": 7}}) == [
        Row("rutube", 0, 7)]
    # Другой показатель и пустые сводки.
    assert cover_rows({"vk": {"views": 1, "posts": 3}}, None, key="posts") == [Row("vk", 3, None)]
    assert cover_rows({}, None) == []


def test_rows_order_ties_follow_platform_order() -> None:
    current = {p: {"views": 5} for p in reversed(PLATFORMS)}
    assert [row.platform for row in cover_rows(current, None)] == list(PLATFORMS)
    rows = cover_rows({"vk": {"views": 0}}, {"rutube": {"views": 1}, "telegram": {"views": 1}})
    assert rows == [Row("vk", 0, None), Row("telegram", None, 1), Row("rutube", None, 1)]


def test_badge() -> None:
    assert badge(112, 100) == "▲ 12 %"
    assert badge(95, 100) == "▼ 5 %"
    assert badge(1000, 999) == "≈ 0 %"
    assert badge(5, 0) is None
    assert badge(5, None) is None
    assert badge(None, 5) is None
    assert badge(0, 100) == "▼ 100 %"
    assert badge(1099, 100) == "▲ 999 %"
    assert badge(1005, 1000) == "▲ 1 %"  # 0,5 % округляется вверх, как в тексте бота


# --- раскладка: общие проверки ---------------------------------------------------

def _inner() -> Box:
    return Box(MARGIN, MARGIN, WIDTH - 2 * MARGIN, HEIGHT - 2 * MARGIN)


def _own_bar(name: str, other: str) -> bool:
    """Подпись и плашка могут лежать внутри своей полосы — это не наложение."""
    kind, _, platform = name.partition(":")
    other_kind, _, other_platform = other.partition(":")
    return platform == other_platform and kind in {"label", "badge"} and other_kind == "bar"


def assert_zones(data: CoverData, measure=pil_measure) -> cover.Layout:
    result = layout(data, measure)
    inner = _inner()
    assert result.canvas == Box(0, 0, WIDTH, HEIGHT)
    assert result.logo.inside(inner)
    assert (result.logo.w, result.logo.h) == LOGO_SIZE
    assert not result.logo.intersects(result.header)
    assert not result.logo.intersects(result.chart)
    assert not result.header.intersects(result.chart)
    assert result.chart.w == WIDTH - 2 * MARGIN
    for name, box in result.items.items():
        assert box.w >= 0 and box.h > 0, name
        assert box.inside(inner), (name, box)
        if name.startswith(CHART_PREFIXES):
            assert box.inside(result.chart), (name, box)
        else:
            assert name in {"title", "subtitle"}, name
            assert box.inside(result.header), (name, box)
    names = sorted(result.items)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            a, b = result.items[first], result.items[second]
            if _own_bar(first, second) or _own_bar(second, first):
                inner_box, bar = (a, b) if first.startswith(("label", "badge")) else (b, a)
                assert inner_box.inside(bar) or not inner_box.intersects(bar), (first, second)
                continue
            assert not a.intersects(b), (first, a, second, b)
    # Что нарисовано, то и подписано.
    assert set(result.texts) == {n for n in result.items if not n.startswith(("icon:", "bar:"))}
    return result


def _random_title(rng: random.Random) -> str:
    alphabet = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ" \
               "abcdefghijklmnopqrstuvwxyzMWЖШЩ0123456789«»№-—.,()"
    length = rng.randint(1, 120)
    chars = [" " if rng.random() < 0.12 else rng.choice(alphabet) for _ in range(length)]
    return "".join(chars).strip() or "Ж"


def _random_value(rng: random.Random) -> int:
    return rng.choice((0, 1, rng.randint(2, 99), rng.randint(100, 99_999),
                       rng.randint(100_000, 10 ** 9), 10 ** 9))


def _random_data(seed: int) -> CoverData:
    rng = random.Random(seed)
    current: dict[str, dict[str, int]] = {}
    previous: dict[str, dict[str, int]] = {}
    for platform in rng.sample(PLATFORMS, rng.randint(0, 4)):
        where = rng.random()
        if where < 0.8:
            current[platform] = {"views": _random_value(rng)}
        if where >= 0.8 or rng.random() < 0.6:
            previous[platform] = {"views": _random_value(rng)}
    return CoverData(_random_title(rng), SUBTITLE, cover_rows(current, previous or None))


LONG_NAME = ("Федеральное государственное автономное образовательное учреждение высшего "
             "образования Московский физико-технический институт национальный "
             "исследовательский университет имени")[:200]

EXTREMES = {
    "long-title-200": CoverData(LONG_NAME.ljust(200, "я"), SUBTITLE,
                                [Row("vk", 6400, 6000), Row("telegram", 2100, None)]),
    "no-short-name": CoverData("Московский физико-технический институт (национальный "
                               "исследовательский университет)", SUBTITLE,
                               [Row("telegram", 912, 1000)]),
    "one-word-200": CoverData("Ж" * 200, "x" * 300, [Row("max", 5, 4)]),
    "one-row": CoverData("МФТИ", SUBTITLE, [Row("rutube", 77, None)]),
    "four-rows": CoverData("МФТИ", SUBTITLE, [Row(p, v, v - 1) for p, v in
                                              zip(PLATFORMS, (9_200_000, 999_999, 1_250, 7))]),
    "all-zero": CoverData("МФТИ", SUBTITLE, [Row(p, 0, 0) for p in PLATFORMS]),
    "mixed": CoverData("МФТИ", SUBTITLE, [Row("vk", 10 ** 9, 1), Row("telegram", 1, 1),
                                         Row("max", 0, 5), Row("rutube", None, 3)]),
    "plus-999": CoverData("МФТИ", SUBTITLE, [Row(p, 999_999 if i == 0 else 1099, 100)
                                            for i, p in enumerate(PLATFORMS)]),
    "minus-999": CoverData("МФТИ", SUBTITLE, [Row(p, 1, 1000) for p in PLATFORMS]),
    "no-rows": CoverData("МФТИ", SUBTITLE, []),
    "all-no-data": CoverData("МФТИ", SUBTITLE, [Row(p, None, 5) for p in PLATFORMS]),
    "empty-title": CoverData("", "", [Row("vk", 3, None)]),
}


@pytest.mark.parametrize("name", sorted(EXTREMES))
def test_zones_never_overlap_extremes(name: str) -> None:
    assert_zones(EXTREMES[name])


@pytest.mark.parametrize("seed", range(290))
def test_zones_never_overlap(seed: int) -> None:
    assert_zones(_random_data(seed))


def test_header_and_logo_geometry() -> None:
    result = layout(EXTREMES["four-rows"], pil_measure)
    logo_x = WIDTH - MARGIN - LOGO_SIZE[0]
    assert result.logo.x == logo_x
    assert result.header.x == MARGIN
    assert result.header.w == WIDTH - 2 * MARGIN - LOGO_SIZE[0] - 32
    assert result.header.y <= result.logo.y
    assert result.logo.y + result.logo.h <= result.header.y + result.header.h
    assert result.chart.y >= result.header.y + result.header.h + 24
    assert result.chart.y + result.chart.h == HEIGHT - MARGIN
    assert result.items["subtitle"].y >= result.items["title"].y + result.items["title"].h


def test_rows_centred_with_equal_step() -> None:
    for count in range(1, 5):
        data = CoverData("МФТИ", SUBTITLE, [Row(p, 100, None) for p in PLATFORMS[:count]])
        result = layout(data, pil_measure)
        icons = [result.items[f"icon:{p}"] for p in PLATFORMS[:count]]
        steps = {b.y - a.y for a, b in zip(icons, icons[1:])}
        assert len(steps) <= 1
        top = icons[0].y - result.chart.y
        bottom = result.chart.y + result.chart.h - (icons[-1].y + icons[-1].h)
        assert abs(top - bottom) <= 1
        for icon in icons:
            assert (icon.w, icon.h) == (44, 44)
            assert icon.x == result.chart.x


def test_text_boxes_hold_real_font_lines() -> None:
    """Высоты текстовых рамок покрывают строку шрифта (ascent + descent)."""
    for key, sizes in (("title", range(TITLE_MIN, TITLE_MAX + 1)),
                       ("subtitle", (cover.SUBTITLE_SIZE, cover.LABEL_SIZE)),
                       ("number", (cover.NUMBER_SIZE, cover.BADGE_SIZE))):
        for size in sizes:
            ascent, descent = cover.load_font(key, size).getmetrics()
            assert ascent + descent <= cover.line_height(key, size), (key, size)
    assert cover.line_height("number", cover.NUMBER_SIZE) <= cover.BAR_HEIGHT
    assert cover.line_height("number", cover.BADGE_SIZE) <= cover.BADGE_HEIGHT


# --- название -----------------------------------------------------------------------

def _title_layout(title: str) -> cover.Layout:
    return assert_zones(CoverData(title, SUBTITLE, [Row("vk", 10, None)]))


def test_title_shrinks_then_ellipsis() -> None:
    width = WIDTH - 2 * MARGIN - LOGO_SIZE[0] - 32

    short = _title_layout("МФТИ")
    assert short.title_size == TITLE_MAX and short.title == "МФТИ"

    middle = "Санкт-Петербургский университет"
    assert pil_measure(middle, "title", TITLE_MAX) > width
    assert pil_measure(middle, "title", TITLE_MIN) <= width
    shrunk = _title_layout(middle)
    assert TITLE_MIN <= shrunk.title_size < TITLE_MAX
    assert shrunk.title == middle
    assert shrunk.items["title"].w == pil_measure(middle, "title", shrunk.title_size)

    long = _title_layout(LONG_NAME)
    assert long.title_size == TITLE_MIN
    assert long.title.endswith("…")
    head = long.title[:-1]
    assert LONG_NAME.startswith(head) and LONG_NAME[len(head)] == " "  # обрезано по слову
    assert pil_measure(long.title, "title", TITLE_MIN) <= width
    # Следующее слово уже не влезло бы.
    next_space = LONG_NAME.find(" ", len(head) + 1)
    longer = LONG_NAME[:next_space if next_space > 0 else len(LONG_NAME)] + "…"
    assert pil_measure(longer, "title", TITLE_MIN) > width


def test_single_long_word_cut_by_characters() -> None:
    result = _title_layout("Ж" * 200)
    assert result.title_size == TITLE_MIN
    assert result.title.endswith("…") and set(result.title[:-1]) == {"Ж"}
    assert 1 < len(result.title) < 200


# --- полосы ------------------------------------------------------------------------

def _track(result: cover.Layout) -> tuple[int, int]:
    x = result.chart.x + cover.ICON_SIZE + cover.ICON_GAP
    return x, result.chart.x + result.chart.w - x


def test_longest_bar_is_70_percent() -> None:
    result = assert_zones(EXTREMES["four-rows"])
    track_x, track_w = _track(result)
    bars = {p: result.items[f"bar:{p}"] for p in PLATFORMS}
    assert all(bar.x == track_x for bar in bars.values())
    assert abs(bars["telegram"].w - BAR_SHARE * track_w) <= 1
    assert bars["telegram"].w <= BAR_SHARE * track_w
    # Линейный масштаб от максимума.
    assert bars["vk"].w == pytest.approx(bars["telegram"].w * 999_999 / 9_200_000, abs=1)
    assert all(bar.h == cover.BAR_HEIGHT for bar in bars.values())


def test_tiny_bar_min_10px() -> None:
    result = assert_zones(EXTREMES["mixed"])
    assert result.items["bar:telegram"].w == BAR_MIN


def test_zero_has_no_bar() -> None:
    result = assert_zones(EXTREMES["mixed"])
    assert "bar:max" not in result.items
    assert result.texts["label:max"] == "0"
    assert "bar:rutube" not in result.items
    assert result.texts["label:rutube"] == "нет данных"
    assert "badge:rutube" not in result.items
    zeros = assert_zones(EXTREMES["all-zero"])
    assert not [name for name in zeros.items if name.startswith("bar:")]


def test_labels_right_of_bar_with_numbers_and_badges() -> None:
    data = CoverData("МФТИ", SUBTITLE, [Row("vk", 6400, 6000), Row("telegram", 2100, None)])
    result = assert_zones(data)
    assert result.texts["label:vk"] == "6,4 тыс."
    assert result.texts["badge:vk"] == "▲ 7 %"
    assert "badge:telegram" not in result.items
    bar, label = result.items["bar:telegram"], result.items["label:telegram"]
    assert label.x == bar.x + bar.w + 16
    assert label.y == bar.y and label.h == bar.h
    assert label.w == pil_measure("2,1 тыс.", "number", cover.NUMBER_SIZE)
    # Плашка — справа от числа; при 70 % подпись с плашкой влезает справа.
    vk_label, vk_badge = result.items["label:vk"], result.items["badge:vk"]
    assert vk_label.x == result.items["bar:vk"].x + result.items["bar:vk"].w + 16
    assert vk_badge.x == vk_label.x + vk_label.w + 12
    assert vk_badge.w == pil_measure("▲ 7 %", "number", cover.BADGE_SIZE) + 2 * cover.BADGE_PAD


def _big(width: int):
    def measure(text: str, font_key: str, size: int) -> int:
        return width if font_key == "number" else pil_measure(text, font_key, size)
    return measure


def test_label_moves_inside_when_no_room() -> None:
    data = CoverData("МФТИ", SUBTITLE, [Row("vk", 1000, None), Row("max", 10, None)])
    result = assert_zones(data, _big(400))
    assert result.items["label:vk"].inside(result.items["bar:vk"])
    assert result.items["label:vk"].x == result.items["bar:vk"].x + 24
    assert result.items["label:vk"].w == 400
    # Короткой полосе места справа хватает.
    max_bar, max_label = result.items["bar:max"], result.items["label:max"]
    assert max_label.x == max_bar.x + max_bar.w + 16


def test_badge_dropped_when_no_room_anywhere() -> None:
    data = CoverData("МФТИ", SUBTITLE, [Row("vk", 1000, 900), Row("max", 999, 900)])
    result = assert_zones(data, _big(700))
    for platform in ("vk", "max"):
        assert f"label:{platform}" in result.items
        assert f"badge:{platform}" not in result.items
        assert f"badge:{platform}" not in result.texts
        assert result.items[f"label:{platform}"].w == 700
    assert result.items["label:vk"].inside(result.items["bar:vk"])


def test_impossible_label_is_clipped_not_overlapping() -> None:
    data = CoverData("МФТИ", SUBTITLE, [Row("vk", 1000, None), Row("max", 0, None)])
    assert_zones(data, _big(5000))


def test_more_than_four_rows_are_cut() -> None:
    rows = [Row(p, 10, None) for p in PLATFORMS] + [Row("extra", 1, None)]
    result = assert_zones(CoverData("МФТИ", SUBTITLE, rows))
    assert "icon:extra" not in result.items


# --- шрифты ------------------------------------------------------------------------

def test_review_focus_glyphs() -> None:
    text = "«Ёжик» №1 Café ▲▼…"
    for key in ("title", "subtitle", "number"):
        for ch in text:
            assert pil_measure(ch, key, 40) > 0, (key, ch)
    # Настоящие глифы, не «нет символа»: текст шапки — в Geologica и Onest,
    # числа и ▲▼ плашек — в JetBrains Mono (решение Task 1, без треугольников).
    for key, chars in (("title", "«Ёжик»№1Café…"), ("subtitle", "«Ёжик»№1Café…"),
                       ("number", "«Ёжик»№1Café▲▼…0123456789,.%≈")):
        font = cover.load_font(key, 40)
        missing = font.getmask("\U0010FFFD")
        for ch in chars:
            mask = font.getmask(ch)
            assert mask.getbbox() is not None, (key, ch)
            assert (mask.size, bytes(mask)) != (missing.size, bytes(missing)), (key, ch)


def test_fonts_use_named_instances_and_are_cached() -> None:
    title = cover.load_font("title", 50)
    assert title is cover.load_font("title", 50)
    assert title.get_variation_axes()  # переменный шрифт, начертание выбрано по имени
    # Geologica по умолчанию Thin: Bold заметно шире.
    from PIL import ImageFont
    thin = ImageFont.truetype(str(cover.FONTS / "Geologica-Variable.ttf"), 50)
    assert title.getlength("Ёжик МФТИ") > thin.getlength("Ёжик МФТИ")


def test_layout_is_fast() -> None:
    import time
    started = time.perf_counter()
    for seed in range(300, 400):
        layout(_random_data(seed), pil_measure)
    assert time.perf_counter() - started < 1.0
