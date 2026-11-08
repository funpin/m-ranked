"""Признаки формы просмотров: пакет после второго часа (20) и поздний старт охвата (21)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, view_late_start, view_packet
from anomaly_analysis.v2.domain import Level, Metric, PostSeries
from anomaly_analysis.v2.levels import STRONG, assess, level_for
from anomaly_analysis.v2.series import CollectionCadence, prepare

PUBLISHED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)  # 11:00 МСК
V, R = Metric.VIEWS, Metric.REACTIONS


def series(burst_hour=2, burst_views=3000, burst_reactions=0, *, base_views=60.0, rate=0.02, hours=80,
           publication_type="photo", platform="vk", after_rate=None):
    observed, views, reactions = [], [], []
    v, r = 0.0, 0.0
    for minute in range(15, hours * 60 + 1, 15):
        hour = (minute - 1) // 60
        pace = base_views * 3 / (1 + hour / 6)
        if after_rate is not None and burst_hour < hour <= burst_hour + 3:
            pace = after_rate
        v += pace / 4
        r += pace / 4 * rate
        if hour == burst_hour:
            v += burst_views / 4
            r += burst_reactions / 4
        observed.append(PUBLISHED + timedelta(minutes=minute))
        views.append(int(v))
        reactions.append(int(r))
    return PostSeries(UUID(int=20), UUID(int=9), platform, PUBLISHED, False, tuple(observed),
                      {V: tuple(views), R: tuple(reactions)}, publication_type=publication_type)


def prepared(item):
    return prepare(item, item.observed_at[-1], CollectionCadence())


def packet(item, offset=0):
    return view_packet.detect(prepared(item), DetectorContext("vk", audience_offset=offset))


def late(item):
    return view_late_start.detect(prepared(item), DetectorContext("vk"))


def test_a_packet_without_a_response_is_one_composite_level_three_sign():
    (sign,) = packet(series())
    assert sign.pattern == 20 and sign.render["outcome"] == "decoupled"
    assert level_for([sign]) is Level.ARTIFICIAL_ACTIVITY_SIGNS


def test_a_packet_with_a_daytime_cliff_is_pronounced():
    (sign,) = packet(series(rate=0.004))
    assert sign.render["outcome"] == "decoupled" and sign.render["cliff"] is True
    assert STRONG <= sign.strength < 0.9


def test_a_cliff_with_a_partial_response_stays_a_weak_signal():
    (sign,) = packet(series(burst_reactions=20))
    assert sign.render["outcome"] == "intermediate" and sign.render["cliff"] is True
    assert sign.strength < STRONG


def test_a_packet_alone_is_a_weak_signal():
    (sign,) = packet(series(burst_hour=12, burst_reactions=20))  # обрыв приходится на полночь МСК
    assert sign.render["cliff"] is False and sign.strength < STRONG


def test_a_viral_packet_with_coupled_reactions_is_not_a_sign():
    assert not packet(series(burst_reactions=60))


def test_the_cliff_hour_follows_the_audience_clock():
    # Обрыв в 00:00 МСК у аудитории с +9… вне границ; с +6 это 06:00 — тоже не день; с +4 в 13 МСК — 17:00.
    item = series(burst_hour=12, burst_reactions=20)
    assert packet(item, offset=0)[0].render["cliff"] is False
    daytime = series(burst_reactions=20)
    assert packet(daytime, offset=4)[0].render["cliff"] is True
    assert packet(daytime, offset=None)[0].render["cliff"] is False


def test_a_slow_decline_after_the_packet_is_not_a_cliff():
    (sign,) = packet(series(burst_reactions=20, after_rate=900))
    assert sign.render["cliff"] is False


def test_only_vk_is_judged():
    assert not packet(series(platform="max"))
    assert not late(series(platform="max", burst_hour=30, base_views=2))


def test_late_start_alone_is_weak():
    (sign,) = late(series(burst_hour=30, burst_reactions=60, base_views=2, rate=0.02))
    assert sign.pattern == 21 and sign.strength == 0.45


def test_late_start_with_a_decoupled_burst_is_pronounced_and_covers_the_burst():
    item = series(burst_hour=30, base_views=4, rate=0.05)
    (sign,) = late(item)
    assert sign.strength >= STRONG
    assert sign.render["endAge"] >= 31 * 3600


def test_a_normal_start_or_small_post_is_not_a_late_start():
    assert not late(series(burst_hour=30, burst_views=100))
    assert not late(series(burst_hour=30, burst_views=1000, base_views=1))


def test_young_post_has_no_late_start_verdict():
    assert not late(series(burst_hour=30, base_views=2, hours=60))


def test_late_start_and_decoupled_packet_stay_one_event():
    item = series(burst_hour=30, base_views=4, rate=0.05, burst_views=3000)
    verdict = assess(item, analyzed_at=item.observed_at[-1])
    found = {p for sign in verdict.signs for p in (sign.pattern, *sign.render.get("sameEpisodePatterns", ()))}
    assert {19, 20, 21} <= found
    assert sum(sign.pattern in {19, 20, 21} for sign in verdict.signs) == 1
