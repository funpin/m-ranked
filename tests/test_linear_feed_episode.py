"""Линейная подача показывается на весь эпизод, в том числе сквозь «1,2K» Telegram.

Случай МИСИС в Telegram (01.10.2026): ровно ~1 200 просмотров в час с 6-го по
40-й час, днём и ночью, реакции почти не растут. Признак закрывал только 6–12 ч,
а синтетическая копия не получала его вовсе: ступенька по коридору бралась от
среднего за шесть часов до участка, куда входил крутой старт поста.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence

PUBLISHED = datetime(2026, 10, 1, 10, 7, tzinfo=timezone.utc)


def _display(value: float) -> tuple[int, str]:
    """Как Telegram: точно до тысячи, дальше три значащие цифры с отбрасыванием."""
    if value < 1000:
        return int(value), "exact"
    step = 10 if value < 10_000 else 100 if value < 100_000 else 1000
    return int(value // step * step), "rounded"


def _post(rate: float, feed: tuple[float, float] = (6.0, 40.0)) -> PostSeries:
    observed, views, reactions, qualities = [], [], [], []
    age = 5 / 60
    while age <= 72:
        organic = 3000 * (1 - math.exp(-age / 2)) + 150 * math.log1p(age)
        value, quality = _display(organic + rate * (min(max(age, feed[0]), feed[1]) - feed[0]))
        observed.append(PUBLISHED + timedelta(hours=age))
        views.append(max(value, views[-1]) if views else value)
        qualities.append(quality)
        reactions.append(int(25 * (1 - math.exp(-age / 0.5))))
        age += (5 if age < 24 else 15) / 60
    return PostSeries(uuid4(), uuid4(), "telegram", PUBLISHED, False, tuple(observed),
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)},
                      qualities={Metric.VIEWS: tuple(qualities), Metric.REACTIONS: ("exact",) * len(views)})


def _hours(series: PostSeries, sign) -> tuple[float, float]:
    return tuple((moment - series.published_at).total_seconds() / 3600
                 for moment in (sign.interval.start, sign.interval.end))


def test_rounded_telegram_feed_is_marked_over_its_whole_length() -> None:
    series = _post(1200)
    verdict = assess(series, analyzed_at=series.observed_at[-1], cadence=CollectionCadence())
    feeds = [sign for sign in verdict.signs if sign.pattern == 1 and sign.metric is Metric.VIEWS]
    assert len(feeds) == 1 and int(verdict.level) >= 2
    start, end = _hours(series, feeds[0])
    assert start <= 6.5 and end >= 39.5
    assert feeds[0].render["measurementMode"] == "bounded_views"


def test_organic_rounded_post_has_no_feed() -> None:
    series = _post(0)
    verdict = assess(series, analyzed_at=series.observed_at[-1], cadence=CollectionCadence())
    assert not [sign for sign in verdict.signs if sign.pattern == 1]


# Почасовой прирост просмотров настоящего поста МИСИС в Telegram (01.10.2026):
# пологий старт, подача ~1 200/ч с 6-го по 43-й час с паузами на 12-м, 28–29-м
# и 36-м часах, затем обрыв. На 19-м часу сбора не было.
REAL_HOURLY = (718, 217, 385, 180, 380, 430, 1140, 1230, 1220, 1220, 1210, 1220, 280, 1070, 1100, 1200, 1300,
               1200, 1200, 500, 1600, 1400, 1200, 1200, 1100, 1300, 1200, 1200, 400, 400, 1000, 1100, 1200, 1300,
               1100, 1200, 400, 1000, 1200, 1200, 1200, 1200, 1200, 600) + (0,) * 12
COLLECTION_GAP = (19.0, 20.0)


def _real_shape() -> PostSeries:
    cumulative = np.concatenate(([0.0], np.cumsum(REAL_HOURLY)))
    observed, views, reactions, qualities = [], [], [], []
    for minute in range(5, 60 * len(REAL_HOURLY), 5):
        age = minute / 60
        if COLLECTION_GAP[0] < age < COLLECTION_GAP[1]:
            continue
        value, quality = _display(float(np.interp(age, np.arange(cumulative.size), cumulative)))
        observed.append(PUBLISHED + timedelta(hours=age))
        views.append(max(value, views[-1]) if views else value)
        qualities.append(quality)
        reactions.append(min(30, minute // 10))
    return PostSeries(uuid4(), uuid4(), "telegram", PUBLISHED, False, tuple(observed),
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)},
                      qualities={Metric.VIEWS: tuple(qualities), Metric.REACTIONS: ("exact",) * len(views)})


def test_real_feed_with_pauses_and_a_gap_is_one_episode() -> None:
    """Худший случай каждого часа по отдельности раздувал фон округлением
    (415/ч против 328/ч по отрезку), и признак терялся; паузы и пробел рвали
    эпизод на куски."""
    series = _real_shape()
    verdict = assess(series, analyzed_at=series.observed_at[-1], cadence=CollectionCadence())
    feeds = [sign for sign in verdict.signs if sign.pattern == 1 and sign.metric is Metric.VIEWS]
    assert len(feeds) == 1 and int(verdict.level) >= 2
    start, end = _hours(series, feeds[0])
    assert start <= 6.5 and end >= 42.5
