"""Поздний старт охвата: к шестому часу меньше 5 % просмотров, набранных к трём суткам.

Одинаково встречается у платного продвижения записи, рекомендаций ВК и пакетов просмотров.
Признаком становится только вместе со всплеском без отклика (ADR-019): с живыми реакциями
это причина для находки о продвижении, а не уровень поста. Сравнивается только форма самого поста.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, make_sign, number
from .view_burst_response import MIN_SURPRISE, PLATFORMS, burst_response

ID = "view_late_start"
VERSION = "1.0.0"
PATTERN = 21
FAMILY = Family.SHAPE
NEEDS_NORM = False

EARLY_AGE = 6 * HOUR
HORIZON = 72 * HOUR
EARLY_SHARE = 0.05
MIN_VIEWS = 2_000
# Значение к шестому часу известно, только если рядом есть настоящие замеры.
MAX_EARLY_DISTANCE = 2 * HOUR
STRENGTH = 0.75
SCALE = timedelta(hours=6)


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    views = prepared.metrics.get(Metric.VIEWS)
    if prepared.series.platform not in PLATFORMS or views is None or views.ages[-1] < HORIZON:
        return ()
    if float(np.abs(views.ages - EARLY_AGE).min()) > MAX_EARLY_DISTANCE:
        return ()
    early = float(np.interp(EARLY_AGE, views.ages, views.values))
    total = float(np.interp(HORIZON, views.ages, views.values))
    if total < MIN_VIEWS or early >= EARLY_SHARE * total:
        return ()
    response = burst_response(prepared)
    if response is None or response.outcome != "decoupled" or response.surprise < MIN_SURPRISE:
        return ()
    formula = (f"к 6 ч {number(early)} просмотров — {early / total:.1%} от {number(total)} к 72 ч; "
               "основной приток пришёл почти без реакций")
    return (make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, STRENGTH, 0.0, response.end_age, SCALE, formula,
                      {"kind": "late_start", "earlyViews": round(early), "totalViews": round(total),
                       "earlyShare": round(early / total, 4)},
                      ("paid_promotion", "recommendation_wave", "news_event", "site_embed")),)
