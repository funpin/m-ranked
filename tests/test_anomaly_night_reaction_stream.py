"""Реакции сквозь ночь (признак 18): поток реакций клипа ВК в 00–06 МСК."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, night_reaction_stream
from anomaly_analysis.v2.domain import Family, Metric, PostSeries
from anomaly_analysis.v2.levels import assess
from anomaly_analysis.v2.series import CollectionCadence, prepare

# 11:00 МСК, как Губкинский ВК №238136 01.10.2026.
PUBLISHED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
MSK = timedelta(hours=3)


def clip(reactions_per_hour, views_per_hour, hours=40, publication_type="video", step=5):
    """Ряд с замерами раз в `step` минут; темпы — функции часа МСК от публикации."""
    observed, views, reactions = [], [], []
    v = r = 0.0
    for minute in range(step, hours * 60 + 1, step):
        moment = PUBLISHED + timedelta(minutes=minute)
        age = minute / 60
        v += views_per_hour(age, (moment + MSK).hour) * step / 60
        r += reactions_per_hour(age, (moment + MSK).hour) * step / 60
        observed.append(moment)
        views.append(int(v))
        reactions.append(int(r))
    return PostSeries(UUID(int=18), UUID(int=8), "vk", PUBLISHED, False, tuple(observed),
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)},
                      publication_type=publication_type)


def gubkin_reactions(age, hour):
    """2 лайка за 9 ч, затем с 20:00 до 04:00 МСК по ~45 в час, и обрыв в ноль."""
    if age < 9:
        return 0.25
    if 9 <= age < 17:
        return 45.0
    return 0.0


def gubkin_views(age, hour):
    if age < 9:
        return 40.0
    if age < 17:
        return 90.0
    return 8.0


def detect(series):
    return night_reaction_stream.detect(prepare(series, series.observed_at[-1], CollectionCadence()),
                                        DetectorContext(series.platform))


def test_a_night_stream_of_clip_reactions_that_stops_dead_is_a_strong_sign():
    (sign,) = detect(clip(gubkin_reactions, gubkin_views))
    assert sign.pattern == 18 and sign.family is Family.VELOCITY and sign.metric is Metric.REACTIONS
    assert sign.strength == night_reaction_stream.STRONG_STRENGTH
    assert sign.render["startClock"] == 20 and sign.render["endClock"] == 4
    assert sign.render["nightShare"] >= night_reaction_stream.NIGHT_SHARE
    assert sign.render["cliffRate"] >= night_reaction_stream.CLIFF_RATE and sign.render["cliffViews"] > 0
    assert "с 00 до 06 МСК" in sign.formula and "без единой реакции" in sign.formula


def test_a_night_stream_that_fades_instead_of_stopping_is_a_medium_sign():
    fading = lambda age, hour: gubkin_reactions(age, hour) or (4.0 if age >= 17 else 0.0)  # noqa: E731
    (sign,) = detect(clip(fading, gubkin_views))
    assert sign.strength == night_reaction_stream.MEDIUM_STRENGTH and sign.render["cliffRate"] is None


def test_an_evening_response_that_sleeps_at_night_is_not_a_sign():
    # Живой клип: отклик с 18 до 23 МСК, ночью почти ничего.
    evening = lambda age, hour: 30.0 if 18 <= hour < 23 and age < 24 else (0.5 if age < 24 else 0.0)  # noqa: E731
    assert detect(clip(evening, gubkin_views)) == ()


def test_only_vk_clips_are_judged_by_the_clock():
    assert detect(clip(gubkin_reactions, gubkin_views, publication_type="photo")) == ()


def test_the_first_response_after_publication_is_not_a_night_stream():
    # Клип вышел в 23:00 МСК, и первый отклик пришёл ночью: это не поток.
    late = lambda age, hour: 30.0 if age < 6 else 0.0  # noqa: E731
    series = clip(late, gubkin_views)
    shifted = PostSeries(series.publication_id, series.account_id, "vk", PUBLISHED + timedelta(hours=12),
                         False, tuple(moment + timedelta(hours=12) for moment in series.observed_at),
                         series.values, publication_type="video")
    assert detect(shifted) == ()


def test_the_post_level_carries_the_night_stream():
    result = assess(clip(gubkin_reactions, gubkin_views))
    assert any(sign.pattern == 18 for sign in result.signs)
    assert int(result.level) >= 2
