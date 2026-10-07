"""Посты из разбора владельца 07.10.2026: что раньше не помечалось и почему теперь помечается."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from reported_cases import CASES, reported
from anomaly_analysis.v2.detectors import DetectorContext, engagement_regime, joint_cliff, reaction_write_off
from anomaly_analysis.v2.domain import Level, Metric
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.series import CollectionCadence, prepare

R, V = Metric.REACTIONS, Metric.VIEWS
HOUR = 3600


def hours(series, sign):
    return ((sign.interval.start - series.published_at).total_seconds() / HOUR,
            (sign.interval.end - series.published_at).total_seconds() / HOUR)


def detect(detector, series):
    return detector.detect(prepare(series, series.observed_at[-1], CollectionCadence()),
                           DetectorContext(series.platform))


@pytest.mark.parametrize("name, start, end", [
    # Реакции ~54/ч с 3,6 до 8,8 ч, затем сутки без единой реакции.
    ("02_linear_pack_then_stop", 3, 9.5),
    # 0 → 119 реакций за три часа, затем +1 на 1 900 просмотров.
    ("03_early_pack_then_stop", 0.3, 3.2),
    # Репост: +37 реакций при +8 просмотрах за 15 минут.
    ("04_repost_instant_step", 3.4, 4.5),
    # Сутки без реакций, затем +19 на 162 просмотра.
    ("10_late_start", 23, 34),
    # ~1 000 реакций ровно с 1-го по 18-й час, затем остановка.
    ("14_long_linear_pack", 0.5, 18.5),
])
def test_reaction_packs_reach_the_highest_level_with_the_whole_episode(name, start, end):
    series = reported(name)
    verdict = assess(series)
    assert verdict.level is Level.ARTIFICIAL_ACTIVITY_SIGNS
    (episode,) = [sign for sign in verdict.signs if sign.pattern == engagement_regime.PATTERN]
    begin, finish = hours(series, episode)
    assert start <= begin and finish <= end, (begin, finish)
    assert episode.render["plateauEvidence"] == engagement_regime.CONFIRMED_MODE


def test_repost_episode_uses_the_reposts_own_views():
    series = reported("04_repost_instant_step")
    assert series.is_repost
    payload = compact(assess(series))
    assert "repost_source_counter" not in payload["quality"]["codes"]
    assert not any("требу" in signal["title"] for signal in payload["signals"])


def test_joint_cliff_of_views_and_reactions_is_pronounced():
    series = reported("05_joint_cliff")
    verdict = assess(series)
    assert verdict.level >= Level.PRONOUNCED_ANOMALY
    (cliff,) = [sign for sign in verdict.signs if sign.pattern == joint_cliff.PATTERN]
    assert 6 <= hours(series, cliff)[1] <= 7


def test_write_off_is_pronounced_and_names_the_removed_reactions():
    series = reported("06_write_off")
    verdict = assess(series)
    assert verdict.level >= Level.PRONOUNCED_ANOMALY
    (write_off,) = [sign for sign in verdict.signs if sign.pattern == reaction_write_off.PATTERN]
    assert write_off.render["before"] == 111 and write_off.render["removed"] == 79


@pytest.mark.parametrize("name", [name for name in CASES if name.startswith("control_")])
def test_busy_organic_posts_stay_clean(name):
    series = reported(name)
    for detector in (engagement_regime, joint_cliff, reaction_write_off):
        assert detect(detector, series) == (), (name, detector.ID)


def test_restored_counter_is_a_glitch_not_a_write_off():
    series = reported("06_write_off")
    values = list(series.values[R])
    drop = next(index for index in range(1, len(values)) if values[index] < values[index - 1] - 50)
    # Значение вернулось следующим замером — сбой выдачи.
    values[drop] = values[drop - 1] - 79
    for index in range(drop + 1, len(values)):
        values[index] = max(values[index], values[drop - 1])
    assert detect(reaction_write_off, replace(series, values={**series.values, R: tuple(values)})) == ()


def test_evening_cliff_inside_moscow_night_is_not_a_sign():
    series = reported("05_joint_cliff")
    # Тот же ряд, сдвинутый так, что обрыв приходится на 01:00 по Москве.
    shift = timedelta(hours=7)
    moved = replace(series, published_at=series.published_at + shift,
                    observed_at=tuple(at + shift for at in series.observed_at))
    assert detect(joint_cliff, moved) == ()


def test_granular_counter_updates_are_not_mistaken_for_a_pack():
    # Каждое органическое событие ×10 (пакетное обновление счётчика): форма та
    # же, что у живого поста, — квазипуассоновский разброс гасит зернистость.
    series = reported("control_max_0")
    coarse = tuple(None if value is None else value * 10 for value in series.values[R])
    assert detect(engagement_regime, replace(series, values={**series.values, R: coarse})) == ()
