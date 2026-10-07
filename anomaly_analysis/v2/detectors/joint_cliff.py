"""Одновременный обрыв просмотров и реакций после ровного участка.

Живой интерес затухает плавно: за соседние часы скорость меняется в разы
только ночью, когда аудитория засыпает. Подача, у которой закончился
оплаченный объём, обрывается сразу по обеим метрикам: часами шла почти
ровно — и в следующие три часа стала вдесятеро медленнее. Один обрыв одной
метрики случается и у живых постов (вечерний спад, выпадение из ленты),
поэтому признак требует совпадения обрывов просмотров и реакций.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "joint_cliff"
VERSION = "1.0.0"
PATTERN = 16
FAMILY = Family.VELOCITY
NEEDS_NORM = False
MEASUREMENT_MODE = "joint_cliff_v1"

WINDOW = 3 * HOUR
MIN_SPAN = 2.5 * HOUR
# Обрыв — скорость после хотя бы в восемь раз ниже скорости до.
MIN_DROP = 8.0
# До обрыва участок ровный: половины окна различаются не больше чем вдвое.
MAX_DECAY = 0.5
# Обрывы двух метрик совпали в пределах часа.
MAX_LAG = HOUR
MIN_BEFORE = {Metric.VIEWS: 100, Metric.REACTIONS: 30}
# Ночь по Москве: спад в эти часы — суточный ритм.
MSK_OFFSET = 3 * HOUR
DAY_START, DAY_END = 8, 23


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    cliffs = {metric: _cliffs(prepared, metric) for metric in (Metric.VIEWS, Metric.REACTIONS)}
    if not cliffs[Metric.VIEWS] or not cliffs[Metric.REACTIONS]:
        return ()
    best = None
    for views in cliffs[Metric.VIEWS]:
        for reactions in cliffs[Metric.REACTIONS]:
            if abs(views[0] - reactions[0]) <= MAX_LAG:
                score = min(views[3], reactions[3])
                if best is None or score > best[0]:
                    best = (score, views, reactions)
    if best is None:
        return ()
    _, views, reactions = best
    at = min(views[0], reactions[0])
    formula = (f"просмотры: {number(views[1])}/ч → {number(views[2])}/ч, реакции: {number(reactions[1])}/ч → "
               f"{number(reactions[2])}/ч около {age_text(at)} — обе метрики замедлились в "
               f"{min(views[3], reactions[3]):.0f}+ раз сразу после ровного участка; соседние окна по 3ч")
    return (make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, 0.75, at - WINDOW, at, timedelta(seconds=WINDOW),
                      formula, {"kind": "cliff", "measurementMode": MEASUREMENT_MODE,
                                "viewsBefore": round(views[1], 1), "viewsAfter": round(views[2], 1),
                                "reactionsBefore": round(reactions[1], 1), "reactionsAfter": round(reactions[2], 1),
                                "cliffAge": round(at)},
                      ("counter_frozen", "recommendation_wave")),)


def _cliffs(prepared: PreparedSeries, metric: Metric) -> list[tuple[float, float, float, float]]:
    data = prepared.metrics.get(metric)
    if data is None or data.source_counter or data.ages.size < 6:
        return []
    ages, values = data.ages, data.values.astype(float)
    # Окно с уменьшением счётчика внутри не судится: префиксная сумма падений.
    falls = np.concatenate(([0], np.cumsum(np.diff(values) < 0)))
    published = prepared.series.published_at.timestamp()
    at = ages[1:-1]
    clock = ((published + at + MSK_OFFSET) // HOUR).astype(np.int64) % 24
    keep = (clock >= DAY_START) & (clock < DAY_END)
    at = at[keep]
    if not at.size:
        return []
    before = _rates(ages, values, falls, at - WINDOW, at, MIN_SPAN)
    after = _rates(ages, values, falls, at, at + WINDOW, MIN_SPAN)
    first = _rates(ages, values, falls, at - WINDOW, at - WINDOW / 2, WINDOW / 3)
    last = _rates(ages, values, falls, at - WINDOW / 2, at, WINDOW / 3)
    ok = ~(np.isnan(before) | np.isnan(after) | np.isnan(first) | np.isnan(last))
    # Ровный участок: половины окна различаются не больше чем вдвое. Живая
    # волна (пересылка, рекомендации) внутри окна сначала растёт, и её
    # обычное затухание за пиком обрывом не считается.
    with np.errstate(invalid="ignore"):
        ok &= (before * WINDOW / HOUR >= MIN_BEFORE[metric]) & (last >= MAX_DECAY * first) & (last * MAX_DECAY <= first)
        ratio = before / np.maximum(after, 0.1)
        ok &= ratio >= MIN_DROP
    return [(float(at[i]), float(before[i]), float(after[i]), float(ratio[i])) for i in np.flatnonzero(ok)]


def _rates(ages, values, falls, start, end, min_span) -> np.ndarray:
    """Скорость между крайними замерами внутри [start; end] (±1 с), в единицах в час; NaN — нельзя."""
    a = np.searchsorted(ages, start - 1, side="left")
    b = np.searchsorted(ages, end + 1, side="right") - 1
    valid = b > a
    a, b = np.clip(a, 0, ages.size - 1), np.clip(b, 0, ages.size - 1)
    span = ages[b] - ages[a]
    valid &= (span >= min_span) & (falls[b] == falls[a])
    rate = np.full(start.shape, np.nan)
    rate[valid] = (values[b] - values[a])[valid] / span[valid] * HOUR
    return rate
