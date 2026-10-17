"""Обложка дайджеста и /week: данные строк и раскладка зон.

Раскладка — чистое вычисление «данные → прямоугольники»: ширина текста
приходит через `measure`, высоты строк — из констант, которые тест сверяет с
метриками настоящих шрифтов. Рисование идёт отдельно, строго по этим
прямоугольникам, поэтому «зоны не пересекаются» проверяется без картинки.

Холст 1280×640 с полями 64: шапка (название и подзаголовок) слева сверху,
знак m-ranked справа на одной линии с ней, под ними — график на всю ширину,
по строке на площадку: значок, полоса, подпись (число и плашка ▲/▼).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import ImageFont

from .render import PLATFORM_ORDER, format_count

WIDTH = 1280
HEIGHT = 640
MARGIN = 64
LOGO_SIZE = (200, 117)
TITLE_MAX = 64
TITLE_MIN = 44
TITLE_STEP = 2
BAR_SHARE = 0.70
BAR_MIN = 10

HEADER_TOP = 52        # верх шапки по макету v2; текст начинается от поля 64
HEADER_HEIGHT = 132
HEADER_GAP = 32        # зазор шапка — логотип
CHART_GAP = 30         # зазор шапка — график
SUBTITLE_SIZE = 26
NUMBER_SIZE = 30
LABEL_SIZE = 26        # «нет данных» — шрифтом подзаголовка
BADGE_SIZE = 22
BADGE_PAD = 12         # поля плашки слева и справа от текста
BADGE_HEIGHT = 32
ICON_SIZE = 44
ICON_GAP = 20
BAR_HEIGHT = 44
ROW_GAP = 22
MAX_ROWS = 4
LABEL_GAP = 16         # полоса — подпись снаружи
LABEL_INSET = 24       # отступ подписи внутри полосы
BADGE_GAP = 12         # число — плашка
NO_DATA = "нет данных"
ELLIPSIS = "…"

ASSETS = Path(__file__).resolve().parent / "assets"
FONTS = ASSETS / "fonts"
# Переменные шрифты Google Fonts; начертание выбирается по имени (у Geologica
# по умолчанию Thin). JetBrains Mono моноширинный: ширина Medium и Bold одна,
# поэтому плашку (▲/▼ — глифы этого шрифта) можно мерить ключом "number".
FONT_FILES = {
    "title": ("Geologica-Variable.ttf", "Bold"),
    "subtitle": ("Onest-Variable.ttf", "Regular"),
    "number": ("JetBrainsMono-Variable.ttf", "Medium"),
}
# Высота строки (ascent + descent) в долях кегля, с запасом над метриками
# шрифтов; test_text_boxes_hold_real_font_lines сверяет с настоящими.
LINE_RATIO = {"title": 1.28, "subtitle": 1.32, "number": 1.37}

Measure = Callable[[str, str, int], int]


# --- данные -------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    platform: str
    value: int | None      # None — аккаунт есть, данных за неделю нет
    previous: int | None


@dataclass(frozen=True)
class CoverData:
    title: str             # уже выбранное имя: shortName, иначе полное
    subtitle: str
    rows: list[Row]


def _order(platform: str) -> int:
    return PLATFORM_ORDER.index(platform) if platform in PLATFORM_ORDER else len(PLATFORM_ORDER)


def cover_rows(current: dict[str, dict[str, int]], previous: dict[str, dict[str, int]] | None,
               key: str = "views") -> list[Row]:
    """Площадка есть у вуза, если она есть в текущей сводке или в прошлом снимке.

    Есть в текущей (даже с нулём) — значение; только в прошлом — «нет данных».
    Порядок — по убыванию значения, «нет данных» в конце, равные — в порядке
    площадок.
    """
    previous = previous or {}
    rows = []
    for platform in set(current) | set(previous):
        value = current[platform].get(key) if platform in current else None
        before = previous[platform].get(key) if platform in previous else None
        rows.append(Row(platform, value, before))
    rows.sort(key=lambda row: (row.value is None, -(row.value or 0), _order(row.platform),
                               row.platform))
    return rows


def badge(value: int | None, previous: int | None) -> str | None:
    """«▲ 12 %» / «▼ 5 %» / «≈ 0 %»; без прошлого значения (или при нуле) — нет."""
    if value is None or previous is None or previous <= 0:
        return None
    percent = (value - previous) * 100 / previous
    rounded = int(abs(percent) + 0.5)
    if rounded == 0:
        return "≈ 0 %"
    return f"{'▲' if percent > 0 else '▼'} {rounded} %"


# --- прямоугольники -----------------------------------------------------------

@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: Box) -> bool:
        """Общая площадь больше нуля (касание краями — не пересечение)."""
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def inside(self, other: Box) -> bool:
        return (other.x <= self.x and self.right <= other.right
                and other.y <= self.y and self.bottom <= other.bottom)


@dataclass(frozen=True)
class Layout:
    canvas: Box
    header: Box
    logo: Box
    chart: Box
    title: str
    title_size: int
    items: dict[str, Box]
    # Текст каждого текстового элемента из items (title, subtitle, label:*, badge:*):
    # рисование берёт строки отсюда, а не собирает их заново.
    texts: dict[str, str] = field(default_factory=dict)


def line_height(font_key: str, size: int) -> int:
    return math.ceil(size * LINE_RATIO[font_key])


# --- шрифты -------------------------------------------------------------------

@lru_cache(maxsize=32)
def load_font(font_key: str, size: int) -> ImageFont.FreeTypeFont:
    """Шрифт с выбранным начертанием; кэш по (ключ, кегль)."""
    name, instance = FONT_FILES[font_key]
    font = ImageFont.truetype(str(FONTS / name), size)
    font.set_variation_by_name(instance)
    return font


def pil_measure(text: str, font_key: str, size: int) -> int:
    """Ширина строки в px настоящим шрифтом (вверх до целого)."""
    return math.ceil(load_font(font_key, size).getlength(text))


# --- раскладка ----------------------------------------------------------------

def _fit(text: str, font_key: str, size: int, width: int, measure: Measure) -> str:
    """Строка как есть, если влезает; иначе обрезка по слову с «…»; если и
    первое слово не влезает — по символам."""
    if measure(text, font_key, size) <= width:
        return text
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    for cut in reversed(spaces):
        head = text[:cut].rstrip(" ,.;:-–—")
        if head and measure(head + ELLIPSIS, font_key, size) <= width:
            return head + ELLIPSIS
    low, high = 0, len(text)          # самая длинная приставка, которая влезает
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ELLIPSIS, font_key, size) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ELLIPSIS if low else ""


def _title(text: str, width: int, measure: Measure) -> tuple[str, int]:
    for size in range(TITLE_MAX, TITLE_MIN - 1, -TITLE_STEP):
        if measure(text, "title", size) <= width:
            return text, size
    return _fit(text, "title", TITLE_MIN, width, measure), TITLE_MIN


def _bar_width(value: int | None, peak: int, longest: int) -> int:
    if not value or peak <= 0:
        return 0
    return max(BAR_MIN, round(value * longest / peak))


def _label(row: Row, bar: Box | None, track: Box, y: int,
           measure: Measure) -> tuple[dict[str, Box], dict[str, str]]:
    """Подпись справа от полосы; не влезает — внутрь; и там нет — без плашки."""
    p = row.platform
    if row.value is None:
        number, key, size = NO_DATA, "subtitle", LABEL_SIZE
    else:
        number, key, size = format_count(row.value), "number", NUMBER_SIZE
    number_w = measure(number, key, size)
    change = badge(row.value, row.previous)
    badge_w = measure(change, "number", BADGE_SIZE) + 2 * BADGE_PAD if change else 0

    outside = bar.right + LABEL_GAP if bar else track.x
    places = [(outside, track.right)]
    if bar:
        places.append((bar.x + LABEL_INSET, bar.right - LABEL_INSET))
    variants = ([True] if change else []) + [False]
    for with_badge in variants:
        need = number_w + (BADGE_GAP + badge_w if with_badge else 0)
        for start, end in places:
            if start + need <= end:
                items = {f"label:{p}": Box(start, y, number_w, BAR_HEIGHT)}
                texts = {f"label:{p}": number}
                if with_badge:
                    items[f"badge:{p}"] = Box(start + number_w + BADGE_GAP,
                                              y + (BAR_HEIGHT - BADGE_HEIGHT) // 2,
                                              badge_w, BADGE_HEIGHT)
                    texts[f"badge:{p}"] = change
                return items, texts
    # С настоящими шрифтами недостижимо (число короче места справа от 70 %);
    # рамка обрезается по дорожке, рисование обрежет текст по ней же.
    return ({f"label:{p}": Box(outside, y, max(0, track.right - outside), BAR_HEIGHT)},
            {f"label:{p}": number})


def layout(data: CoverData, measure: Measure) -> Layout:
    canvas = Box(0, 0, WIDTH, HEIGHT)
    logo_w, logo_h = LOGO_SIZE
    logo = Box(WIDTH - MARGIN - logo_w, MARGIN, logo_w, logo_h)
    header = Box(MARGIN, HEADER_TOP, logo.x - HEADER_GAP - MARGIN, HEADER_HEIGHT)
    chart_y = header.bottom + CHART_GAP
    chart = Box(MARGIN, chart_y, WIDTH - 2 * MARGIN, HEIGHT - MARGIN - chart_y)

    items: dict[str, Box] = {}
    texts: dict[str, str] = {}

    title, title_size = _title(data.title, header.w, measure)
    items["title"] = Box(header.x, MARGIN, measure(title, "title", title_size),
                         line_height("title", title_size))
    texts["title"] = title
    subtitle = _fit(data.subtitle, "subtitle", SUBTITLE_SIZE, header.w, measure)
    subtitle_h = line_height("subtitle", SUBTITLE_SIZE)
    items["subtitle"] = Box(header.x, header.bottom - subtitle_h,
                            measure(subtitle, "subtitle", SUBTITLE_SIZE), subtitle_h)
    texts["subtitle"] = subtitle

    rows = data.rows[:MAX_ROWS]
    track_x = chart.x + ICON_SIZE + ICON_GAP
    track = Box(track_x, chart.y, chart.right - track_x, chart.h)
    longest = int(track.w * BAR_SHARE)
    peak = max((row.value or 0 for row in rows), default=0)
    total = len(rows) * BAR_HEIGHT + max(0, len(rows) - 1) * ROW_GAP
    top = chart.y + (chart.h - total) // 2
    for index, row in enumerate(rows):
        y = top + index * (BAR_HEIGHT + ROW_GAP)
        p = row.platform
        items[f"icon:{p}"] = Box(chart.x, y + (BAR_HEIGHT - ICON_SIZE) // 2, ICON_SIZE, ICON_SIZE)
        width = _bar_width(row.value, peak, longest)
        bar = Box(track.x, y, width, BAR_HEIGHT) if width else None
        if bar:
            items[f"bar:{p}"] = bar
        label_items, label_texts = _label(row, bar, track, y, measure)
        items.update(label_items)
        texts.update(label_texts)

    return Layout(canvas, header, logo, chart, title, title_size, items, texts)
