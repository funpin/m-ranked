"""Реакции сквозь ночь: поток реакций видео ВК в 00–06 МСК, часто с обрывом в ноль.

Просмотры записи на стене у клипа — не его аудитория (series.NOT_AUDIENCE_TYPES):
клип смотрят в ленте клипов, и доля реакций на просмотр стены ничего не
доказывает. Остаётся время. Живой отклик на клип приходит днём и вечером;
ночью аудитория спит, и в ленте клипов тоже.

Губкинский ВК №238136, 01–02.10.2026: за 9 ч после публикации 2 лайка, затем
с 20:30 до 04:30 МСК +397 лайков, ночью по 19–65 в час, и в 04:30 поток
обрывается в ноль, хотя просмотры записи идут дальше.

Эпизод — час с наибольшим приростом реакций на часовой сетке МСК и соседние
часы не ниже пятой части его (до двух более слабых часов внутри). Час сетки
известен, когда замеры у обеих его границ не дальше MAX_GAP друг от друга
или счётчик на краях промежутка не изменился (доказанное плато).

Пороги — клипы ВК 15.09–11.10.2026 (1 060 постов, копия прода 12.10): у 127
эпизодов от 30 реакций вне Губкинского ночная доля не выше 0,244 (99-й
перцентиль 0,136); у Губкинского — 0,32–1,0 у семи из восьми, все по одной
схеме: публикация около 18:00, реакции с 00–01 МСК. Обрыв в ноль при
продолжающихся просмотрах — у 4 клипов из 1 060.
"""
from __future__ import annotations

from datetime import timedelta
import math

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries, views_not_audience_reason
from .base import DetectorContext, age_text, make_sign, number

ID = "night_reaction_stream"
VERSION = "1.0.0"
PATTERN = 18
FAMILY = Family.VELOCITY
NEEDS_NORM = False
MODE = "night_reaction_stream_v1"

MOSCOW_OFFSET = 3 * HOUR
NIGHT_END_HOUR = 6
MAX_GAP = 1.6 * HOUR
FLOOR = 3.0
EPISODE_SHARE = 0.2
DIP = 2
MIN_REACTIONS = 30
MIN_NIGHT_REACTIONS = 20
NIGHT_SHARE = 0.3
# Первый отклик на клип приходит с публикации: эпизод, начавшийся в первые два
# часа, — это он (СКФУ, клип 26.09 в 17:03: 41 лайк с 18 до 02 при 984 просмотрах).
MIN_START_AGE = 2 * HOUR
# Обрыв: последние два часа эпизода не меньше CLIFF_RATE в час, затем
# CLIFF_HOURS известных часов без единой реакции при приросте просмотров.
CLIFF_RATE = 20.0
CLIFF_HOURS = 4
MEDIUM_STRENGTH = 0.55
STRONG_STRENGTH = 0.75


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    if views_not_audience_reason(prepared.series) != "vk_video_views":
        return ()
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if reactions is None or views is None or reactions.ages.size < 3 or views.ages.size < 3:
        return ()
    published = prepared.series.published_at.timestamp()
    first = max(reactions.ages[0], views.ages[0])
    last = min(reactions.ages[-1], views.ages[-1])
    # Границы часов МСК в возрасте поста.
    begin = math.ceil((published + first + MOSCOW_OFFSET) / HOUR) * HOUR - MOSCOW_OFFSET - published
    end = math.floor((published + last + MOSCOW_OFFSET) / HOUR) * HOUR - MOSCOW_OFFSET - published
    if end - begin < 3 * HOUR:
        return ()
    edges = np.arange(begin, end + 1, HOUR)
    r_cum, r_known = _on_edges(reactions.ages, reactions.values, edges)
    v_cum, v_known = _on_edges(views.ages, views.values, edges)
    rate, growth = np.diff(r_cum), np.diff(v_cum)
    known = r_known[:-1] & r_known[1:] & v_known[:-1] & v_known[1:]
    episode = _episode(rate, known)
    if episode is None:
        return ()
    first_hour, last_hour = episode
    start_age, end_age = float(edges[first_hour]), float(edges[last_hour + 1])
    if start_age < MIN_START_AGE:
        return ()
    span = slice(first_hour, last_hour + 1)
    total = float(rate[span].sum())
    clock = ((published + edges[:-1] + MOSCOW_OFFSET) % 86400) // HOUR
    night = float(rate[span][clock[span] < NIGHT_END_HOUR].sum())
    if total < MIN_REACTIONS or night < MIN_NIGHT_REACTIONS or night < NIGHT_SHARE * total:
        return ()
    cliff = _cliff(rate, growth, known, first_hour, last_hour)
    strength = STRONG_STRENGTH if cliff is not None else MEDIUM_STRENGTH
    start_clock = int(clock[first_hour])
    end_clock = int((clock[last_hour] + 1) % 24)
    formula = (f"+{number(total)} реакций за t ∈ [{age_text(start_age)}; {age_text(end_age)}] "
               f"({start_clock:02d}:00–{end_clock:02d}:00 МСК), из них {night / total:.0%} — с 00 до 06 МСК; "
               f"просмотры записи за то же время +{number(float(growth[span].sum()))}")
    if cliff is not None:
        formula += (f"; затем {CLIFF_HOURS} ч без единой реакции после {number(cliff[0])} в час "
                    f"при +{number(cliff[1])} просмотрах записи")
    render = {"kind": "night_stream", "reactions": int(round(total)), "nightReactions": int(round(night)),
              "nightShare": round(night / total, 4), "startClock": start_clock, "endClock": end_clock,
              "cliffRate": round(cliff[0], 1) if cliff is not None else None,
              "cliffViews": int(round(cliff[1])) if cliff is not None else None, "mode": MODE}
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
                      timedelta(hours=1), formula, render,
                      ("night_audience_abroad", "clip_feed_recommendation")),)


def _on_edges(ages: np.ndarray, values: np.ndarray, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Счётчик на границах часов и известна ли граница: замеры рядом или плато."""
    values = np.maximum.accumulate(values.astype(float))
    cumulative = np.interp(edges, ages, values)
    right = np.clip(np.searchsorted(ages, edges), 0, ages.size - 1)
    left = np.clip(right - 1, 0, ages.size - 1)
    exact = ages[right] == edges
    known = exact | (ages[right] - ages[left] <= MAX_GAP) | (values[right] == values[left])
    return cumulative, known


def _episode(rate: np.ndarray, known: np.ndarray) -> tuple[int, int] | None:
    if not known.any():
        return None
    masked = np.where(known, rate, -1.0)
    peak = int(masked.argmax())
    if rate[peak] < FLOOR:
        return None
    threshold = max(FLOOR, EPISODE_SHARE * float(rate[peak]))
    first = last = peak
    while True:
        step = next((index for index in range(first - 1, max(-1, first - 2 - DIP), -1)
                     if known[index] and rate[index] >= threshold), None)
        if step is None or not known[step:first].all():
            break
        first = step
    while True:
        step = next((index for index in range(last + 1, min(rate.size, last + 2 + DIP))
                     if known[index] and rate[index] >= threshold), None)
        if step is None or not known[last + 1:step + 1].all():
            break
        last = step
    return first, last


def _cliff(rate, growth, known, first_hour: int, last_hour: int) -> tuple[float, float] | None:
    """(темп последних двух часов эпизода, прирост просмотров после) — если реакции оборвались в ноль."""
    after = slice(last_hour + 1, last_hour + 1 + CLIFF_HOURS)
    if last_hour + CLIFF_HOURS >= rate.size or not known[after].all():
        return None
    tail = float(rate[max(first_hour, last_hour - 1):last_hour + 1].mean())
    views_after = float(growth[after].sum())
    if tail < CLIFF_RATE or float(rate[after].sum()) > 0 or views_after <= 0:
        return None
    return tail, views_after
