from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.detectors import DetectorContext, reactions_catch_up, reactions_exceed_views
from anomaly_analysis.v2.series import CollectionCadence, confirm_unchanged, prepare


def test_account_success_cannot_turn_day_growth_into_half_hour_burst():
    ages = np.array([72., 96.]) * 3600
    out, source, covered = confirm_unchanged(ages, np.arange(72.5, 96.1, .5)*3600, CollectionCadence(), "max")
    assert np.diff(out).tolist() == [86400.]
    assert source.tolist() == [0, 1] and not covered.any()


def test_half_cell_interpolation_cannot_turn_alternating_counts_into_low_dispersion():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    counts = np.arange(41)
    # Alternating 0/80 becomes constant 40 after half-cell interpolation.
    for low_noise in (False, True):
        increments = np.full(40, 40) if low_noise else np.tile([0, 80], 20)
        reactions = np.r_[1000, 1000+np.cumsum(increments)]
        for shift in (0, 3):
            times = tuple(start + timedelta(hours=int(h)) for h in 72 + counts*6 + shift)
            series = PostSeries(UUID(int=1), UUID(int=2), "rutube", start, False, times,
                                {Metric.VIEWS: tuple(map(int, 12500+500*counts)),
                                 Metric.REACTIONS: tuple(map(int, reactions))})
            signs = reactions_catch_up.detect(prepare(series, times[-1], CollectionCadence()), DetectorContext("rutube"))
            if low_noise:
                assert signs and all(s.strength <= reactions_catch_up.EXPLORATORY_CAP for s in signs)
            else:
                assert signs == ()


def test_telegram_product_rule_uses_one_to_one_without_claiming_unique_people():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    series = PostSeries(UUID(int=1), UUID(int=2), "telegram", start, False,
                        (start+timedelta(hours=1),start+timedelta(hours=2)),
                        {Metric.VIEWS: (100,100), Metric.REACTIONS: (200,200)})
    signs = reactions_exceed_views.detect(prepare(series,start+timedelta(hours=2),CollectionCadence()), DetectorContext("telegram"))
    assert signs and signs[0].render['comparisonRatio'] == 1
    assert 'multiple_reactions_per_viewer' in signs[0].alternatives


def test_observed_resets_inside_a_pair_are_not_treated_as_smooth_arrivals():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    steps = np.arange(81)
    times = tuple(start + timedelta(hours=int(h)) for h in 72 + steps*3)
    reactions = np.where(steps % 2, 100, 1000 + 20*steps)
    series = PostSeries(UUID(int=1), UUID(int=2), "rutube", start, False, times,
                        {Metric.VIEWS: tuple(map(int, 12500 + 250*steps)),
                         Metric.REACTIONS: tuple(map(int, reactions))})
    assert not reactions_catch_up.detect(
        prepare(series, times[-1], CollectionCadence()), DetectorContext("rutube"))
