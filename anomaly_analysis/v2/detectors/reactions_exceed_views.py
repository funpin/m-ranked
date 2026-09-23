"""Реакций больше, чем просмотров, в замере — физически невозможно.

Реакции предшествует просмотр. Разовое превышение в пределах запаса ещё
объясняется задержкой счётчика просмотров; два замера подряд или превышение
сверх запаса — уже признак.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import PreparedSeries
from .base import DetectorContext, make_sign, number

ID = "reactions_exceed_views"
VERSION = "2.0.0"
PATTERN = 7
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False

# Запас на задержку счётчика просмотров в одиночном замере: 10 % и десяток.
SINGLE_MARGIN = 1.1
SINGLE_SLACK = 10
MIN_CONSECUTIVE = 2


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if reactions is None or views is None:
        return ()
    # Сравниваются только замеры, где получены обе метрики.
    common, left, right = np.intersect1d(reactions.ages, views.ages, return_indices=True)
    if not common.size:
        return ()
    r, v = reactions.values[left], views.values[right]
    exceed = r > v
    signs = []
    edges = np.flatnonzero(np.diff(np.concatenate(([0], exceed.astype(np.int8), [0]))))
    for begin, end in zip(edges[::2], edges[1::2]):
        count = int(end - begin)
        worst = int(begin + np.argmax(r[begin:end] - v[begin:end]))
        beyond = r[worst] > v[worst] * SINGLE_MARGIN + SINGLE_SLACK
        if count < MIN_CONSECUTIVE and not beyond:
            continue
        excess_ratio = float(r[worst] / max(v[worst], 1.0))
        strength = (0.7 + 0.3 * min(1.0, (excess_ratio - 1) / 0.5)) if count >= MIN_CONSECUTIVE else 0.5
        start_age = float(common[begin - 1] if begin > 0 else common[begin])
        end_age = float(common[end - 1])
        formula = (f"реакции {number(r[worst])} > просмотры {number(v[worst])}"
                   f" в {count} замер{'е' if count == 1 else 'ах'} подряд")
        signs.append(make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
                               timedelta(seconds=max(1.0, end_age - start_age)), formula,
                               {"kind": "exceed", "reactions": int(r[worst]), "views": int(v[worst]),
                                "points": count}, ("views_counter_delay",)))
    return tuple(signs)
