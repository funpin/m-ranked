"""Детекторы относительно нормы: паттерны 2, 4, 5, 10, мультимасштаб, пересылки."""
from __future__ import annotations

from datetime import timedelta
import re
import time

import numpy as np
import pytest

from anomaly_analysis.v2.detectors import (
    NORM_RELATIVE_DETECTORS, DetectorContext, erv_outlier, gap_growth, late_spike, reactions_catch_up,
)
from anomaly_analysis.v2.levels import _context
from anomaly_analysis.v2.series import CollectionCadence, prepare
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
    (late_spike, "p03_multiscale_rise_vk"),
    (late_spike, "owner_vk_views_jump_second_day"),
    (gap_growth, "p04_gap_growth_telegram"),
    (reactions_catch_up, "p05_reactions_catch_up_vk"),
])
def test_detector_finds_its_pattern(detector, name):
    signs = run(detector, name)
    assert signs, name
    sign = max(signs, key=lambda item: item.strength)
    assert sign.pattern == detector.PATTERN and sign.strength >= 0.7
    assert detector.NEEDS_NORM and sign.norm_confidence is not None and sign.norm_confidence >= 0.5
    assert re.search(r"\d", sign.formula)


@pytest.mark.parametrize("name,direction", [("p10_high_erv_vk", 1), ("p10_low_erv_vk", -1)])
def test_erv_outside_the_account_norm_in_both_directions_is_only_a_weak_signal(name, direction):
    (sign,) = run(erv_outlier, name)
    assert np.sign(sign.render["z"]) == direction and abs(sign.render["z"]) >= 3
    assert 0.45 <= sign.strength <= erv_outlier.MAX_STRENGTH


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
    assert sign.scale == timedelta(hours=6) and "виден на масштабе 6 ч" in sign.formula


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
