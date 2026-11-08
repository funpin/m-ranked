"""Всплеск просмотров без отклика: новые зрители всплеска не реагируют так, как читатели поста.

Живой приток — реклама, рекомендации, репост крупным пабликом — приводит людей,
которые реагируют примерно в той же пропорции. У пакета просмотров реакций внутри
всплеска почти нет. Сравнение идёт с самим постом вне всплеска, поэтому регулярная
подача не становится «нормой канала».

ВК 01.09–07.11.2026 (23 тыс. постов от 200 просмотров): при доле ≤ 20 % и значимости
от 4 — 253 поста, 89 % у шести аккаунтов; у постов с продвижением и органики эталона —
ни одного. Реклама и рекомендации дают всплеск со сцепленными реакциями: это контекст
для находки аккаунта, в уровень он не входит.

Нулевая гипотеза биномиальная: реакции в часы всплеска приходят с той же долей, что и
у поста вне них. Сила — по −log₁₀ p, как у признака 14. Реакции считаются в те же часы,
без запаса на задержку: следующий час вернул бы реакции обычной аудитории поста.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math

import numpy as np
from scipy.stats import binom

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries, views_ratio_unreliable
from .base import DetectorContext, age_text, make_sign, number

ID = "view_burst_response"
VERSION = "1.0.0"
PATTERN = 19
FAMILY = Family.CROSS_METRIC
NEEDS_NORM = False
MODE = "view_burst_response_v1"
# Пороги проверены только на эталоне ВК; просмотры по внешней ссылке на RuTube — норма площадки.
PLATFORMS = frozenset({"vk"})

SCALE = timedelta(hours=1)
# Первые два часа — обычный первый охват подписчиков.
MIN_AGE = 2 * HOUR
HORIZON = 72 * HOUR
MIN_VIEWS = 200
VIEW_SHARE = 0.20
MIN_OUTSIDE_VIEWS = 100
DECOUPLED = 0.20
COUPLED = 0.50
# −log₁₀ p → сила. Подтверждённого уровня здесь нет: составной признак — этап формы.
STRENGTHS = ((10.0, 0.75), (6.0, 0.55), (4.0, 0.45))


@dataclass(frozen=True, slots=True)
class BurstResponse:
    start_age: float
    end_age: float
    views: float
    reactions: float
    outside_views: float
    outside_reactions: float
    reference_views: float
    share: float
    surprise: float

    @property
    def outcome(self) -> str:
        if self.share <= DECOUPLED:
            return "decoupled"
        return "coupled" if self.share >= COUPLED else "intermediate"

    @property
    def inside_per_thousand(self) -> float:
        return 1000 * self.reactions / max(self.views, 1.0)

    @property
    def outside_per_thousand(self) -> float:
        return 1000 * self.outside_reactions / max(self.outside_views, 1.0)


def burst_response(prepared: PreparedSeries) -> BurstResponse | None:
    """Самый крупный всплеск просмотров в первые трое суток; None — его нет или не с чем сравнить."""
    if prepared.series.platform not in PLATFORMS:
        return None
    views, reactions = prepared.metrics.get(Metric.VIEWS), prepared.metrics.get(Metric.REACTIONS)
    if views is None or reactions is None or views_ratio_unreliable(prepared.series):
        return None
    view_grid, reaction_grid = views.grids.get(SCALE), reactions.grids.get(SCALE)
    if view_grid is None or reaction_grid is None:
        return None
    edges, view_index, reaction_index = np.intersect1d(view_grid.edges, reaction_grid.edges, return_indices=True)
    if edges.size < 2:
        return None
    reference_views = float(np.interp(min(HORIZON, views.ages[-1]), views.ages, views.values))
    reference_reactions = float(np.interp(min(HORIZON, reactions.ages[-1]), reactions.ages, reactions.values))
    view_cumulative, reaction_cumulative = view_grid.cumulative[view_index], reaction_grid.cumulative[reaction_index]
    cells = view_index[:-1], reaction_index[:-1]
    usable = (view_grid.usable[cells[0]] & reaction_grid.usable[cells[1]]
              & ~view_grid.negative[cells[0]] & ~reaction_grid.negative[cells[1]])
    growth = np.diff(view_cumulative)
    hot = (usable & (edges[:-1] >= MIN_AGE) & (edges[:-1] < HORIZON)
           & (growth >= max(MIN_VIEWS, VIEW_SHARE * reference_views)))
    bounds = np.flatnonzero(np.diff(np.concatenate(([0], hot.astype(np.int8), [0]))))
    if not bounds.size:
        return None
    begin, end = max(zip(bounds[::2], bounds[1::2]), key=lambda run: float(growth[run[0]:run[1]].sum()))
    inside_views = float(growth[begin:end].sum())
    inside_reactions = max(0.0, float(reaction_cumulative[end] - reaction_cumulative[begin]))
    outside_views = max(0.0, reference_views - inside_views)
    outside_reactions = max(0.0, reference_reactions - inside_reactions)
    if outside_views < MIN_OUTSIDE_VIEWS:
        return None
    outside_rate = (outside_reactions + 0.5) / (outside_views + 1.0)
    share = (inside_reactions / inside_views) / outside_rate
    log_p = float(binom.logcdf(round(inside_reactions), round(inside_views), min(outside_rate, 0.999)))
    return BurstResponse(float(edges[begin]), float(edges[end]), inside_views, inside_reactions, outside_views,
                         outside_reactions, reference_views, float(share), -log_p / math.log(10))


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    response = burst_response(prepared)
    if response is None or response.outcome != "decoupled":
        return ()
    strength = next((value for surprise, value in STRENGTHS if response.surprise >= surprise), None)
    if strength is None:
        return ()
    formula = (f"+{number(response.views)} просмотров за t ∈ [{age_text(response.start_age)}; "
               f"{age_text(response.end_age)}] ({response.views / max(response.reference_views, 1.0):.0%} просмотров поста): "
               f"{response.inside_per_thousand:.1f} реакций на 1 000 новых просмотров при "
               f"{response.outside_per_thousand:.1f} у поста вне всплеска, −log₁₀ p = {response.surprise:.1f}")
    render = {"kind": "view_burst", "outcome": response.outcome, "views": round(response.views),
              "reactions": round(response.reactions), "outsideViews": round(response.outside_views),
              "outsideReactions": round(response.outside_reactions), "responseShare": round(response.share, 3),
              "surprise": round(min(response.surprise, 999.0), 1), "mode": MODE}
    return (make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, strength, response.start_age, response.end_age, SCALE,
                      formula, render, ("paid_promotion", "recommendation_wave", "site_embed", "wide_reach_low_engagement")),)
