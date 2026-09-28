"""Large reaction changes that remain large under compact-count uncertainty.

Exact counts are usable on every platform. Only Telegram's retained individual
compact reaction counters have the required
decimal-display contract here. A parsed positive component is a multiple of
its display unit (a power of ten, at most 10**9 for K/M/B). Without the original
text we allow the LARGEST such divisor on BOTH sides, covering rounding and
truncation. An explicitly retained empty list proves zero; missing components,
mismatched sums and unknown quality abstain.

We compare three observed endpoint windows, never interpolate or manufacture
unchanged readings: six hours before, a burst of at most six hours, and at least
three hours after. The least possible burst must exceed the largest possible
background tenfold, and the largest possible subsequent rate must fall below
5% of that burst. This establishes a change in window-average growth, not the
time/shape of arrivals inside a polling gap or their artificial origin.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import replace
from datetime import timedelta
from math import log2
from typing import Mapping

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number, strongest

ID = "bounded_reaction_burst"
VERSION = "1.2.0"
PATTERN = 9
FAMILY = Family.SHAPE
NEEDS_NORM = False
MEASUREMENT_MODE = "bounded_reaction_counts_v1"
BURST_HOURS = (1, 2, 3, 6)
BACKGROUND_HOURS = 6
AFTER_HOURS = 3
BOUNDARY_TOLERANCE_HOURS = 1
MIN_DELTA = 20
MIN_EARLY_DELTA = 10
MIN_SHARE = .2
# A concentrated pack needs three independently observable properties: a short
# large burst, a sustained plateau, and viewers continuing without comparable
# reactions. These are one compound pattern, not three independent signals.
CONFIRMED_PLATEAU_MODE = "concentrated_plateau_v1"
MIN_PACK = 20
MIN_PACK_RATE = 100
MAX_PACK_HOURS = .5
MIN_PACK_SHARE = .75
MIN_RATIO_DROP = 5


def reaction_bounds(total: int | None, quality: str,
                    breakdown: Mapping[str, int] | None) -> tuple[int, int] | None:
    if total is None or quality not in {"exact", "rounded"}:
        return None
    if breakdown and any(key.startswith("paid:") or key.startswith("unknown:") for key in breakdown):
        return None
    if quality == "exact":
        return total, total
    # An explicitly retained empty reaction list is the parser's zero-count
    # representation. An absent breakdown (None) is not that observation.
    if total == 0 and breakdown is not None and len(breakdown) == 0:
        return 0, 0
    if not breakdown or sum(breakdown.values()) != total:
        return None
    lower, upper = 0, 0
    for count in breakdown.values():
        if type(count) is not int or count <= 0:
            return None
        unit = _max_display_unit(count)
        lower += max(0, count - unit)
        upper += count + unit
    return lower, upper


def _max_display_unit(count: int) -> int:
    unit = 1
    while unit < 10**9 and count % (unit * 10) == 0:
        unit *= 10
    return unit


def _view_bounds(value, quality, uncertain, *, compact_allowed=True):
    if uncertain or value is None or quality not in {"exact", "rounded"}:
        return None
    if quality == "exact":
        return value, value
    if not compact_allowed:
        return None
    if value <= 0:
        return None
    unit = _max_display_unit(value)
    return max(0, value - unit), value + unit


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    series = prepared.series
    if Metric.REACTIONS not in series.values:
        return ()
    count = bisect_right(series.observed_at, prepared.analyzed_at)
    rows = list(zip(
                series.observed_at[:count], series.values[Metric.REACTIONS][:count],
                series.qualities[Metric.REACTIONS][:count], series.interval_uncertain[:count],
                series.reaction_breakdowns[:count] or (None,) * count))
    if len(rows) < 3 or max((row[1] or 0 for row in rows), default=0) < MIN_EARLY_DELTA:
        return ()
    ages = np.array([(row[0] - series.published_at).total_seconds() / HOUR for row in rows])
    bounds = [None if row[3] or (row[2] != "exact" and series.platform != "telegram")
              else reaction_bounds(row[1], row[2], row[4]) for row in rows]
    # No known correction/reset or unusable read may be hidden inside a window.
    bad = np.array([b is None for b in bounds], dtype=int)
    validity_prefix = np.r_[0, np.cumsum(bad)]
    withdrawals = np.zeros(len(rows))
    for i in range(1, len(rows)):
        if rows[i][1] is not None and rows[i-1][1] is not None and rows[i][1] < rows[i-1][1]:
            bad[i] = 1
            withdrawals[i] = rows[i-1][1] - rows[i][1]
    prefix = np.r_[0, np.cumsum(bad)]
    view_bounds = None
    signs = []
    for begin, end in _candidate_pairs(ages, bounds, BURST_HOURS, max_duration=6, min_age=6):
        after = int(np.searchsorted(ages, ages[end] + AFTER_HOURS))
        first_after = int(np.searchsorted(ages, ages[end] + 1))
        if after >= len(rows) or ages[after] - ages[end] > AFTER_HOURS + BOUNDARY_TOLERANCE_HOURS:
            continue
        before = int(np.searchsorted(ages, ages[begin] - BACKGROUND_HOURS, side="right")) - 1
        if (before < 0 or ages[begin] - ages[before] > BACKGROUND_HOURS + BOUNDARY_TOLERANCE_HOURS
                or ages[first_after] - ages[end] > 1.5 or prefix[after+1] != prefix[before]):
            continue
        low, high = bounds[begin], bounds[end]
        burst = high[0] - low[1]
        duration = ages[end] - ages[begin]
        if burst < max(MIN_DELTA, MIN_SHARE * low[1]):
            continue
        rate = burst / duration
        background = max(0, low[1] - bounds[before][0]) / (ages[begin] - ages[before])
        tail = max(0, bounds[after][1] - high[0]) / (ages[after] - ages[end])
        immediate = max(0, bounds[first_after][1] - high[0]) / (ages[first_after] - ages[end])
        if rate < 10 * max(background, 1) or max(tail, immediate) > .05 * rate:
            continue
        if view_bounds is None and not series.is_repost:
            view_bounds = _views(prepared, count)
        if view_bounds and not series.is_repost:
            v0, v1 = view_bounds[begin], view_bounds[end]
            if v0 is not None and v1 is not None:
                # A new audience with a compatible reaction fraction is a
                # plausible organic wave. Window averages alone cannot refute
                # it, even when a long burst window includes its gradual tail.
                compatible = 3 * low[1] / max(v0[0], 1) * max(0, v1[1] - v0[0])
                if burst <= compatible:
                    continue
        start_age, end_age = float(ages[begin] * HOUR), float(ages[end] * HOUR)
        formula = (f"реакции: прирост не менее +{number(burst)} за {age_text(duration * HOUR)} "
                   f"с учётом точности счётчиков; средняя скорость ≥ {number(rate)}/ч, "
                   f"до него ≤ {number(background)}/ч, после ≤ {number(tail)}/ч. "
                   "Время изменений внутри интервалов замеров неизвестно")
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.REACTIONS, .75,
            start_age, end_age, timedelta(hours=float(duration)), formula,
            {"kind": "bounded_burst", "measurementMode": MEASUREMENT_MODE,
             "burstLower": burst, "burstRateLower": round(float(rate), 2),
             "backgroundRateUpper": round(float(background), 2), "afterRateUpper": round(float(tail), 2),
             "firstAfterRateUpper": round(float(immediate), 2),
             "beforeRange": list(low), "afterRange": list(high),
             "backgroundStartAge": float(ages[before] * HOUR),
             "confirmationEndAge": float(ages[after] * HOUR),
             "timingUnknown": True},
            ("reaction_counter_batch_update", "news_event", "pinned_post")))
    withdrawal_prefix = np.r_[0, np.cumsum(withdrawals)]
    signs.extend(_decoupled(prepared, ages, bounds, validity_prefix, withdrawal_prefix))
    if not signs and series.platform == "telegram" and any(row[2] == "rounded" for row in rows):
        signs.extend(_reported_plateau(prepared, ages, bounds, validity_prefix, withdrawal_prefix))
    return tuple(strongest(signs))


def _candidate_pairs(ages, bounds, hours_options, *, max_duration, min_age=0, max_age=np.inf, min_delta=MIN_DELTA):
    """Vectorize the cheap volume gate before inspecting window evidence."""
    low = np.array([np.nan if b is None else b[0] for b in bounds])
    high = np.array([np.nan if b is None else b[1] for b in bounds])
    for hours in hours_options:
        # Zero selects adjacent real observations. A fixed 15-minute minimum
        # otherwise dilutes five-minute early bursts with their quiet tail.
        begin = (np.arange(len(ages)) - 1 if hours == 0 else
                 np.searchsorted(ages, ages - hours, side="right") - 1)
        clipped = np.maximum(begin, 0)
        duration = ages - ages[clipped]
        candidate = ((begin >= 0) & (ages[clipped] >= min_age) & (ages[clipped] < max_age)
                     & (duration <= min(max_duration, hours + .5))
                     & (low - high[clipped] >= min_delta))
        for end in np.flatnonzero(candidate):
            yield int(begin[end]), int(end)


def _views(prepared, count):
    series = prepared.series
    if Metric.VIEWS not in series.values:
        return []
    return [_view_bounds(value, quality, uncertain, compact_allowed=series.platform == "telegram")
            for value, quality, uncertain in zip(
                series.values[Metric.VIEWS][:count], series.qualities[Metric.VIEWS][:count],
                series.interval_uncertain[:count])]


def _decoupled(prepared, ages, bounds, reaction_bad_prefix, withdrawals, *, views_override=None):
    """Reaction packs at any age, without a synthetic zero or an early model.

    Require observed subsequent viewers, a tenfold fall in reactions/view,
    and a twentyfold fall in reactions/hour, all at worst-case bounds.
    Source views of reposts are not a comparable audience and abstain here.
    """
    series = prepared.series
    if series.is_repost or Metric.VIEWS not in series.values:
        return []
    count = len(ages)
    candidates = tuple(_candidate_pairs(ages, bounds, (0, 1/6, .25, .5, 1, 2), max_duration=2, min_delta=MIN_EARLY_DELTA))
    initial = 0 < ages[0] <= .25 and bounds[0] is not None and bounds[0][0] >= MIN_EARLY_DELTA
    if not candidates and not initial:
        return []
    rows = series.values[Metric.VIEWS][:count]
    views = _views(prepared, count) if views_override is None else views_override
    bad = np.array([v is None for v in views], dtype=int)
    for i in range(1, len(rows)):
        if rows[i] is not None and rows[i-1] is not None and rows[i] < rows[i-1]:
            bad[i] = 1
    prefix = np.r_[0, np.cumsum(bad)]
    signs = []
    # None means the pack is already present in the first actual observation.
    # It is a concentration by that age, never a measured rise from zero.
    for begin, end in candidates + (((None, 0),) if initial else ()):
        first = end if begin is None else begin
        after = int(np.searchsorted(ages, ages[end] + AFTER_HOURS))
        if after >= len(ages) or ages[after] - ages[end] > AFTER_HOURS + BOUNDARY_TOLERANCE_HOURS:
            continue
        if (prefix[after+1] != prefix[first]
                    or reaction_bad_prefix[after+1] != reaction_bad_prefix[first]):
            continue
        burst = bounds[end][0] if begin is None else bounds[end][0] - bounds[begin][1]
        burst_views = max(1, views[end][1] if begin is None else views[end][1] - views[begin][0])
        withdrawn = float(withdrawals[after+1] - withdrawals[end+1])
        # Reactions can be withdrawn. A few removals do not erase a real pack;
        # add every observed removal back to the upper growth bound. A reset
        # or repeated declines remain ineligible, as does a decline in the pack.
        if withdrawals[end+1] != withdrawals[first+1] or withdrawn > min(3, .05 * burst):
            continue
        after_reactions = max(0, bounds[after][1] - bounds[end][0]) + withdrawn
        after_views = views[after][0] - views[end][1]
        duration = float(ages[end] if begin is None else ages[end] - ages[begin])
        rate = burst / duration
        tail = after_reactions / float(ages[after] - ages[end])
        if (burst < MIN_EARLY_DELTA or after_views < 20 or burst / burst_views < .25 or tail > .05 * rate):
            continue
        # Lower the ratio-drop threshold only with additional concentration,
        # scale and observation-density evidence. A mild/long burst still
        # needs the original tenfold ratio drop and is not highest severity.
        first_after = int(np.searchsorted(ages, ages[end] + 1))
        immediate = (max(0, bounds[first_after][1] - bounds[end][0])
                     + withdrawals[first_after+1] - withdrawals[end+1]) / float(ages[first_after] - ages[end])
        concentrated = burst / (burst + after_reactions) >= MIN_PACK_SHARE
        disproportionate = burst >= 3 * burst_views
        required_pack = max(MIN_PACK, MIN_PACK_RATE * duration)
        confirmed = (burst >= required_pack and duration <= MAX_PACK_HOURS
                     and (begin is None or burst >= MIN_SHARE * bounds[begin][1])
                     and (concentrated or disproportionate)
                     and after_views >= burst_views
                     and MIN_RATIO_DROP * after_reactions / after_views <= burst / burst_views
                     and after - end >= 3 and np.max(np.diff(ages[end:after+1])) <= 1.5
                     and ages[first_after] - ages[end] <= 1.5 and immediate <= .1 * rate)
        if not confirmed and (ages[first] >= 6
                              or 10 * after_reactions / after_views > burst / burst_views):
            continue
        formula = (f"прирост реакций ≥ +{number(burst)} при приросте просмотров "
                   f"≤ +{number(burst_views)} за {age_text(duration * HOUR)} с учётом точности счётчиков; "
                   f"затем реакции ≤ +{number(after_reactions)}, просмотры ≥ +{number(after_views)} "
                   f"за {age_text(float(ages[after] - ages[end]) * HOUR)}. "
                   "Время изменений внутри интервалов замеров неизвестно")
        if begin is None:
            formula = (f"уже в первом замере на {age_text(ages[end] * HOUR)}: "
                       f"реакций ≥ {number(burst)}, просмотров ≤ {number(burst_views)}; "
                       f"затем за {age_text(float(ages[after] - ages[end]) * HOUR)} "
                       f"реакции ≤ +{number(after_reactions)}, просмотры ≥ +{number(after_views)} "
                       "с учётом точности счётчиков. Рост до первого замера не наблюдался")
        render = {"kind": "bounded_burst", "mode": "initial_plateau" if begin is None else "early_ratio",
                  "measurementMode": MEASUREMENT_MODE,
                  "burstLower": burst, "burstViewsUpper": burst_views,
                  "afterReactionsUpper": after_reactions, "afterViewsLower": after_views,
                  "beforeRange": list(bounds[first]),
                  "afterRange": list(bounds[after] if begin is None else bounds[end]),
                  "burstRateLower": round(rate, 2), "afterRateUpper": round(tail, 2),
                  "firstAfterRateUpper": round(immediate, 2),
                  "confirmationEndAge": float(ages[after] * HOUR), "timingUnknown": True}
        if withdrawn:
            render["withdrawnReactions"] = withdrawn
        if confirmed:
            render["plateauEvidence"] = CONFIRMED_PLATEAU_MODE
            render["packShareLower"] = round(burst / (burst + after_reactions), 4)
            render["severityReason"] = "concentration" if concentrated else "disproportionate_reactions"
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.REACTIONS,
            min(.99, .9 + .03 * log2(burst / required_pack) + .02 * log2(MAX_PACK_HOURS / duration)) if confirmed else .75,
            float(ages[first] * HOUR), float(ages[after if begin is None else end] * HOUR),
            timedelta(hours=duration), formula, render,
            ("reaction_counter_batch_update", "pinned_post")))
    return signs


def _reported_plateau(prepared, ages, bounds, validity_prefix, withdrawals):
    """Retain an observable rounded-count candidate without claiming certainty.

    Quality, breakdown validity, real readings and correction guards are
    unchanged. Nominal arithmetic is used only to find a candidate; all its
    lower/upper growth claims and highest-severity evidence are discarded.
    """
    series = prepared.series
    if series.is_repost or Metric.VIEWS not in series.values:
        return []
    count = len(ages)
    views = _views(prepared, count)
    nominal_r = [None if bound is None else (value, value)
                 for bound, value in zip(bounds, series.values[Metric.REACTIONS][:count])]
    nominal_v = [None if bound is None else (value, value)
                 for bound, value in zip(views, series.values[Metric.VIEWS][:count])]
    candidates = _decoupled(prepared, ages, nominal_r, validity_prefix, withdrawals, views_override=nominal_v)
    signs = []
    for sign in candidates:
        first = bisect_left(series.observed_at, sign.interval.start)
        last = bisect_left(series.observed_at, sign.interval.end)
        source = sign.render
        initial = source.get('mode') == 'initial_plateau'
        introduction = (f"в первом замере на {age_text(sign.scale.total_seconds())}: {number(source['burstLower'])} реакций"
                        if initial else f"+{number(source['burstLower'])} реакций за {age_text(sign.scale.total_seconds())}")
        formula = (f"По округлённым значениям: {introduction}; затем не более +{number(source['afterReactionsUpper'])} "
                   f"при +{number(source['afterViewsLower'])} просмотрах за 3ч. "
                   "Допуск округления не позволяет подтвердить величину рывка; показан слабый сигнал")
        signs.append(replace(sign, strength=.5, formula=formula, render={
            "kind": "bounded_burst", "measurementMode": MEASUREMENT_MODE,
            "mode": "initial_plateau" if initial else "reported_plateau",
            "roundingLimited": True, "reportedBurst": source['burstLower'],
            "beforeRange": list(bounds[first]), "afterRange": list(bounds[last]),
            "startAge": source['startAge'], "endAge": source['endAge'],
            "confirmationEndAge": source['confirmationEndAge'], "timingUnknown": True}))
    return signs
