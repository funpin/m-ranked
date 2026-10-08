"""Детекторы относительно нормы: паттерны 2, 4, 5, 10, мультимасштаб, пересылки."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import re
import time

import numpy as np
import pytest

from anomaly_analysis.v2.detectors import (
    NORM_RELATIVE_DETECTORS, DetectorContext, erv_outlier, gap_growth, late_spike, reactions_catch_up,
)
from anomaly_analysis.v2.levels import _context
from anomaly_analysis.v2.domain import Metric
from anomaly_analysis.v2.series import AGE_BAND_EDGES, CollectionCadence, engagement_at, prepare, views_estimate_at
from anomaly_reference.mature_norms import norms_for, synthetic_cases

CASES = synthetic_cases()


def context_for(name, *, subscribers=True):
    case = CASES[name]
    prepared = prepare(case.subject, case.subject.observed_at[-1], CollectionCadence())
    context = _context(prepared, case.siblings, norms_for(case), case.subscribers if subscribers else ())
    return prepared, context


def run(detector, name, **options):
    prepared, context = context_for(name, **options)
    return detector.detect(prepared, context)


@pytest.mark.parametrize("detector,name", [
    (late_spike, "p02_late_spike_telegram"),
    (late_spike, "owner_vk_views_jump_second_day"),
    (gap_growth, "p04_gap_growth_telegram"),
])
def test_detector_finds_its_pattern(detector, name):
    signs = run(detector, name)
    assert signs, name
    sign = max(signs, key=lambda item: item.strength)
    assert sign.pattern == detector.PATTERN and sign.strength >= 0.7
    assert detector.NEEDS_NORM and sign.norm_confidence is not None and sign.norm_confidence >= 0.5
    assert re.search(r"\d", sign.formula)


def test_late_rise_below_a_quarter_of_the_post_is_a_weak_signal():
    # Подъём +8 000 к ~60 000 просмотров значим по модели, но меньше четверти
    # набранного: к четвёртым суткам модель ждёт почти ноль, отсюда большой z.
    (sign,) = [sign for sign in run(late_spike, "p03_multiscale_rise_vk") if sign.metric.value == "views"]
    assert sign.strength == late_spike.NATURAL_CAP and sign.render["excessShare"] < late_spike.STRONG_SHARE


def test_conditional_underdispersion_is_only_an_exploratory_weak_sign():
    signs = run(reactions_catch_up, "p05_reactions_catch_up_vk")
    assert signs
    assert all(sign.strength <= reactions_catch_up.EXPLORATORY_CAP for sign in signs)
    assert all("conditional_count_variation" in sign.alternatives for sign in signs)


@pytest.mark.parametrize("name,direction", [("p10_high_erv_vk", 1), ("p10_low_erv_vk", -1)])
def test_erv_outside_the_account_norm_in_both_directions_is_only_a_weak_signal(name, direction):
    (sign,) = run(erv_outlier, name)
    assert np.sign(sign.render["z"]) == direction and abs(sign.render["z"]) >= 3
    assert 0.45 <= sign.strength <= erv_outlier.MAX_STRENGTH


def _telegram_display(series):
    """Тот же ряд, каким его показывает Telegram: с тысячи — три значащие цифры."""
    def shown(value):
        if value is None or value < 1000:
            return value
        unit = 10 ** (len(str(value)) - 3)
        return value // unit * unit
    views = tuple(shown(value) for value in series.values[Metric.VIEWS])
    qualities = {metric: tuple("rounded" if metric is Metric.VIEWS and value is not None and value >= 1000
                               else "exact" for value in series.values[Metric.VIEWS])
                 for metric in series.values}
    return replace(series, platform="telegram", values={**series.values, Metric.VIEWS: views},
                   qualities=qualities, interval_uncertain=())


@pytest.mark.parametrize("name,direction", [("p10_high_erv_vk", 1), ("p10_low_erv_vk", -1)])
def test_erv_is_found_through_rounded_telegram_views(name, direction):
    case = CASES[name]
    subject = _telegram_display(case.subject)
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    _, context = context_for(name)
    # Точные просмотры кончаются на первой тысяче — задолго до конца интервала.
    assert prepared.metrics[Metric.VIEWS].values[-1] < 1000
    (sign,) = erv_outlier.detect(prepared, replace(context, platform="telegram"))
    exact = run(erv_outlier, name)[0]
    assert np.sign(sign.render["z"]) == direction
    low, high = sign.render["views_range"]
    assert low < high and high / low - 1 <= 0.05
    assert abs(sign.render["z"] - exact.render["z"]) < 0.2
    assert "просмотры округлены площадкой" in sign.formula


def test_erv_inside_the_rounding_corridor_on_one_bound_is_not_a_sign():
    case = CASES["p10_high_erv_vk"]
    subject = _telegram_display(case.subject)
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    _, context = context_for("p10_high_erv_vk")
    (sign,) = erv_outlier.detect(prepared, replace(context, platform="telegram"))
    low, high = sign.render["views_range"]
    # Норма сдвинута так, что верхняя граница просмотров даёт z ровно на пороге,
    # а нижняя — выше: признак держится лишь на части коридора.
    band = sign.render["band"]
    cell = context.norm.cells[("erv", band)]
    engaged = engagement_at(prepared, float(AGE_BAND_EDGES[band + 1]))
    spread = max(1.4826 * cell.log_erv.mad, erv_outlier.SPREAD_FLOOR)
    median = float(np.log(engaged / high)) - (erv_outlier.MIN_Z - 0.01) * spread
    # По оценке просмотров отклонение по-прежнему за порогом.
    assert (float(np.log(engaged / views_estimate_at(prepared, float(AGE_BAND_EDGES[band + 1])).value))
            - median) / spread >= erv_outlier.MIN_Z
    shifted = replace(context.norm, cells={**context.norm.cells, ("erv", band):
                                           replace(cell, log_erv=replace(cell.log_erv, median=median))})
    assert erv_outlier.detect(prepared, replace(context, platform="telegram", norm=shifted)) == ()


def test_natural_forward_wave_is_capped_and_lower_with_subscriber_growth():
    name = "honest_forward_large_channel_telegram"
    unconfirmed = max(run(late_spike, name, subscribers=False), key=lambda item: item.strength)
    assert unconfirmed.render["shape"] == "wave" and unconfirmed.render["consistent"]
    assert unconfirmed.strength <= late_spike.NATURAL_CAP
    assert unconfirmed.alternatives[0] == "forward_by_large_channel"
    confirmed = max(run(late_spike, name), key=lambda item: item.strength)
    assert confirmed.strength <= late_spike.CONFIRMED_CAP < unconfirmed.strength


def test_vk_reposts_confirm_a_natural_wave():
    signs = run(late_spike, "honest_forward_vk_reposts", subscribers=False)
    assert signs and max(sign.strength for sign in signs) <= late_spike.CONFIRMED_CAP


@pytest.mark.parametrize("name,shape", [("owner_vk_views_jump_second_day", "step"),
                                        ("p01_linear_feed_vk", "ramp")])
def test_mechanical_shape_of_a_late_spike_stays_strong(name, shape):
    sign = max((item for item in run(late_spike, name) if item.metric.value == "views"),
               key=lambda item: item.strength)
    assert sign.render["shape"] == shape and sign.strength >= 0.7


@pytest.mark.parametrize("detector", NORM_RELATIVE_DETECTORS, ids=lambda item: item.ID)
def test_reposts_are_skipped(detector):
    assert run(detector, "honest_repost_of_foreign_telegram") == ()


def test_stretched_rise_is_invisible_at_fifteen_minutes_and_found_at_six_hours(monkeypatch):
    monkeypatch.setattr(late_spike, "SCALES", (timedelta(minutes=15),))
    assert not [sign for sign in run(late_spike, "p03_multiscale_rise_vk") if sign.metric.value == "views"]
    monkeypatch.setattr(late_spike, "SCALES", (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)))
    (sign,) = [sign for sign in run(late_spike, "p03_multiscale_rise_vk") if sign.metric.value == "views"]
    assert sign.scale >= timedelta(hours=1) and f"виден на масштабе {sign.scale.seconds // 3600} ч" in sign.formula


def test_without_a_norm_the_detectors_still_mark_their_confidence():
    case = CASES["p02_late_spike_telegram"]
    prepared = prepare(case.subject, case.subject.observed_at[-1], CollectionCadence())
    signs = late_spike.detect(prepared, DetectorContext("telegram"))
    assert signs and all(sign.norm_confidence == 0.0 for sign in signs)


@pytest.mark.benchmark
def test_four_relative_detectors_on_1200_points_are_fast():
    prepared, context = context_for("honest_organic_telegram")
    assert prepared.ages.size >= 1200

    def once():
        fresh = DetectorContext(context.platform, context.norm)
        started = time.perf_counter()
        for detector in NORM_RELATIVE_DETECTORS:
            detector.detect(prepared, fresh)
        return time.perf_counter() - started

    once()
    assert np.min([once() for _ in range(15)]) < 0.020
