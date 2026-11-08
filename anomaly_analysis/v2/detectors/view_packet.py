"""Пакет просмотров после второго часа: час с приростом от 15 % итога.

Такой час бывает и у живого поста, поэтому решают реакции внутри него (ADR-019). Если
реакции пришли хотя бы частично, это приток живых людей: продвижение, рекомендации или
репост крупным пабликом, признака нет, и уровень такого поста не растёт. Дневной обрыв —
следующие три часа не больше пятой части темпа пакета в 09–21 по времени аудитории.
Обрыв вместе с расцеплением — выраженный признак. Отсутствие реакций при значимости от 12 —
уровень 3 одним составным признаком, как рывок с плато у реакций.

Пост сравнивается с самим собой, норма аккаунта не участвует.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number
from .view_burst_response import MIN_SURPRISE, SCALE, BurstResponse, burst_response

ID = "view_packet"
VERSION = "1.0.0"
PATTERN = 20
FAMILY = Family.SHAPE
NEEDS_NORM = False
CONFIRMED_MODE = "view_packet_without_response_v1"

VIEW_SHARE = 0.15
AFTER_CELLS = 3
CLIFF_RATIO = 5.0
DAY_HOURS = (9, 21)
MOSCOW_OFFSET = 3 * HOUR
CONFIRMED_SURPRISE = 12.0
PLAIN_STRENGTH = 0.45
PARTIAL_STRENGTH = 0.55
CLIFF_STRENGTH = 0.75
CONFIRMED_STRENGTH = 0.95


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    response = burst_response(prepared, view_share=VIEW_SHARE)
    if response is None or response.outcome != "decoupled":
        return ()
    cliff = _daytime_cliff(prepared, response, context.audience_offset)
    decoupled = response.surprise >= MIN_SURPRISE
    render = {"kind": "view_packet", "outcome": response.outcome, "cliff": cliff, "views": round(response.views),
              "reactions": round(response.reactions), "outsideViews": round(response.outside_views),
              "outsideReactions": round(response.outside_reactions), "responseShare": round(response.share, 3),
              "surprise": round(min(response.surprise, 999.0), 1)}
    if decoupled and response.surprise >= CONFIRMED_SURPRISE:
        strength = CONFIRMED_STRENGTH
        render["plateauEvidence"] = CONFIRMED_MODE
    elif decoupled and cliff:
        strength = CLIFF_STRENGTH
    else:
        strength = PARTIAL_STRENGTH if decoupled or cliff else PLAIN_STRENGTH
    formula = (f"+{number(response.views)} просмотров за t ∈ [{age_text(response.start_age)}; "
               f"{age_text(response.end_age)}] ({response.views / max(response.reference_views, 1.0):.0%} просмотров поста), "
               f"{response.inside_per_thousand:.1f} реакций на 1 000 новых просмотров при "
               f"{response.outside_per_thousand:.1f} вне пакета"
               + ("; следующие три часа — меньше пятой части темпа пакета" if cliff else ""))
    return (make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, strength, response.start_age, response.end_age, SCALE,
                      formula, render, ("paid_promotion", "recommendation_wave", "site_embed", "mailing_link")),)


def _daytime_cliff(prepared: PreparedSeries, response: BurstResponse, audience_offset: int | None) -> bool:
    if audience_offset is None:
        return False
    grid = prepared.metrics[Metric.VIEWS].grids[SCALE]
    first = int(np.searchsorted(grid.edges, response.end_age))
    cells = range(first, first + AFTER_CELLS)
    if cells[-1] >= grid.usable.size or not grid.usable[list(cells)].all():
        return False
    hours = (response.end_age - response.start_age) / HOUR
    after = float(grid.cumulative[cells[-1] + 1] - grid.cumulative[first]) / AFTER_CELLS
    if after > response.views / hours / CLIFF_RATIO:
        return False
    instant = prepared.series.published_at + timedelta(seconds=response.end_age)
    clock = int((instant.timestamp() + MOSCOW_OFFSET) % 86400 // HOUR)
    return DAY_HOURS[0] <= (clock + audience_offset) % 24 <= DAY_HOURS[1]
