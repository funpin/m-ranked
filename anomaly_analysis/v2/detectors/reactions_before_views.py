"""Реакции раньше просмотров: прирост реакций, которому не хватает просмотров.

Живые реакции приходят от живых просмотров. Ожидаемый прирост реакций за час
— доля реакций поста на просмотр, умноженная на прирост просмотров за тот же
час с допуском на задержку счётчика площадки. Реакции сверх пуассоновского
разброса вокруг этого ожидания и есть реакции «раньше» просмотров: излом ряда
реакций опережает излом просмотров или случается без него вовсе.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "reactions_before_views"
VERSION = "2.0.0"
PATTERN = 6
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False

SCALE = timedelta(hours=1)
# Доля реакций на просмотр у живого поста гуляет; вдвое выше собственной
# доли поста — ещё органика, а не признак.
RATIO_TOLERANCE = 2.0
# Нижняя граница доли: у поста почти без реакций любая первая реакция иначе
# выглядела бы бесконечным превышением.
RATIO_FLOOR = 0.002
# Пуассоновский z от шести — вероятность меньше одной на миллиард ячеек.
MIN_Z = 6.0
MIN_EXCESS = 20
# Пока просмотров меньше полусотни, доля реакций поста ещё не определена.
MIN_VIEWS = 50


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if reactions is None or views is None:
        return ()
    grid = reactions.grids.get(SCALE)
    if grid is None or not grid.rates.size:
        return ()
    starts, ends = grid.edges[:-1], grid.edges[1:]
    inside = (starts >= views.ages[0]) & (ends + context.counter_delay <= views.ages[-1])
    view_start = np.interp(starts, views.ages, views.values)
    # Просмотр может догнать реакцию на задержку счётчика — окно просмотров шире.
    view_delta = np.interp(ends + context.counter_delay, views.ages, views.values) - view_start
    reaction_start = grid.cumulative[:-1]
    reaction_delta = np.diff(grid.cumulative)
    ratio = np.maximum(reaction_start / np.maximum(view_start, 1.0), RATIO_FLOOR)
    expected = RATIO_TOLERANCE * ratio * np.maximum(view_delta, 0.0)
    z = (reaction_delta - expected) / np.sqrt(expected + 1.0)
    hot = grid.usable & inside & (view_start >= MIN_VIEWS) & (z >= MIN_Z) \
        & (reaction_delta - expected >= MIN_EXCESS)
    signs = []
    for begin, end in _runs(hot):
        observed = float(reaction_delta[begin:end].sum())
        allowed = float(expected[begin:end].sum())
        seen = float(np.maximum(view_delta[begin:end], 0).sum())
        run_z = (observed - allowed) / np.sqrt(allowed + 1.0)
        strength = 0.5 + 0.5 * min(1.0, (run_z - MIN_Z) / 24)
        start_age, end_age = float(starts[begin]), float(ends[end - 1])
        formula = (f"Δреакции = +{number(observed)} при Δпросмотры = +{number(seen)} "
                   f"за {age_text(end_age - start_age)} (ожидалось ≤ {number(max(allowed, 1))}), "
                   f"t ∈ [{age_text(start_age)}; {age_text(end_age)}]")
        signs.append(make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
                               SCALE, formula, {"kind": "lead", "reactionsDelta": round(observed),
                                                "viewsDelta": round(seen), "expected": round(allowed, 1)},
                               ("counter_update_delay",)))
    return tuple(signs)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return list(zip(edges[::2], edges[1::2]))
