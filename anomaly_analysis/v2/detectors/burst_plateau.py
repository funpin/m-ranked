"""Рывок, обрывающийся в плато без степенного хвоста.

Фермы доставляют сотни реакций за 2–4 часа и замолкают (De Cristofaro и др.,
2014): после рывка скорость сразу возвращается к затухшему фону. Живая волна,
даже от внешнего толчка, затухает степенно — в следующий час она ещё
приносит заметную долю пиковой скорости.

Первые шесть часов фона для сравнения нет, и там рывок судится относительно
просмотров: живые реакции идут вместе с просмотрами, а доставленная пачка
приходит разом и обрывается, хотя зрители продолжают прибывать.
"""
from __future__ import annotations

from datetime import timedelta
from bisect import bisect_right
from math import log2

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number
from .bounded_reaction_burst import _candidate_pairs, _views

ID = "burst_plateau"
VERSION = "2.3.0"
PATTERN = 9
FAMILY = Family.SHAPE
NEEDS_NORM = False
RAPID_VIEW_MODE = "rapid_view_plateau_v1"
VIEW_MEASUREMENT_MODE = "bounded_view_counts_v1"

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

# Ранний режим: рывок реакций в первые часы, оторванный от просмотров.
EARLY_SCALE = timedelta(minutes=15)
EARLY_MAX_BURST = 8              # клеток по 15 минут — два часа
EARLY_AFTER = 12                 # три часа после рывка
EARLY_MIN_BURST_RATIO = 0.25     # реакций на просмотр в рывке
EARLY_MIN_DROP = 10.0            # во столько раз реже реакции на просмотр после
EARLY_MIN_AFTER_VIEWS = 20       # зрители после рывка продолжают приходить


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    signs = list(_rapid_views(prepared))
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        if data is None or data.source_counter:
            continue
        grid = data.grids.get(SCALE)
        if grid is None or grid.rates.size < BACKGROUND_HOURS + AFTER_HOURS + 1:
            continue
        rates = grid.rates * HOUR
        usable = grid.usable
        floors = _floors(rates, usable)
        candidates = usable & (grid.edges[:-1] >= MIN_ONSET_AGE) & (rates >= BURST_FACTOR * floors)
        candidates[:BACKGROUND_HOURS] = False
        candidates[rates.size - AFTER_HOURS:] = False
        resume = 0
        for index in np.flatnonzero(candidates):
            # Ячейки уже разобранного рывка не начинают новый.
            if index < resume:
                continue
            floor = float(floors[index])
            end = index
            while end < rates.size and usable[end] and rates[end] >= BURST_FACTOR * floor:
                end += 1
            sign = _judge(prepared, metric, grid, rates, usable, index, end, floor)
            if sign is not None:
                signs.append(sign)
            resume = end
    early = _early(prepared)
    if early is not None and not any(sign.metric is Metric.REACTIONS
                                     and sign.interval.start <= early.interval.end
                                     and early.interval.start <= sign.interval.end for sign in signs):
        signs.append(early)
    return tuple(signs)


def _early(prepared: PreparedSeries) -> Sign | None:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if reactions is None or views is None or views.source_counter:
        return None
    # Anchor to the first actual readings, never an invented publication-time
    # zero. A pack already present there is checked by the endpoint detector.
    width = EARLY_SCALE.total_seconds()
    first = max(float(reactions.ages[0]), float(views.ages[0]))
    last = min(float(reactions.ages[-1]), float(views.ages[-1]))
    edges = np.arange(first, last + .001, width)
    if edges.size < EARLY_AFTER + 3:
        return None
    r_cum = np.interp(edges, reactions.ages, reactions.values)
    v_cum = np.interp(edges, views.ages, views.values)
    usable = ~(_touches_gap(edges, reactions) | _touches_gap(edges, views))
    r_rate, v_rate = np.diff(r_cum), np.diff(v_cum)
    early = np.flatnonzero((edges[:-1] < MIN_ONSET_AGE) & usable)
    if not early.size:
        return None
    common = edges
    peak_at = int(early[np.argmax(r_rate[early])])
    peak = float(r_rate[peak_at])
    if peak <= 0:
        return None
    begin, end = peak_at, peak_at + 1
    while begin > 0 and usable[begin - 1] and r_rate[begin - 1] >= BODY_SHARE * peak:
        begin -= 1
    while end < r_rate.size and usable[end] and r_rate[end] >= BODY_SHARE * peak:
        end += 1
    after = slice(end, end + EARLY_AFTER)
    if end - begin > EARLY_MAX_BURST or end + EARLY_AFTER > r_rate.size or not usable[after].all():
        return None
    burst_r, burst_v = float(r_cum[end] - r_cum[begin]), float(v_cum[end] - v_cum[begin])
    after_r, after_v = float(r_rate[after].sum()), float(v_rate[after].sum())
    if burst_r < MIN_DELTA[Metric.REACTIONS] or after_v < EARLY_MIN_AFTER_VIEWS:
        return None
    burst_ratio = burst_r / max(burst_v, 1.0)
    after_ratio = after_r / after_v
    tail_share = float(r_rate[after].mean()) / peak
    if (burst_ratio < EARLY_MIN_BURST_RATIO or after_ratio * EARLY_MIN_DROP > burst_ratio
            or tail_share > MAX_AFTER_SHARE):
        return None
    drop = burst_ratio / max(after_ratio, 1e-3)
    strength = min(1.0, 0.6 + 0.4 * min(1.0, (drop - EARLY_MIN_DROP) / (4 * EARLY_MIN_DROP)))
    start_age, end_age = float(common[begin]), float(common[end])
    formula = (f"+{number(burst_r)} реакций при +{number(burst_v)} просмотрах за {age_text(end_age - start_age)} "
               f"(t ∈ [{age_text(start_age)}; {age_text(end_age)}], {burst_ratio:.0%} на просмотр), "
               f"затем +{number(after_r)} при +{number(after_v)} за 3ч ({after_ratio:.1%})")
    return make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age, EARLY_SCALE,
                     formula, {"kind": "ratio", "mode": "early_plateau", "burst": round(burst_r), "burstViews": round(burst_v),
                               "afterReactions": round(after_r), "afterViews": round(after_v),
                               "drop": round(drop, 1)},
                     ("pinned_post",))


def _floors(rates: np.ndarray, usable: np.ndarray) -> np.ndarray:
    """Фон каждой ячейки — медиана пригодных скоростей шести предыдущих, не ниже 1/ч."""
    floors = np.full(rates.size, np.inf)
    if rates.size <= BACKGROUND_HOURS:
        return floors
    masked = np.where(usable, rates, np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(masked, BACKGROUND_HOURS)[:-1]
    counts = np.sum(~np.isnan(windows), axis=1)
    medians = np.full(windows.shape[0], np.inf)
    filled = counts > 0
    if filled.any():
        medians[filled] = np.nanmedian(windows[filled], axis=1)
    floors[BACKGROUND_HOURS:] = np.maximum(medians, 1.0)
    return floors


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


def _rapid_views(prepared: PreparedSeries) -> tuple[Sign, ...]:
    """Large short late view bursts with observed abrupt plateau.

    The initial audience ramp has no comparable pre-burst background and is
    deliberately ineligible. No norm or guessed points are used.
    """
    series = prepared.series
    if series.is_repost or Metric.VIEWS not in series.values:
        return ()
    count = bisect_right(series.observed_at, prepared.analyzed_at)
    rows = series.values[Metric.VIEWS][:count]
    if count < 5 or max((value or 0 for value in rows), default=0) < 500:
        return ()
    ages = np.array([(at - series.published_at).total_seconds() / HOUR for at in series.observed_at[:count]])
    bounds = _views(prepared, count)
    candidates = tuple(_candidate_pairs(ages, bounds, (0, 1/6, .25, .5), max_duration=.5, min_age=6, min_delta=500))
    if not candidates:
        return ()
    bad = np.array([bound is None for bound in bounds], dtype=int)
    for i in range(1, count):
        if rows[i] is not None and rows[i-1] is not None and rows[i] < rows[i-1]:
            bad[i] = 1
    prefix = np.r_[0, np.cumsum(bad)]
    signs = []
    for begin, end in candidates:
        before = int(np.searchsorted(ages, ages[begin] - 6, side="right")) - 1
        after = int(np.searchsorted(ages, ages[end] + 3))
        if (before < 0 or after >= count or ages[begin] - ages[before] > 7
                or ages[after] - ages[end] > 4 or prefix[after+1] != prefix[before]):
            continue
        low, high = bounds[begin], bounds[end]
        burst = high[0] - low[1]
        duration = float(ages[end] - ages[begin])
        if burst < max(500, .5 * low[1]):
            continue
        rate = burst / duration
        background = max(max(0, bounds[i][1] - bounds[i-1][0]) / float(ages[i] - ages[i-1])
                         for i in range(before+1, begin+1))
        tail = max(0, bounds[after][1] - high[0]) / float(ages[after] - ages[end])
        first_after = int(np.searchsorted(ages, ages[end] + 1))
        immediate = max(0, bounds[first_after][1] - high[0]) / float(ages[first_after] - ages[end])
        if (rate < 30 * max(background, 1) or max(tail, immediate) > .02 * rate
                or after - end < 3 or ages[first_after] - ages[end] > 1.5
                or np.max(np.diff(ages[end:after+1])) > 1.5):
            continue
        formula = (f"просмотры: прирост ≥ +{number(burst)} за {age_text(duration * HOUR)} "
                   f"(не менее {burst / max(low[1], 1):.0%} прежнего значения); "
                   f"скорость ≥ {number(rate)}/ч, до скачка ≤ {number(background)}/ч, "
                   f"в первый час после ≤ {number(immediate)}/ч, за следующие 3ч ≤ {number(tail)}/ч. "
                   "Границы учитывают точность счётчиков; время изменений между замерами неизвестно")
        signs.append(make_sign(
            PATTERN, FAMILY, prepared, Metric.VIEWS,
            min(.99, .9 + .03 * log2(burst / 500) + .02 * log2(.5 / duration)),
            float(ages[begin] * HOUR), float(ages[end] * HOUR), timedelta(hours=duration), formula,
            {"kind": "bounded_burst", "measurementMode": VIEW_MEASUREMENT_MODE,
             "plateauEvidence": RAPID_VIEW_MODE, "burstLower": burst,
             "burstRateLower": round(rate, 2), "backgroundRateUpper": round(background, 2),
             "afterRateUpper": round(tail, 2), "firstAfterRateUpper": round(immediate, 2),
             "beforeRange": list(low), "afterRange": list(high),
             "confirmationEndAge": float(ages[after] * HOUR), "timingUnknown": True},
            ("counter_update_delay", "forward_by_large_channel", "counter_frozen")))
    return tuple(signs)


def _touches_gap(edges: np.ndarray, data) -> np.ndarray:
    """Ячейки, задевающие пробел в замерах метрики."""
    touched = np.zeros(edges.size - 1, dtype=bool)
    for gap in data.gaps:
        touched |= (edges[:-1] < gap.end_age) & (edges[1:] > gap.start_age)
    return touched
