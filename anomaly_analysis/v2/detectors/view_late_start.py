"""Поздний старт охвата: к шестому часу меньше 5 % просмотров, набранных к трём суткам.

Одинаково встречается у платного продвижения записи и у пакетов просмотров, поэтому
сам по себе — слабый сигнал. Выраженным его делает всплеск без отклика: реакции в нём
почти не приходят. Сравнивается только форма самого поста.
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
WEAK_STRENGTH = 0.45
STRONG_STRENGTH = 0.75
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
    decoupled = response is not None and response.outcome == "decoupled" and response.surprise >= MIN_SURPRISE
    end_age = response.end_age if decoupled else EARLY_AGE
    formula = (f"к 6 ч {number(early)} просмотров — {early / total:.1%} от {number(total)} к 72 ч"
               + ("; основной приток пришёл почти без реакций" if decoupled else ""))
    return (make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, STRONG_STRENGTH if decoupled else WEAK_STRENGTH, 0.0,
                      end_age, SCALE, formula,
                      {"kind": "late_start", "earlyViews": round(early), "totalViews": round(total),
                       "earlyShare": round(early / total, 4), "decoupled": decoupled},
                      ("paid_promotion", "recommendation_wave", "news_event", "site_embed")),)
