"""Прирост за пробел в замерах сверх интеграла модели затухания.

За пробел ожидается ровно то, что принесла бы продолженная модель поста. Если
до пробела рост почти остановился, а после него счётчик оказался в разы выше,
подача пришлась на время, когда её никто не видел.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "gap_growth"
VERSION = "2.0.0"
PATTERN = 4
FAMILY = Family.SHAPE
NEEDS_NORM = True

METRICS = (Metric.VIEWS, Metric.REACTIONS)
# На раннем быстром участке модель ещё не уверена: пробел в первые 12 часов
# не оценивается.
MIN_GAP_AGE = 12 * HOUR
MIN_RATIO = 5.0
MIN_Z = 4.0
MIN_EXCESS = {Metric.VIEWS: 50, Metric.REACTIONS: 20}
MIN_SHARE = 0.1
# «Почти остановившийся» рост: скорость последних трёх часов до пробела,
# продолженная на весь пробел, даёт меньше пятой части факта.
BEFORE_WINDOW = 3 * HOUR


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    if prepared.series.is_repost:
        return ()
    signs = []
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        fit = context.early_fit(prepared, metric)
        if data is None or fit is None or data.source_counter:
            continue
        for gap in data.gaps:
            if gap.start_age < MIN_GAP_AGE or gap.delta <= 0:
                continue
            model = float(fit.expected(np.array([gap.start_age]), np.array([gap.end_age]))[0])
            before = float(gap.start_age - BEFORE_WINDOW)
            recent = (float(np.interp(gap.start_age, data.ages, data.values))
                      - float(np.interp(before, data.ages, data.values))) / BEFORE_WINDOW
            duration = gap.end_age - gap.start_age
            start_value = float(np.interp(gap.start_age, data.ages, data.values))
            ratio = (gap.delta + 0.5) / (model + 0.5)
            z = np.log(ratio) / np.sqrt(fit.sigma_model ** 2 + 1.0 / (model + 0.5))
            if (ratio < MIN_RATIO or z < MIN_Z or recent * duration * MIN_RATIO > gap.delta
                    or gap.delta - model < max(MIN_EXCESS[metric], MIN_SHARE * start_value)):
                continue
            strength = 0.5 + 0.5 * min(1.0, np.log(ratio / MIN_RATIO) / np.log(20))
            formula = (f"за пробел {age_text(duration)} прирост +{number(gap.delta)} при ожидаемых "
                       f"{number(model)} (×{ratio:.0f}), t ∈ [{age_text(gap.start_age)}; {age_text(gap.end_age)}]")
            signs.append(make_sign(PATTERN, FAMILY, prepared, metric, strength, gap.start_age, gap.end_age,
                                   timedelta(seconds=duration), formula,
                                   {"kind": "gap", "actual": round(gap.delta), "expected": round(model, 1),
                                    "rateBefore": round(recent * HOUR, 2)},
                                   ("collection_outage_during_organic_wave",), context.norm_confidence))
    return tuple(signs)
