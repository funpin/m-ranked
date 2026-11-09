"""Всплеск просмотров без отклика (признак 19): реакции внутри всплеска против реакций поста вне него."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, view_burst_response
from anomaly_analysis.v2.domain import Family, Metric, PostSeries
from anomaly_analysis.v2.levels import STRONG, _same_events, assess
from anomaly_analysis.v2.series import CollectionCadence, prepare

PUBLISHED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
V, R = Metric.VIEWS, Metric.REACTIONS


def series(burst_hour=30, burst_views=3000, burst_reactions=0, *, base_views=60.0, rate=0.02, hours=80,
           publication_type="photo"):
    observed, views, reactions = [], [], []
    v, r = 0.0, 0.0
    for minute in range(15, hours * 60 + 1, 15):
        hour = (minute - 1) // 60
        rate_views = base_views * 3 / (1 + hour / 6)
        v += rate_views / 4
        r += rate_views / 4 * rate
        if hour == burst_hour:
            v += burst_views / 4
            r += burst_reactions / 4
        observed.append(PUBLISHED + timedelta(minutes=minute))
        views.append(int(v))
        reactions.append(int(r))
    return PostSeries(UUID(int=19), UUID(int=9), "vk", PUBLISHED, False, tuple(observed), {V: tuple(views), R: tuple(reactions)},
                      publication_type=publication_type)


def prepared(item):
    return prepare(item, item.observed_at[-1], CollectionCadence())


def detect(item):
    return view_burst_response.detect(prepared(item), DetectorContext("vk"))


def test_views_without_reactions_inside_the_burst_are_a_sign():
    (sign,) = detect(series())
    assert sign.pattern == 19 and sign.family is Family.CROSS_METRIC and sign.metric is V
    assert sign.render["kind"] == "view_burst" and sign.render["outcome"] == "decoupled"
    assert sign.strength >= STRONG


def test_reactions_in_the_usual_proportion_are_context_not_a_sign():
    item = series(burst_reactions=60)
    assert view_burst_response.burst_response(prepared(item)).outcome == "coupled"
    assert not detect(item)


def test_reactions_above_the_usual_proportion_are_coupled_with_a_high_share():
    response = view_burst_response.burst_response(prepared(series(burst_reactions=150)))
    assert response.outcome == "coupled" and response.share >= 1.5


def test_a_half_way_response_is_intermediate_and_not_a_sign():
    item = series(burst_reactions=20)
    assert view_burst_response.burst_response(prepared(item)).outcome == "intermediate"
    assert not detect(item)


def test_a_burst_below_the_size_threshold_is_not_measured():
    assert view_burst_response.burst_response(prepared(series(burst_views=150))) is None


def test_the_first_two_hours_are_not_a_burst():
    assert view_burst_response.burst_response(prepared(series(burst_hour=1))) is None


def test_a_post_with_almost_no_reactions_gives_no_evidence():
    item = series(rate=0.0005)
    assert view_burst_response.burst_response(prepared(item)).outcome == "decoupled"
    assert not detect(item)


def test_a_post_younger_than_three_days_uses_its_current_value():
    (sign,) = detect(series(burst_hour=20, hours=40))
    assert sign.render["outcome"] == "decoupled"


def test_vk_video_is_not_judged():
    assert not detect(series(publication_type="video"))


def test_strength_follows_the_surprise():
    weak = series(burst_views=420, base_views=20, rate=0.03)
    (sign,) = detect(weak)
    assert sign.strength < STRONG


def test_one_view_burst_is_one_event_for_the_level():
    from dataclasses import replace

    (burst,) = detect(series())
    shape = replace(burst, pattern=2, family=Family.SHAPE, strength=0.9, render={"kind": "expected"})
    apart = replace(shape, interval=replace(burst.interval, start=burst.interval.start + timedelta(hours=9),
                                            end=burst.interval.end + timedelta(hours=9)))
    assert len(_same_events([burst, shape])) == 1
    assert len(_same_events([burst, apart])) == 2
    assert len(_same_events([shape, apart])) == 2


def test_a_decoupled_burst_reaches_the_verdict():
    item = series()
    verdict = assess(item, analyzed_at=item.observed_at[-1])
    assert 19 in {sign.pattern for sign in verdict.signs} | {
        pattern for sign in verdict.signs for pattern in sign.render.get("sameEpisodePatterns", ())}


def test_only_vk_is_judged_until_other_platforms_are_calibrated():
    from dataclasses import replace

    item = replace(series(), platform="max")
    assert view_burst_response.burst_response(prepared(item)) is None
