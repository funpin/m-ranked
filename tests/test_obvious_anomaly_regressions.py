"""Observable counter patterns must survive missing unrelated metrics and reposts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np
import pytest

from anomaly_analysis.v2.detectors import DetectorContext, linear_feed
from anomaly_analysis.v2.domain import Level, Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence, prepare

T = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
V, R = Metric.VIEWS, Metric.REACTIONS


def series(platform="max", *, ramp=False, repost=False, missing_views=False):
    hours = np.arange(24, 48.01, .25)
    reactions = 30 + (np.clip(hours - 32, 0, 8) * 100 if ramp else (hours >= 33) * 1000)
    views = tuple(None if missing_views and 31 <= h <= 41 else 3000 for h in hours)
    return PostSeries(UUID(int=1), UUID(int=2), platform, T, repost,
                      tuple(T + timedelta(hours=float(h)) for h in hours),
                      {V: views, R: tuple(map(int, reactions))})


@pytest.mark.parametrize("platform", ["telegram", "vk", "max", "rutube"])
def test_observed_zero_background_is_valid_for_linear_feed(platform):
    subject = series(platform, ramp=True)
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    signs = linear_feed.detect(prepared, DetectorContext(platform))
    assert any(s.metric is R and s.strength >= .7 for s in signs)


@pytest.mark.parametrize("platform", ["telegram", "vk", "max", "rutube"])
def test_view_gap_cannot_hide_an_observed_reaction_burst(platform):
    result = assess(series(platform, missing_views=True))
    assert result.level >= Level.PRONOUNCED_ANOMALY
    assert any(s.pattern == 9 and s.metric is R for s in result.signs)


@pytest.mark.parametrize("platform", ["telegram", "vk", "max", "rutube"])
def test_repost_keeps_its_own_reaction_shape_checks(platform):
    result = assess(series(platform, repost=True, missing_views=True))
    assert result.level >= Level.PRONOUNCED_ANOMALY
    assert any(s.pattern == 9 and s.metric is R for s in result.signs)
    assert not any(s.metric is V for s in result.signs)


def test_missing_background_does_not_become_observed_zero():
    subject = series(ramp=True)
    values = tuple(None if (at - T).total_seconds() < 32 * 3600 else value
                   for at, value in zip(subject.observed_at, subject.values[R]))
    subject = replace(subject, values={R: values})
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    assert not linear_feed.detect(prepared, DetectorContext(subject.platform))
