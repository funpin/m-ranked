from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import time
from uuid import UUID

import numpy as np
import pytest

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import (
    SCALES, CollectionCadence, PointFlag, age_band, prepare, views_belong_to_source, views_estimate_at,
)

PUBLISHED = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
CADENCE = CollectionCadence()
H, M = 3600, 60


def post(ages, values, *, platform="telegram", is_repost=False, qualities=None):
    return PostSeries(UUID(int=1), UUID(int=2), platform, PUBLISHED, is_repost,
                      tuple(PUBLISHED + timedelta(seconds=int(age)) for age in ages),
                      {Metric(name): tuple(column) for name, column in values.items()},
                      qualities=None if qualities is None else {
                          Metric(name): tuple(column) for name, column in qualities.items()})


def later(hours):
    return PUBLISHED + timedelta(hours=hours)


def test_telegram_five_minute_grid_recovers_a_constant_rate():
    ages = np.arange(0, 24 * H + 1, 5 * M)
    prepared = prepare(post(ages, {"views": list(ages // 60)}), later(30), CADENCE)
    views = prepared.metrics[Metric.VIEWS]
    for scale in SCALES[:3]:
        grid = views.grids[scale]
        assert np.allclose(grid.rates, 1 / 60)
        assert grid.usable.all() and not grid.in_gap.any()
        assert np.allclose(grid.edges % scale.total_seconds(), 0)
    # Ровно сутки замеров дают одну суточную ячейку.
    assert views.grids[SCALES[3]].rates.size == 1
    assert views.coverage == 1.0 and not views.gaps
    assert not prepared.truncated_start


def test_rutube_hourly_series_interpolates_inside_observations():
    ages = np.arange(0, 48 * H + 1, H)
    prepared = prepare(post(ages, {"views": list(ages // 36)}, platform="rutube"), later(48), CADENCE)
    grid = prepared.metrics[Metric.VIEWS].grids[timedelta(minutes=15)]
    assert grid.rates.size == 48 * 4
    assert np.allclose(grid.rates, 1 / 36) and grid.usable.all()
    # Для RuTube часовой шаг — норма, пробела нет.
    assert not prepared.metrics[Metric.VIEWS].gaps


def test_gap_is_kept_as_an_interval_and_masked_on_grids():
    ages = np.concatenate((np.arange(0, 60 * H, 15 * M), np.arange(74 * H, 80 * H, 15 * M)))
    values = np.where(ages < 60 * H, 1000, 8000) + ages // 3600
    prepared = prepare(post(ages, {"views": list(values)}), later(80), CADENCE)
    views = prepared.metrics[Metric.VIEWS]
    (gap,) = views.gaps
    assert gap.start_age < 60 * H and gap.end_age == 74 * H
    assert gap.delta == pytest.approx(8074 - 1059)
    assert views.flags[np.searchsorted(views.ages, 74 * H)] & PointFlag.AFTER_GAP
    grid = views.grids[timedelta(hours=1)]
    inside = (grid.edges[:-1] >= 60 * H) & (grid.edges[1:] <= 74 * H)
    assert grid.in_gap[inside].all() and not grid.usable[inside].any()
    assert grid.usable[grid.edges[1:] <= 59 * H].all()
    assert views.coverage < 0.9


def test_truncated_start_is_detected():
    ages = np.arange(9 * H, 20 * H, 5 * M)
    assert prepare(post(ages, {"views": list(ages)}), later(20), CADENCE).truncated_start
    early = np.arange(4 * M, 20 * H, 5 * M)
    assert not prepare(post(early, {"views": list(early)}), later(20), CADENCE).truncated_start


def test_negative_delta_is_a_flag_and_a_large_drop_is_a_reset():
    ages = np.arange(0, 6 * H, 15 * M)
    reactions = [100 + index for index in range(ages.size)]
    reactions[8] -= 5          # сняли несколько реакций
    reactions[16:] = [value - 90 for value in reactions[16:]]  # счётчик сброшен
    prepared = prepare(post(ages, {"views": list(ages), "reactions": reactions}), later(6), CADENCE)
    series = prepared.metrics[Metric.REACTIONS]
    assert series.flags[8] & PointFlag.NEGATIVE_DELTA
    assert not series.flags[8] & PointFlag.COUNTER_RESET
    assert series.flags[16] & PointFlag.COUNTER_RESET
    grid = series.grids[timedelta(minutes=15)]
    assert grid.negative[7] and grid.usable[7]
    assert not grid.usable[15]
    assert grid.usable[[index for index in range(grid.usable.size) if index != 15]].all()


def test_null_metrics_are_unsupported_or_missing_not_zero():
    ages = np.arange(0, 10 * H, 15 * M)
    reactions = [int(age // 60) for age in ages]
    for index in range(12, 20):
        reactions[index] = None
    prepared = prepare(post(ages, {"views": list(ages), "reactions": reactions,
                                   "comments": [None] * ages.size}), later(10), CADENCE)
    assert prepared.unsupported == {Metric.COMMENTS, Metric.SHARES}
    series = prepared.metrics[Metric.REACTIONS]
    assert series.ages.size == ages.size - 8
    assert series.flags[12] & PointFlag.MISSING
    # Два часа без значения при пятнадцатиминутном шаге — пробел по этой метрике.
    assert len(series.gaps) == 1 and not prepared.metrics[Metric.VIEWS].gaps


def test_repost_views_are_the_reposts_own_counter():
    # Замеры 1 100 репостов MAX и Telegram: первый замер и итог как у своих постов.
    ages = np.arange(0, 5 * H, 5 * M)
    subject = post(ages, {"views": list(ages), "reactions": list(ages // 100)}, is_repost=True)
    prepared = prepare(subject, later(5), CADENCE)
    assert not views_belong_to_source(subject)
    assert not prepared.metrics[Metric.VIEWS].source_counter
    assert not prepared.metrics[Metric.REACTIONS].source_counter


def test_analysis_moment_is_a_parameter():
    ages = np.arange(0, 10 * H, 5 * M)
    prepared = prepare(post(ages, {"views": list(ages)}), later(4), CADENCE)
    assert prepared.ages[-1] <= 4 * H
    assert prepared.stale_seconds == pytest.approx(4 * H - prepared.ages[-1])


def test_age_bands_follow_the_schedule_table():
    assert list(age_band(np.array([0, 23 * H, 24 * H, 71 * H, 3 * 24 * H, 8 * 24 * H, 31 * 24 * H]))) \
        == [0, 0, 1, 1, 2, 3, 4]


def test_cadence_defaults_match_the_collectors(monkeypatch):
    from collector_runtime.config import Settings

    for item in fields(CollectionCadence):
        monkeypatch.delenv(item.name.upper(), raising=False)
    collector = Settings.load(env_file="/nonexistent")
    for item in fields(CollectionCadence):
        assert getattr(CADENCE, item.name) == getattr(collector, item.name), item.name
    overridden = CollectionCadence.from_environment({"POLL_INTERVAL_MINUTES": "10"})
    assert overridden.poll_interval_minutes == 10


@pytest.mark.benchmark
def test_preparing_1200_points_four_metrics_four_scales_is_fast():
    rng = np.random.default_rng(7)
    ages = np.cumsum(np.full(1200, 5 * M)) + rng.integers(-15, 15, 1200)
    columns = {metric.value: list(np.cumsum(rng.poisson(5, 1200))) for metric in Metric}
    series = post(ages, columns)
    moment = later(24 * 30)
    prepare(series, moment, CADENCE)
    best = min(_timed(lambda: prepare(series, moment, CADENCE)) for _ in range(20))
    assert best < 0.005, best


def _timed(action) -> float:
    started = time.perf_counter()
    action()
    return time.perf_counter() - started


def _rounded(values):
    return ["exact" if value < 1000 else "rounded" for value in values]


def test_views_past_a_thousand_are_estimated_inside_the_display_rounding():
    # Замер Пермского Политеха 07.10.2026: 996 точно на четвёртом часу, дальше
    # «1,03K» и т. д. К суткам точных просмотров нет.
    ages = [4 * H, 20.7 * H, 22.7 * H, 25.9 * H]
    values = [996, 1150, 1220, 1260]
    prepared = prepare(post(ages, {"views": values}, qualities={"views": _rounded(values)}), later(26), CADENCE)
    assert prepared.metrics[Metric.VIEWS].ages[-1] == 4 * H
    estimate = views_estimate_at(prepared, 24 * H)
    assert estimate is not None and estimate.rounded
    # Не ниже «1,22K» минус шаг и не выше «1,26K» плюс шаг.
    assert (estimate.low, estimate.high) == (1210, 1270)
    assert estimate.low <= estimate.value <= estimate.high


def test_coarse_display_unit_is_narrowed_by_finer_neighbours():
    # «1,1K» — шаг до ста; соседние «1,09K» и «1,12K» сужают коридор до 1 080–1 130.
    ages = [22 * H, 23 * H, 25 * H]
    values = [1090, 1100, 1120]
    prepared = prepare(post(ages, {"views": values}, qualities={"views": _rounded(values)}), later(26), CADENCE)
    estimate = views_estimate_at(prepared, 24 * H)
    assert (estimate.low, estimate.high) == (1080, 1130)


@pytest.mark.parametrize("platform,ages,values", [
    # Коридор шире 5 %: между замерами сутки роста.
    ("telegram", [2 * H, 40 * H], [1100, 2400]),
    # Округлённое число без контракта показа площадки — не оценка.
    ("vk", [23 * H, 25 * H], [1210, 1230]),
    # Снятые просмотры: счётчик убыл, коридор пуст.
    ("telegram", [23 * H, 25 * H], [1500, 1210]),
])
def test_views_are_not_estimated_without_a_tight_monotone_bracket(platform, ages, values):
    prepared = prepare(post(ages, {"views": values}, platform=platform, qualities={"views": _rounded(values)}),
                       later(41), CADENCE)
    assert views_estimate_at(prepared, 24 * H) is None


def test_exact_views_are_taken_as_they_are():
    ages = np.arange(0, 30 * H + 1, 15 * M)
    prepared = prepare(post(ages, {"views": list(ages // 100)}), later(30), CADENCE)
    estimate = views_estimate_at(prepared, 24 * H)
    assert not estimate.rounded and estimate.value == 24 * H // 100
