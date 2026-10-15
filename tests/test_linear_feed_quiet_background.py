"""Линейная подача после тихого простоя: фон и обрыв — по верхней границе тихих промежутков.

НИЯУ МИФИ ВК №35481, 18.09.2026: пять суток просмотры росли на 1–2 за замер
раз в несколько часов, затем шесть часов ровно ~1 300 в час и снова +1 за
6,5 ч. Ячейки простоя были «пробелом», фона до участка не было, и подача,
очевидная на графике, признака не получала.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence

PUBLISHED = datetime(2026, 9, 12, 3, 5, tzinfo=timezone.utc)
FEED = (143.4, 150.0)


def _post(rate: float) -> PostSeries:
    readings: list[tuple[float, int]] = []
    age = 5 / 60
    while age <= 48:
        readings.append((age, int(3300 * (1 - math.exp(-age / 3)))))
        age += 0.5
    value = readings[-1][1]
    # Простой: сборщик заходит раз в 5–6 часов, счётчик прибавляет по одному.
    for age in (54.0, 60.0, 66.0, 72.0, 78.0, 84.0, 90.0, 96.0, 102.0, 108.0, 119.8, 129.6, 134.6, 137.5, FEED[0]):
        value += 1
        readings.append((age, value))
    age = FEED[0]
    while age + 0.5 <= FEED[1] + 1e-9:
        age += 0.5
        value += int(rate * 0.5)
        readings.append((age, value))
    for age in (156.5, 166.2, 176.0):
        value += 1
        readings.append((age, value))
    observed = tuple(PUBLISHED + timedelta(hours=age) for age, _ in readings)
    views = tuple(value for _, value in readings)
    reactions = tuple(min(9, int(age)) for age, _ in readings)
    return PostSeries(uuid4(), uuid4(), "vk", PUBLISHED, False, observed,
                      {Metric.VIEWS: views, Metric.REACTIONS: reactions})


def _feeds(series: PostSeries):
    verdict = assess(series, analyzed_at=series.observed_at[-1], cadence=CollectionCadence())
    return verdict, [sign for sign in verdict.signs if sign.pattern == 1 and sign.metric is Metric.VIEWS]


def test_feed_after_quiet_idle_is_marked() -> None:
    series = _post(1300)
    verdict, feeds = _feeds(series)
    late = [sign for sign in feeds if (sign.interval.start - series.published_at) >= timedelta(hours=140)]
    assert len(late) == 1 and int(verdict.level) >= 2
    start = (late[0].interval.start - series.published_at).total_seconds() / 3600
    end = (late[0].interval.end - series.published_at).total_seconds() / 3600
    assert 142 <= start <= 145 and 148 <= end <= 151


def test_quiet_idle_without_feed_has_no_sign() -> None:
    _, feeds = _feeds(_post(0))
    assert not feeds
