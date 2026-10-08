"""ERV поста вне нормы аккаунта: робастный z в логарифмической шкале.

ERV сравнивается с нормой того же возраста поста, потому что с возрастом он
меняется. Оба направления информативны: только реакции поднимают ERV, только
просмотры роняют. Честно «выстреливший» пост тоже выходит за норму, поэтому
признак сам по себе не сильнее слабого сигнала (исследование, раздел 5).

Telegram с тысячи показывает просмотры округлёнными («1,27K»), и заметный
пост к суткам точных просмотров уже не имеет. Тогда просмотры берутся с
коридором округления (series.views_estimate_at), и признак ставится, только
если ERV выходит за норму на обеих границах коридора.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..norms import ERV
from ..series import AGE_BAND_EDGES, PreparedSeries, engagement_at, views_belong_to_source, views_estimate_at
from .base import DetectorContext, age_text, make_sign

ID = "erv_outlier"
VERSION = "2.2.0"
PATTERN = 10
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = True

MIN_Z = 3.0
# Живой ERV между постами одного аккаунта гуляет хотя бы на 15 %: более узкая
# полоса нормы превращала бы в признак любую случайность.
SPREAD_FLOOR = 0.15
MAX_STRENGTH = 0.55
ENGAGEMENT = (Metric.REACTIONS, Metric.COMMENTS, Metric.SHARES)


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    series = prepared.series
    views = series.values.get(Metric.VIEWS)
    if series.is_repost or context.norm is None or views is None or views_belong_to_source(series):
        return ()
    observed = [at for at, value in zip(series.observed_at, views)
                if value is not None and at <= prepared.analyzed_at]
    if not observed:
        return ()
    ends = AGE_BAND_EDGES[1:]
    reached = np.flatnonzero(ends <= (observed[-1] - series.published_at).total_seconds())
    if not reached.size:
        return ()
    band = int(reached[-1])
    cell = context.norm.cells.get((ERV, band))
    if cell is None or cell.log_erv is None:
        return ()
    end = float(ends[band])
    seen = views_estimate_at(prepared, end)
    engaged = engagement_at(prepared, end)
    if seen is None or engaged is None or seen.low <= 0 or engaged <= 0:
        return ()
    value = float(np.log(engaged / seen.value))
    spread = max(1.4826 * cell.log_erv.mad, SPREAD_FLOOR)
    z = (value - cell.log_erv.median) / spread
    # Меньшее по модулю отклонение внутри коридора округления.
    bounds = [(float(np.log(engaged / item)) - cell.log_erv.median) / spread for item in (seen.high, seen.low)]
    if abs(z) < MIN_Z or bounds[0] * bounds[1] <= 0 or min(map(abs, bounds)) < MIN_Z:
        return ()
    strength = min(MAX_STRENGTH, 0.45 + 0.02 * (abs(z) - MIN_Z))
    start = float(AGE_BAND_EDGES[band])
    formula = (f"ERV {np.exp(value):.1%} против {np.exp(cell.log_erv.median):.1%} по норме "
               f"(z = {z:+.1f} в лог-шкале), возраст {age_text(end)}"
               + (f"; просмотры округлены площадкой: {seen.low:.0f}–{seen.high:.0f}" if seen.rounded else ""))
    alternatives = ("viral_post",) if z > 0 else ("wide_reach_low_engagement",)
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start, end,
                      timedelta(seconds=end - start), formula,
                      {"kind": "erv", "erv": round(float(np.exp(value)), 5),
                       "median": round(float(np.exp(cell.log_erv.median)), 5), "z": round(float(z), 2),
                       "band": band, **({"views_range": [seen.low, seen.high]} if seen.rounded else {})},
                      alternatives, context.norm.confidence_for(ERV, band)),)
