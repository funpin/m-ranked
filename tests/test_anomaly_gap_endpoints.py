from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.detectors import DetectorContext, reactions_before_views
from anomaly_analysis.v2.detectors.reactions_before_views import ENDPOINT_MODE
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.series import CollectionCadence, prepare

V, R = Metric.VIEWS, Metric.REACTIONS
T = datetime(2026, 9, 22, 15, 27, 16, 625000, tzinfo=timezone.utc)


def subject(gap_minutes=95, platform="max"):
    # Actual reported endpoint counts; missing early coverage is intentional.
    start = 5 * 86400 + 48 * 60 + 12
    end = start + gap_minutes * 60
    ages = (805, start-3*3600, start-3600, start, end, end+65*60, end+95*60)
    return PostSeries(UUID(int=101), UUID(int=102), platform, T, False,
                      tuple(T+timedelta(seconds=x) for x in ages),
                      {V: (100, 2963, 2972, 2975, 2976, 2979, 2982),
                       R: (3, 47, 47, 47, 363, 363, 363)})


def endpoints(s, now=None):
    result = assess(s, analyzed_at=now or s.observed_at[-1])
    return result, [sign for sign in result.signs if sign.render.get("comparisonMode") == ENDPOINT_MODE]


def test_missing_first_day_and_95_minute_gap_preserve_measured_jump():
    s = subject()
    p = prepare(s, s.observed_at[-1], CollectionCadence())
    assert p.truncated_start and DetectorContext("max").early_fit(p, R) is None
    result, (sign,) = endpoints(s)
    assert sign.interval.start == s.observed_at[3]
    assert sign.interval.end == s.observed_at[4]
    assert sign.render["reactionsDelta"] == 316
    assert sign.render["viewsDelta"] == 1
    assert sign.render["viewsDeltaWithDelay"] == 4
    assert sign.strength == 0.5 and result.level == 1
    assert "47 → 363" in sign.formula and "неизвестны" in sign.formula
    body = compact(result)
    assert body["signals"][0]["title"] == "Прирост реакций при малом приросте просмотров"
    assert "форма роста" in body["quality"]["summary"]


@pytest.mark.parametrize("minutes", [89, 90, 90.01, 95, 120, 360])
def test_crossing_gap_boundary_does_not_hide_the_jump(minutes):
    result, _ = endpoints(subject(minutes))
    assert any(s.pattern == 6 for s in result.signs)


@pytest.mark.parametrize("minutes", [360.01, 1440])
def test_long_unobserved_intervals_are_not_claimed_as_bounded_evidence(minutes):
    assert not endpoints(subject(minutes))[1]


def test_counter_delay_must_be_observed_and_catch_up_cancels_the_signal():
    s = subject()
    assert not endpoints(s, s.observed_at[4])[1]
    # Current/post-gap readings must not leak into an earlier analysis.
    assert not endpoints(s, s.observed_at[4]+timedelta(minutes=30))[1]
    views = list(s.values[V]); views[5:] = [15000, 15003]
    assert not endpoints(replace(s, values={**s.values, V:tuple(views)}))[1]


@pytest.mark.parametrize("metric", [V, R])
@pytest.mark.parametrize("index", [3, 4, 5])
@pytest.mark.parametrize("quality", ["rounded", "unknown", "invalid", "suspected_reset"])
def test_untrusted_endpoint_or_delay_read_is_never_used(metric, index, quality):
    s = subject(); qualities = dict(s.qualities)
    q = list(qualities[metric]); q[index] = quality; qualities[metric] = tuple(q)
    assert not endpoints(replace(s, qualities=qualities))[1]


def test_bad_interior_read_cannot_be_erased_to_join_two_good_ends():
    s = subject()
    instants = list(s.observed_at); instants.insert(4, instants[3]+timedelta(minutes=30))
    values, qualities = {}, {}
    for metric in (V,R):
        v=list(s.values[metric]); v.insert(4, v[3]); values[metric]=tuple(v)
        q=list(s.qualities[metric]); q.insert(4,"unknown"); qualities[metric]=tuple(q)
    assert not endpoints(replace(s,observed_at=tuple(instants),values=values,qualities=qualities,interval_uncertain=()))[1]


@pytest.mark.parametrize("metric", [V, R])
def test_negative_correction_during_delay_is_not_evidence(metric):
    s=subject(); v=list(s.values[metric]); v[5]=v[4]-1
    assert not endpoints(replace(s,values={**s.values,metric:tuple(v)}))[1]


def test_uncertain_interval_and_repost_are_excluded():
    s=subject(); flags=[False]*len(s.observed_at); flags[4]=True
    assert not endpoints(replace(s,interval_uncertain=tuple(flags)))[1]
    assert not endpoints(replace(s,is_repost=True))[1]


@pytest.mark.parametrize("platform", ["telegram", "vk", "rutube"])
def test_no_unvalidated_transfer_to_other_platforms(platform):
    assert not endpoints(subject(platform=platform))[1]


def test_ordinary_co_growth_and_small_counts_do_not_trigger():
    s=subject()
    for views,reactions in [((100,2963,2972,2975,20000,20003,20006),s.values[R]),
                            (s.values[V],(3,47,47,47,49,49,49))]:
        assert not endpoints(replace(s,values={V:views,R:reactions}))[1]


def test_overdue_follow_up_and_early_gap_abstain():
    s=subject(); at=list(s.observed_at)
    at[5:]=[at[4]+timedelta(hours=4),at[4]+timedelta(hours=5)]
    assert not endpoints(replace(s,observed_at=tuple(at)))[1]
    early=replace(s,observed_at=tuple(T+timedelta(minutes=m) for m in (1,10,20,30,125,190,220)))
    assert not endpoints(early)[1]
