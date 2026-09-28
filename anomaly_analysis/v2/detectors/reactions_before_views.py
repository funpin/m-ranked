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
from ..series import DAY, HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "reactions_before_views"
VERSION = "2.1.0"
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

# A bounded endpoint check cannot establish the shape inside a collection gap.
# Keep it weak, MAX-only, and within the existing six-hour analysis horizon.
MAX_ENDPOINT_GAP = 6 * HOUR
ENDPOINT_STRENGTH = 0.5
ENDPOINT_MODE = "observed_gap_endpoints_v1"


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if reactions is None or views is None:
        return ()
    grid = reactions.grids.get(SCALE)
    if grid is None or not grid.rates.size:
        return _gap_endpoints(prepared, context)
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
    signs.extend(_gap_endpoints(prepared, context))
    return tuple(signs)


def _gap_endpoints(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    """Compare measured counts, without inventing timing or an early-age fit.

    Both ends must be adjacent real observations with exact V/R. An additional
    real reading after the counter-delay allowance must confirm that views
    did not catch up. Missing qualities, intervening invalid values and any
    observed negative correction make the whole comparison unavailable.
    """
    series = prepared.series
    if series.platform != "max" or series.is_repost:
        return ()
    reactions = prepared.metrics.get(Metric.REACTIONS)
    if reactions is None or Metric.VIEWS not in prepared.metrics:
        return ()
    ages = prepared.ages
    counts = [series.exact_values(metric) for metric in (Metric.VIEWS, Metric.REACTIONS)]
    if any(column is None for column in counts):
        return ()
    views, reacts = (np.asarray(column[:ages.size], dtype=float) for column in counts)
    signs = []
    for gap in reactions.gaps:
        duration = gap.end_age - gap.start_age
        if (not gap.count_change_trusted or gap.start_age < DAY
                or duration > MAX_ENDPOINT_GAP or gap.delta < MIN_EXCESS):
            continue
        start = int(np.searchsorted(ages, gap.start_age))
        end = int(np.searchsorted(ages, gap.end_age))
        # Never bridge an omitted/untrusted metric reading between the ends.
        if end != start + 1 or end >= ages.size:
            continue
        delayed = int(np.searchsorted(ages, gap.end_age + context.counter_delay))
        if (delayed >= ages.size or ages[delayed] > gap.end_age + context.counter_delay
                + 3 * prepared.expected_steps[end]):
            continue
        v, r = views[start:delayed + 1], reacts[start:delayed + 1]
        if (not np.isfinite(v).all() or not np.isfinite(r).all()
                or np.any(np.diff(v) < 0) or np.any(np.diff(r) < 0) or v[0] < MIN_VIEWS):
            continue
        observed = float(reacts[end] - reacts[start])
        view_delta = float(views[end] - views[start])
        delayed_views = float(views[delayed] - views[start])
        ratio = max(float(reacts[start] / views[start]), RATIO_FLOOR)
        expected = RATIO_TOLERANCE * ratio * delayed_views
        # Reuse the existing heuristic screen, not a calibrated p-value.
        if observed - expected < MIN_EXCESS or (observed - expected) / np.sqrt(expected + 1) < MIN_Z:
            continue
        formula = (f"между точными замерами за {age_text(duration)}: реакции "
                   f"{number(reacts[start])} → {number(reacts[end])} (+{number(observed)}), "
                   f"просмотры {number(views[start])} → {number(views[end])} (+{number(view_delta)}); "
                   f"с учётом последующего замера через {age_text(ages[delayed] - gap.end_age)} "
                   f"прирост просмотров +{number(delayed_views)}. "
                   "Время и форма прироста внутри пробела неизвестны")
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.REACTIONS, ENDPOINT_STRENGTH,
            gap.start_age, gap.end_age, timedelta(seconds=duration), formula,
            {"kind": "lead", "comparisonMode": ENDPOINT_MODE,
             "reactionsDelta": round(observed), "viewsDelta": round(view_delta),
             "viewsDeltaWithDelay": round(delayed_views), "expected": round(expected, 2),
             "delayObservationAge": round(float(ages[delayed]))},
            ("counter_update_delay", "returning_readers")))
    return tuple(signs)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return list(zip(edges[::2], edges[1::2]))
