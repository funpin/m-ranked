"""Линейная подача ВК: дневной участок ленты не признак, ровная ночь и резкая ступенька — признак."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.detectors import DetectorContext, linear_feed
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import CollectionCadence, prepare

# 12:00 МСК: возраст 12 ч — полночь, 20 ч — 08:00 следующего дня.
PUBLISHED = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
HOURS = 60


def _prepared(rate: Callable[[int], float], reactions: Callable[[int], float] = lambda hour: 0.03, platform: str = "vk"):
    observed, views, likes = [], [], []
    v = r = 0.0
    for minute in range(5, HOURS * 60 + 1, 5):
        hour = (minute - 1) // 60
        v += rate(hour) * 5 / 60
        r += rate(hour) * reactions(hour) * 5 / 60
        observed.append(PUBLISHED + timedelta(minutes=minute))
        views.append(int(v))
        likes.append(int(r))
    series = PostSeries(UUID(int=5), UUID(int=6), platform, PUBLISHED, False, tuple(observed),
                        {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(likes)})
    return prepare(series, observed[-1], CollectionCadence())


def _day_feed(level: float, after: float | None = None) -> Callable[[int], float]:
    """Пик старта, вечерний фон 30/ч, тихая ночь и ровный участок 08:00–16:00 МСК."""
    tail = level / 2 if after is None else after

    def rate(hour: int) -> float:
        if hour < 6:
            return 200
        if hour < 12:
            return 30
        if hour < 20:
            return 3
        return level if hour < 28 else tail
    return rate


def _night_feed(level: float = 150) -> Callable[[int], float]:
    """Ровный участок 01:00–11:00 МСК: у московской аудитории проходит через тихое окно."""
    def rate(hour: int) -> float:
        if hour < 6:
            return 200
        if hour < 13:
            return 30
        return level if hour < 23 else level / 2
    return rate


def _views(prepared, offset: int | None = 0):
    context = DetectorContext(prepared.series.platform, audience_offset=offset)
    return [sign for sign in linear_feed.detect(prepared, context) if sign.metric is Metric.VIEWS]


def test_daytime_feed_near_its_own_background_is_not_a_sign():
    assert not _views(_prepared(_day_feed(150)))


def test_daytime_feed_far_above_its_own_background_stays_a_sign():
    assert _views(_prepared(_day_feed(1500)))


def test_daytime_feed_with_a_daytime_cliff_stays_a_sign():
    assert _views(_prepared(_day_feed(150, after=5)))


def test_feed_through_the_quiet_window_stays_a_sign():
    assert _views(_prepared(_night_feed()))


def test_quiet_window_follows_the_audience_clock():
    # 01:00–11:00 МСК у аудитории с +6 — её 07:00–17:00, день.
    assert not _views(_prepared(_night_feed()), offset=6)


def test_unknown_audience_clock_does_not_prove_a_flat_night():
    assert not _views(_prepared(_night_feed()), offset=None)


def test_other_platforms_keep_the_previous_rule():
    assert _views(_prepared(_day_feed(150), platform="max"))


def _short_block(hour: int) -> float:
    if hour < 6:
        return 30
    if hour < 20:
        return 3 if hour >= 12 else 30
    return 3000 if hour < 24 else 3


def test_coupled_burst_lowers_the_feed_to_a_weak_signal():
    (sign,) = _views(_prepared(_short_block))
    assert sign.strength <= linear_feed.COUPLED_STRENGTH


def test_decoupled_burst_raises_the_feed_to_pronounced():
    silent = _prepared(_short_block, reactions=lambda hour: 0.0 if 20 <= hour < 24 else 0.05)
    (sign,) = _views(silent)
    assert sign.strength >= linear_feed.DECOUPLED_STRENGTH


@pytest.mark.parametrize("platform", ["vk"])
def test_feed_alternatives_name_promotion_and_recommendations(platform):
    (sign,) = _views(_prepared(_night_feed(), platform=platform))
    assert {"recommendation_feed", "paid_promotion"} <= set(sign.alternatives)
