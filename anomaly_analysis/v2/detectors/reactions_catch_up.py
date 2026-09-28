"""Exploratory low conditional dispersion on actual nonoverlapping read pairs.

Interpolation can manufacture low dispersion; finite audiences can also be
underdispersed. The suffix statistic is a heuristic, not a calibrated organic
null test. Until model-based validation, this pattern is at most weak.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from scipy.stats import chi2

from ..domain import Family, Metric, Sign
from ..norms import ERV
from ..series import DAY, PointFlag, PreparedSeries
from .base import DetectorContext, age_text, expected_step, make_sign

ID = "reactions_catch_up"
VERSION = "2.1.0"
PATTERN = 5
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = True

SCALE = timedelta(hours=6)
# Research window; no universal claim about how organic ER ages.
MIN_AGE = 3 * DAY
MIN_WINDOWS = 8
MIN_VIEWS_PER_WINDOW = 20
MIN_REACTIONS = 30
# Exploratory suffix thresholds, without a calibrated account/post error rate.
MAX_DISPERSION = 0.5
MAX_P_VALUE = 1e-4
# Доля держится у ERV поста: не дальше чем втрое от доли реакций на трёх сутках.
RATIO_RANGE = 3.0
# Посты-«вечнозелёнки» живут поздним трафиком: если норма аккаунта не
# показывает падения ERV с возрастом, признак не выше слабого.
EVERGREEN_CAP = 0.4
EXPLORATORY_CAP = 0.45


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if prepared.series.is_repost or reactions is None or views is None or views.source_counter:
        return ()
    # Aggregate nonoverlapping actual read pairs. Splitting a six-hour change
    # across an interpolated grid halves variance and correlates neighbors.
    common, ri, vi = np.intersect1d(reactions.ages, views.ages, return_indices=True)
    starts, ends, rr, vv = [], [], [], []
    left = int(np.searchsorted(common, MIN_AGE))
    seconds = SCALE.total_seconds()
    while left < common.size:
        right = int(np.searchsorted(common, common[left] + seconds))
        if right >= common.size:
            break
        duration = common[right] - common[left]
        # Net recovery after an observed counter correction is not a count
        # of independent reaction arrivals, even if both endpoints increased.
        invalid = int(PointFlag.NEGATIVE_DELTA | PointFlag.COUNTER_RESET | PointFlag.MISSING)
        corrected = (np.any(reactions.flags[ri[left] + 1:ri[right] + 1] & invalid)
                     or np.any(views.flags[vi[left] + 1:vi[right] + 1] & invalid))
        dr = reactions.values[ri[right]] - reactions.values[ri[left]]
        dv = views.values[vi[right]] - views.values[vi[left]]
        if (not corrected and duration <= 1.25 * seconds and dr >= 0 and dv >= MIN_VIEWS_PER_WINDOW
                and expected_step(prepared, common[[left, right]]).max() <= seconds):
            starts.append(common[left]); ends.append(common[right])
            rr.append(dr); vv.append(dv)
        left = right
    dr, dv, first, last = map(np.asarray, (rr, vv, starts, ends))
    if dr.size < MIN_WINDOWS or dr.sum() < MIN_REACTIONS:
        return ()
    found = _segment(dr, dv)
    if found is None:
        return ()
    begin, ratio, dispersion = found
    dr, dv, first, last = dr[begin:], dv[begin:], first[begin:], last[begin:]
    post_ratio = float(np.interp(first[0], reactions.ages, reactions.values)
                       / max(np.interp(first[0], views.ages, views.values), 1.0))
    if not post_ratio / RATIO_RANGE <= ratio <= post_ratio * RATIO_RANGE:
        return ()
    strength = 0.5 + 0.5 * min(1.0, (MAX_DISPERSION - dispersion) / 0.4)
    strength = min(strength, EXPLORATORY_CAP)
    alternatives = ("evergreen_post", "conditional_count_variation")
    if context.norm is not None:
        early, late = context.norm.cells.get((ERV, 1)), context.norm.cells.get((ERV, 3))
        if early and late and early.log_erv and late.log_erv and late.log_erv.median >= early.log_erv.median:
            strength = min(strength, EVERGREEN_CAP)
    start_age, end_age = float(first[0]), float(last[-1])
    formula = (f"Δреакции/Δпросмотры = {ratio:.3f} в {dr.size} окнах около 6 ч, разброс {dispersion:.2f} "
               f"от пуассоновского ориентира, доля поста {post_ratio:.3f}, "
               f"t ∈ [{age_text(start_age)}; {age_text(end_age)}]")
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age, SCALE, formula,
                      {"kind": "ratio", "ratio": round(ratio, 4), "dispersion": round(dispersion, 3),
                       "postRatio": round(post_ratio, 4), "windows": int(dr.size), "observationMode": "actual_nonoverlapping_pairs"},
                      alternatives, context.norm_confidence),)


def _segment(dr: np.ndarray, dv: np.ndarray) -> tuple[int, float, float] | None:
    """Самый длинный участок «от окна до конца» с недоразбросом вокруг одной доли.

    Для участка D = Σ(Δr − qΔv)²/(qΔv) = Σ(Δr²/Δv)/q − ΣΔr при q = ΣΔr/ΣΔv,
    поэтому все участки считаются суффиксными суммами без цикла.
    """
    reactions = np.cumsum(dr[::-1])[::-1]
    views = np.cumsum(dv[::-1])[::-1]
    squares = np.cumsum((dr * dr / dv)[::-1])[::-1]
    count = np.arange(dr.size, 0, -1)
    usable = (count >= MIN_WINDOWS) & (reactions >= MIN_REACTIONS)
    ratio = np.divide(reactions, views, out=np.zeros_like(reactions), where=views > 0)
    statistic = np.divide(squares, ratio, out=np.full_like(squares, np.inf), where=ratio > 0) - reactions
    dispersion = statistic / np.maximum(count - 1, 1)
    p_value = chi2.cdf(statistic, np.maximum(count - 1, 1))
    hits = np.flatnonzero(usable & (dispersion <= MAX_DISPERSION) & (p_value <= MAX_P_VALUE))
    if not hits.size:
        return None
    begin = int(hits[0])
    return begin, float(ratio[begin]), float(dispersion[begin])
