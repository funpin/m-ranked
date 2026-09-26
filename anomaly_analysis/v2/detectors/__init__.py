"""Детекторы v2, по модулю на паттерн.

Паттерна 3 здесь нет: «скачок только на другом масштабе» — это паттерны 1, 2
и 4, найденные на одном из масштабов и помеченные этим масштабом.
"""
from __future__ import annotations

from . import (
    burst_plateau, erv_outlier, gap_growth, late_spike, linear_feed, reactions_before_views,
    reactions_catch_up, reactions_exceed_views, synchronous_rise,
)
from .base import Detector, DetectorContext, SiblingActivity

# Абсолютные детекторы (без нормы) и детекторы относительно нормы держатся
# раздельно: первые обязаны отработать до расчёта нормы — помеченное ими в
# норму не попадает.
ABSOLUTE_DETECTORS = (linear_feed, reactions_before_views, reactions_exceed_views,
                      synchronous_rise, burst_plateau)
NORM_RELATIVE_DETECTORS = (late_spike, gap_growth, reactions_catch_up, erv_outlier)
# Счётчик просмотров репоста принадлежит источнику: остаются только проверки,
# которым безразлично, чья это аудитория.
REPOST_DETECTORS = (reactions_before_views, reactions_exceed_views)

__all__ = ["ABSOLUTE_DETECTORS", "Detector", "DetectorContext", "NORM_RELATIVE_DETECTORS",
           "REPOST_DETECTORS", "SiblingActivity"]
