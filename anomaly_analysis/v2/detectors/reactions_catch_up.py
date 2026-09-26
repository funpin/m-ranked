"""Реакции «догоняют» просмотры на старых постах.

Живые реакции на старом посте — редкие независимые события: их число по
окнам разбросано не меньше пуассоновского. Подача, подгоняющая реакции под
приросты просмотров, даёт почти постоянное Δреакций/Δпросмотров — разброс
вокруг этой доли заметно меньше пуассоновского. Недоразброс органике не
свойственен, поэтому индекс дисперсии и есть статистика признака.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from scipy.stats import chi2

from ..domain import Family, Metric, Sign
from ..norms import ERV
from ..series import DAY, PreparedSeries
from .base import DetectorContext, age_text, expected_step, make_sign

ID = "reactions_catch_up"
VERSION = "2.0.0"
PATTERN = 5
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = True

SCALE = timedelta(hours=6)
# После трёх суток у органики доля реакций на прирост просмотров уже падает.
MIN_AGE = 3 * DAY
MIN_WINDOWS = 8
MIN_VIEWS_PER_WINDOW = 20
MIN_REACTIONS = 30
# Индекс дисперсии живых реакций около единицы. Признак — вдвое меньше и
# притом с хвостом хи-квадрата не выше 1e-4: участков-кандидатов (от каждого
# окна до конца ряда) до нескольких десятков, и порог держит общую ошибку
# в пределах десятых долей процента.
MAX_DISPERSION = 0.5
MAX_P_VALUE = 1e-4
# Доля держится у ERV поста: не дальше чем втрое от доли реакций на трёх сутках.
RATIO_RANGE = 3.0
# Посты-«вечнозелёнки» живут поздним трафиком: если норма аккаунта не
# показывает падения ERV с возрастом, признак не выше слабого.
EVERGREEN_CAP = 0.4


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    reactions, views = prepared.metrics.get(Metric.REACTIONS), prepared.metrics.get(Metric.VIEWS)
    if prepared.series.is_repost or reactions is None or views is None or views.source_counter:
        return ()
    r_grid, v_grid = reactions.grids.get(SCALE), views.grids.get(SCALE)
    if r_grid is None or v_grid is None or r_grid.rates.size == 0:
        return ()
    starts = r_grid.edges[:-1]
    if not np.array_equal(starts, v_grid.edges[:-1]):
        return ()
    dr, dv = np.diff(r_grid.cumulative), np.diff(v_grid.cumulative)
    keep = (r_grid.usable & v_grid.usable & (starts >= MIN_AGE) & (dv >= MIN_VIEWS_PER_WINDOW)
            & (expected_step(prepared, starts) <= SCALE.total_seconds()))
    if keep.sum() < MIN_WINDOWS or dr[keep].sum() < MIN_REACTIONS:
        return ()
    dr, dv, first = dr[keep], dv[keep], starts[keep]
    found = _segment(dr, dv)
    if found is None:
        return ()
    begin, ratio, dispersion = found
    dr, dv, first = dr[begin:], dv[begin:], first[begin:]
    post_ratio = float(np.interp(first[0], reactions.ages, reactions.values)
                       / max(np.interp(first[0], views.ages, views.values), 1.0))
    if not post_ratio / RATIO_RANGE <= ratio <= post_ratio * RATIO_RANGE:
        return ()
    strength = 0.5 + 0.5 * min(1.0, (MAX_DISPERSION - dispersion) / 0.4)
    alternatives = ("evergreen_post",)
    if context.norm is not None:
        early, late = context.norm.cells.get((ERV, 1)), context.norm.cells.get((ERV, 3))
        if early and late and early.log_erv and late.log_erv and late.log_erv.median >= early.log_erv.median:
            strength = min(strength, EVERGREEN_CAP)
    start_age, end_age = float(first[0]), float(first[-1] + SCALE.total_seconds())
    formula = (f"Δреакции/Δпросмотры = {ratio:.3f} в {dr.size} окнах по 6 ч, разброс {dispersion:.2f} "
               f"от пуассоновского (у живых реакций ≈ 1), доля поста {post_ratio:.3f}, "
               f"t ∈ [{age_text(start_age)}; {age_text(end_age)}]")
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age, SCALE, formula,
                      {"kind": "ratio", "ratio": round(ratio, 4), "dispersion": round(dispersion, 3),
                       "postRatio": round(post_ratio, 4), "windows": int(dr.size)},
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
