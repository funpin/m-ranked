"""Observed reaction/view ordering, including Telegram's product rule 1:1.

Telegram's ratio is an explicit screening convention, not a physical upper
bound or an estimate of unique reacting users. Paid/unknown totals abstain.
"""
from __future__ import annotations

from datetime import timedelta
from bisect import bisect_right

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import PreparedSeries, views_belong_to_source
from .base import DetectorContext, make_sign, number
from .bounded_reaction_burst import reaction_bounds, _views

ID = "reactions_exceed_views"
VERSION = "2.2.0"
PATTERN = 7
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False
TELEGRAM_ORDER_MODE = "telegram_counter_order_v1"

# Запас на задержку счётчика просмотров в одиночном замере: 10 % и десяток.
SINGLE_MARGIN = 1.1
SINGLE_SLACK = 10
MIN_CONSECUTIVE = 2


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    if views_belong_to_source(prepared.series):
        return ()
    if prepared.series.platform == "telegram":
        return _telegram_order(prepared, context)
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
        # Считаются разные показания: перенесённая точка (то же значение в
        # следующем цикле, series.confirm_unchanged) и контрольный замер без
        # изменений — не новое превышение.
        count = 1 + int(np.count_nonzero((np.diff(r[begin:end]) != 0) | (np.diff(v[begin:end]) != 0)))
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


def _telegram_order(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    series = prepared.series
    if Metric.REACTIONS not in series.values or Metric.VIEWS not in series.values:
        return ()
    count = bisect_right(series.observed_at, prepared.analyzed_at)
    # Bounds can only confirm or weaken an observed excess. Skip their
    # construction when no actual reading meets the necessary raw condition.
    if not any(r is not None and v is not None and r >= 20 and r > v
               for r, v in zip(series.values[Metric.REACTIONS][:count],
                               series.values[Metric.VIEWS][:count])):
        return ()
    views = _views(prepared, count)
    reactions = [None if uncertain else reaction_bounds(value, quality, breakdown)
                 for value, quality, uncertain, breakdown in zip(
                     series.values[Metric.REACTIONS][:count], series.qualities[Metric.REACTIONS][:count],
                     series.interval_uncertain[:count], series.reaction_breakdowns[:count] or (None,) * count)]
    groups, group = [], []
    for i, (r, v) in enumerate(zip(reactions, views)):
        qualifies = (r is not None and v is not None and series.values[Metric.REACTIONS][i] >= 20
                     and series.values[Metric.REACTIONS][i] > series.values[Metric.VIEWS][i])
        separated = group and (series.observed_at[i] - series.observed_at[group[-1]]).total_seconds() > 5400
        if group and (not qualifies or separated):
            groups.append(group)
            group = []
        if qualifies:
            group.append(i)
    if group:
        groups.append(group)
    signs = []
    for group in groups:
        worst = max(group, key=lambda i: reactions[i][0] - views[i][1])
        r, v = reactions[worst], views[worst]
        certain = [i for i in group if reactions[i][0] > views[i][1]]
        sustained = (len(certain) >= 2 and len(certain) == len(group)
                     and (series.observed_at[certain[-1]] - series.observed_at[certain[0]]).total_seconds()
                     >= context.counter_delay)
        strength = .75 if sustained else .5
        start_age = (series.observed_at[group[0]] - series.published_at).total_seconds()
        end_age = (series.observed_at[group[-1]] - series.published_at).total_seconds()
        observed_r, observed_v = series.values[Metric.REACTIONS][worst], series.values[Metric.VIEWS][worst]
        formula = (f"по правилу сравнения 1:1: реакции {number(observed_r)} > просмотры {number(observed_v)} "
                   f"в {len(group)} замер{'е' if len(group) == 1 else 'ах'}; "
                   f"с учётом точности: реакции [{number(r[0])}; {number(r[1])}], "
                   f"просмотры [{number(v[0])}; {number(v[1])}]. "
                   + ("Превышение сохраняется с учётом округления" if r[0] > v[1]
                      else "Диапазоны пересекаются: величина превышения требует проверки"))
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
            timedelta(seconds=max(1, end_age - start_age)), formula,
            {"kind": "exceed", "measurementMode": TELEGRAM_ORDER_MODE,
             "reactions": observed_r, "views": observed_v, "points": len(group),
             "comparisonRatio": 1, "reactionRange": list(r), "viewRange": list(v),
             "boundsOverlap": r[0] <= v[1]}, ("views_counter_delay", "multiple_reactions_per_viewer")))
    return tuple(signs)
