"""Рывок, обрывающийся в плато без степенного хвоста.

Фермы доставляют сотни реакций за 2–4 часа и замолкают (De Cristofaro и др.,
2014): после рывка скорость сразу возвращается к затухшему фону. Живая волна,
даже от внешнего толчка, затухает степенно — в следующий час она ещё
приносит заметную долю пиковой скорости.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "burst_plateau"
VERSION = "2.0.0"
PATTERN = 9
FAMILY = Family.SHAPE
NEEDS_NORM = False

SCALE = timedelta(hours=1)
METRICS = (Metric.VIEWS, Metric.REACTIONS)
MIN_ONSET_AGE = 6 * HOUR
BACKGROUND_HOURS = 6
# Рывок — скорость хотя бы вдесятеро выше фона; длиннее шести часов — это уже
# подача, её ловит детектор линейной подачи.
BURST_FACTOR = 10.0
MAX_BURST_HOURS = 6
MIN_DELTA = {Metric.VIEWS: 50, Metric.REACTIONS: 20}
MIN_SHARE = 0.05
# «Тело» рывка — часы не ниже 30 % пика. Ступенька и ровная подача после
# тела обрываются сразу; живая волна за пиком ещё держит десятки процентов
# пиковой скорости и опускается к фону постепенно, а не одним шагом.
BODY_SHARE = 0.3
# Три часа после тела; обрыв в плато — меньше 5 % пиковой скорости.
AFTER_HOURS = 3
MAX_AFTER_SHARE = 0.05
NAMES = {Metric.VIEWS: "просмотров", Metric.REACTIONS: "реакций"}


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    signs = []
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        if data is None or data.source_counter:
            continue
        grid = data.grids.get(SCALE)
        if grid is None or grid.rates.size < BACKGROUND_HOURS + AFTER_HOURS + 1:
            continue
        rates = grid.rates * HOUR
        usable = grid.usable
        index = BACKGROUND_HOURS
        while index < rates.size - AFTER_HOURS:
            background = rates[index - BACKGROUND_HOURS:index][usable[index - BACKGROUND_HOURS:index]]
            floor = max(float(np.median(background)) if background.size else np.inf, 1.0)
            if not usable[index] or grid.edges[index] < MIN_ONSET_AGE or rates[index] < BURST_FACTOR * floor:
                index += 1
                continue
            end = index
            while end < rates.size and usable[end] and rates[end] >= BURST_FACTOR * floor:
                end += 1
            sign = _judge(prepared, metric, grid, rates, usable, index, end, floor)
            if sign is not None:
                signs.append(sign)
            index = end
    return tuple(signs)


def _judge(prepared, metric, grid, rates, usable, begin, end, floor):
    peak = float(rates[begin:end].max())
    body = np.flatnonzero(rates[begin:end] >= BODY_SHARE * peak)
    end = begin + int(body[-1]) + 1
    after = slice(end, end + AFTER_HOURS)
    # Плато, совпавшее с пробелом или отказом метрики, — не обрыв, а отсутствие данных.
    if end - begin > MAX_BURST_HOURS or end + AFTER_HOURS > rates.size or not usable[after].all():
        return None
    burst = float(grid.cumulative[end] - grid.cumulative[begin])
    start_value = float(grid.cumulative[begin])
    if burst < max(MIN_DELTA[metric], MIN_SHARE * start_value):
        return None
    tail = float(rates[after].mean())
    share = tail / peak
    if share > MAX_AFTER_SHARE:
        return None
    strength = 0.6 + 0.4 * (1 - share / MAX_AFTER_SHARE)
    start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
    formula = (f"+{number(burst)} {NAMES[metric]} за {age_text(end_age - start_age)} "
               f"(t ∈ [{age_text(start_age)}; {age_text(end_age)}]), затем {number(tail)}/ч — "
               f"{share:.1%} пиковой скорости")
    return make_sign(PATTERN, FAMILY, prepared, metric, strength, start_age, end_age, SCALE, formula,
                     {"kind": "plateau", "burst": round(burst), "peakRate": round(peak, 1),
                      "tailRate": round(tail, 2), "backgroundRate": round(floor, 2)},
                     ("counter_frozen",))
