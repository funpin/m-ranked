"""Доля необычного прироста признака — мера рейтинга «Аномальные посты»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anomaly_analysis.v2.domain import Family, Interval, Metric, PostSeries, Sign
from anomaly_analysis.v2.levels import _with_episode
from anomaly_analysis.v2.series import CollectionCadence, prepare

PUBLISHED = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)


def _series(views: list[int]) -> PostSeries:
    observed = tuple(PUBLISHED + timedelta(minutes=5 * (index + 1)) for index in range(len(views)))
    return PostSeries(uuid4(), uuid4(), "vk", PUBLISHED, False, observed,
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(0 for _ in views)})


def _sign(start_minutes: float, end_minutes: float) -> Sign:
    return Sign(1, Family.VELOCITY, Metric.VIEWS, 0.9,
                Interval(PUBLISHED + timedelta(minutes=start_minutes), PUBLISHED + timedelta(minutes=end_minutes)),
                timedelta(minutes=15), "формула", {"kind": "linear"})


def test_share_is_growth_inside_the_sign_over_the_final_value() -> None:
    # 100 просмотров, затем +900 за 45 минут, затем плато.
    views = [100] * 6 + [400, 700, 1000] + [1000] * 6
    series = _series(views)
    prepared = prepare(series, series.observed_at[-1], CollectionCadence())
    result = _with_episode(prepared, _sign(30, 45))
    assert result.render["episodeGrowth"] == 900
    assert result.render["episodeShare"] == 0.9


def test_sign_from_publication_starts_at_zero_and_missing_metric_keeps_sign() -> None:
    views = [500, 1000, 1000, 1000]
    series = _series(views)
    prepared = prepare(series, series.observed_at[-1], CollectionCadence())
    result = _with_episode(prepared, _sign(0, 10))
    assert result.render["episodeGrowth"] == 1000 and result.render["episodeShare"] == 1.0
    shares = Sign(1, Family.VELOCITY, Metric.SHARES, 0.9, _sign(0, 10).interval, timedelta(minutes=15), "ф", {})
    assert _with_episode(prepared, shares) is shares
