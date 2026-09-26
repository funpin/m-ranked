"""Расписание анализа v2: таблица периодичности, три точки, пробел, заморозка, деградация."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.schedule import (
    ScheduleConfig, interval, plan, recheck_offset, retry_after, stretch_for_lag,
)

CONFIG = ScheduleConfig()
NOW = datetime(2026, 3, 20, 12, tzinfo=timezone.utc)
H, M = 3600, 60


def decide(age_hours, **options):
    defaults = dict(platform="telegram", published_at=NOW - timedelta(hours=age_hours), now=NOW,
                    new_points=3, analyzed_before=True)
    return plan(CONFIG, **{**defaults, **options})


@pytest.mark.parametrize("platform,age_hours,expected", [
    ("telegram", 2, 15 * M), ("vk", 30, 45 * M), ("max", 4 * 24, 90 * M), ("telegram", 10 * 24, 3 * H),
    ("rutube", 2, 3 * H), ("rutube", 30, 3 * H), ("rutube", 4 * 24, 9 * H), ("rutube", 10 * 24, 24 * H),
])
def test_intervals_follow_the_plan_table(platform, age_hours, expected):
    assert interval(CONFIG, platform, age_hours * H) == expected


def test_three_new_points_are_needed_for_a_repeat_analysis():
    assert decide(30).analyze and decide(30).reason == "scheduled"
    waiting = decide(30, new_points=2)
    assert not waiting.analyze and waiting.next_due_at == NOW + timedelta(minutes=45)
    assert decide(30, new_points=0, analyzed_before=False).reason == "first"


def test_resumed_series_is_analyzed_at_once_and_stale_series_is_probed_often():
    assert decide(30, new_points=1, resumed_after_gap=True).analyze
    stale = decide(10 * 24, new_points=0, stale=True)
    assert not stale.analyze and stale.next_due_at == NOW + timedelta(seconds=CONFIG.stale_probe_seconds)


def test_new_norm_forces_a_recheck_without_new_points():
    assert decide(10 * 24, new_points=0, norm_recheck=True).reason == "norm_recheck"


def test_end_of_the_tracking_window_gives_a_final_analysis_and_freezes():
    final = decide(CONFIG.track_post_for_hours + 1, new_points=0)
    assert final.analyze and final.frozen and final.reason == "final"
    assert not decide(CONFIG.track_post_for_hours - 1).frozen


def test_catch_up_never_replays_missed_intervals():
    # Пост ждал анализа три дня простоя: один анализ сейчас, следующий — от сейчас.
    decision = decide(5 * 24)
    assert decision.analyze and decision.next_due_at == NOW + timedelta(minutes=90)


def test_degradation_stretches_only_the_oldest_interval():
    stretch = stretch_for_lag(CONFIG, 2 * H)
    assert stretch == CONFIG.max_stretch
    assert stretch_for_lag(CONFIG, 10 * M) == 1.0
    assert interval(CONFIG, "telegram", 10 * 24 * H, stretch) == 4 * 3 * H
    for age in (2, 30, 4 * 24):
        assert interval(CONFIG, "telegram", age * H, stretch) == interval(CONFIG, "telegram", age * H)


def test_norm_recheck_is_spread_deterministically_over_the_window():
    offsets = [recheck_offset(CONFIG, UUID(int=index)) for index in range(200)]
    assert offsets == [recheck_offset(CONFIG, UUID(int=index)) for index in range(200)]
    assert all(timedelta(0) <= item < timedelta(seconds=CONFIG.recheck_window_seconds) for item in offsets)
    assert max(offsets) - min(offsets) > timedelta(seconds=CONFIG.recheck_window_seconds * 0.8)


def test_retry_backoff_grows_and_is_bounded():
    assert retry_after(0) == timedelta(minutes=1) < retry_after(3) < retry_after(20) == timedelta(days=1)


def test_tracking_window_is_read_from_the_collector_variable():
    config = ScheduleConfig.from_environment({"TRACK_POST_FOR_HOURS": "480", "ANOMALY_MAX_STRETCH": "2.5",
                                              "ANOMALY_INTERVAL_DAY_1_SECONDS": "600"})
    assert config.track_post_for_hours == 480 and config.max_stretch == 2.5
    assert config.interval_day_1_seconds == 600
