"""Списание реакций: счётчик резко уменьшился и не восстановился.

Читатели снимают реакции по одной; одновременно десятки снятых реакций — это
действие площадки. ВК и MAX списывают реакции аккаунтов, признанных
недостоверными, пачкой: счётчик падает за один замер и остаётся ниже.
Кратковременный провал, после которого значение вернулось, — сбой выдачи,
а не списание; такой провал признаком не считается.

Признак говорит о решении площадки, а не о том, кто поставил реакции.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "reaction_write_off"
VERSION = "1.0.0"
PATTERN = 15
FAMILY = Family.SHAPE
NEEDS_NORM = False
MEASUREMENT_MODE = "reaction_write_off_v1"

# Списание — не меньше десяти реакций и пятнадцати процентов значения.
MIN_DROP = 10
MIN_SHARE = 0.15
# Значение не вернулось: ещё два замера на протяжении хотя бы часа держатся
# ниже прежнего больше чем на половину списанного (смотрим два часа:
# дальше пост дорастает органически, а возврат сбоя выдачи приходит сразу).
CONFIRM_POINTS = 2
CONFIRM_SPAN = HOUR
CONFIRM_HORIZON = 2 * HOUR
KEEP_SHARE = 0.5
# Крупное списание — выраженная аномалия: 30 реакций или треть значения.
STRONG_DROP = 30
STRONG_SHARE = 1 / 3


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    series = prepared.series
    column = series.exact_values(Metric.REACTIONS)
    if column is None:
        return ()
    published, moment = series.published_at.timestamp(), prepared.analyzed_at.timestamp()
    instants = np.fromiter((at.timestamp() for at in series.observed_at), dtype=np.float64,
                           count=len(series.observed_at))
    raw = np.asarray(column, dtype=np.float64)
    keep = ~np.isnan(raw) & (instants <= moment)
    ages, values = instants[keep] - published, raw[keep]
    if values.size < CONFIRM_POINTS + 2:
        return ()
    # Подряд идущие падения — одно списание: площадка может списать пачку
    # между двумя опросами, и тогда её видно в двух-трёх замерах подряд.
    falling = np.diff(values) < 0
    runs = []
    index = 0
    while index < falling.size:
        if falling[index]:
            end = index
            while end + 1 < falling.size and falling[end + 1]:
                end += 1
            runs.append((index, end + 1))
            index = end + 1
        else:
            index += 1
    signs = []
    for first, index in runs:
        before, after = values[first], values[index]
        drop = before - after
        if drop < max(MIN_DROP, MIN_SHARE * before):
            continue
        horizon = np.flatnonzero((ages > ages[index]) & (ages <= ages[index] + CONFIRM_HORIZON))
        if horizon.size < CONFIRM_POINTS or ages[horizon[-1]] - ages[index] < CONFIRM_SPAN:
            continue
        if values[horizon].max() > before - KEEP_SHARE * drop:
            continue
        share = drop / before
        strength = 0.75 if drop >= STRONG_DROP or share >= STRONG_SHARE else 0.55
        formula = (f"реакции: {number(before)} → {number(after)} (−{number(drop)}, −{share:.0%}) между замерами "
                   f"{age_text(ages[first])} и {age_text(ages[index])}; за следующие "
                   f"{age_text(ages[horizon[-1]] - ages[index])} значение не вернулось "
                   f"(не выше {number(values[horizon].max())})")
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, float(ages[first]), float(ages[index]),
            timedelta(seconds=float(ages[index] - ages[first])), formula,
            {"kind": "write_off", "measurementMode": MEASUREMENT_MODE, "before": int(before), "after": int(after),
             "removed": int(drop), "removedShare": round(float(share), 3),
             "confirmationEndAge": round(float(ages[horizon[-1]]))},
            ("platform_write_off", "post_edited_reactions_reset")))
    return tuple(signs)

