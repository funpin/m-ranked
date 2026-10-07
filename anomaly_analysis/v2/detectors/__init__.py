"""Детекторы v2, по модулю на паттерн.

Паттерна 3 здесь нет: «скачок только на другом масштабе» — это паттерны 1, 2
и 4, найденные на одном из масштабов и помеченные этим масштабом.
"""
from __future__ import annotations

from . import (
    bounded_reaction_burst, burst_plateau, engagement_regime, erv_outlier, gap_growth, joint_cliff, late_engagement,
    late_spike, linear_feed, reaction_write_off, reactions_before_views, reactions_catch_up, reactions_exceed_views,
    synchronous_rise,
)
from .base import Detector, DetectorContext, SiblingActivity

# Абсолютные детекторы (без нормы) и детекторы относительно нормы держатся
# раздельно: первые обязаны отработать до расчёта нормы — помеченное ими в
# норму не попадает.
ABSOLUTE_DETECTORS = (linear_feed, reactions_before_views, reactions_exceed_views,
                      synchronous_rise, burst_plateau, bounded_reaction_burst, late_engagement,
                      engagement_regime, reaction_write_off, joint_cliff)
NORM_RELATIVE_DETECTORS = (late_spike, gap_growth, reactions_catch_up, erv_outlier)
# Репост: просмотры собственные (series.views_belong_to_source), но содержание
# чужое, а нормы и поздний отклик строятся без репостов. Остаются проверки,
# которые сравнивают пост с самим собой.
REPOST_DETECTORS = (linear_feed, burst_plateau, bounded_reaction_burst, reactions_before_views,
                    reactions_exceed_views, engagement_regime, reaction_write_off, joint_cliff)

__all__ = ["ABSOLUTE_DETECTORS", "Detector", "DetectorContext", "NORM_RELATIVE_DETECTORS",
           "REPOST_DETECTORS", "SiblingActivity"]
