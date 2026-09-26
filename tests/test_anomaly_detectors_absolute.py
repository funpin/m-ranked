"""Абсолютные детекторы v2 на синтетическом эталоне: паттерны 1, 6, 7, 8, 9."""
from __future__ import annotations

import re
import time

import numpy as np
import pytest

from anomaly_analysis.v2.detectors import (
    ABSOLUTE_DETECTORS, DetectorContext, SiblingActivity, burst_plateau, linear_feed,
    reactions_before_views, reactions_exceed_views, synchronous_rise,
)
from anomaly_analysis.v2.series import DAY, CollectionCadence, prepare
from anomaly_reference.mature_norms import synthetic_cases

CASES = synthetic_cases()
HONEST = ("honest_organic_telegram", "honest_organic_vk", "honest_organic_max", "honest_organic_rutube",
          "honest_second_wave_vk", "honest_daily_rhythm_telegram", "honest_forward_large_channel_telegram",
          "honest_forward_vk_reposts", "honest_gaps_telegram", "honest_truncated_start_vk")


def run(detector, name):
    case = CASES[name]
    subject = case.subject
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())
    siblings = SiblingActivity.from_series(case.siblings, subject.observed_at[0].timestamp() - DAY,
                                           subject.observed_at[-1].timestamp()) if case.siblings else None
    return detector.detect(prepared, DetectorContext(subject.platform, None, siblings))


@pytest.mark.parametrize("detector,name", [
    (linear_feed, "p01_linear_feed_vk"),
    (linear_feed, "p01_linear_feed_rutube"),
    (linear_feed, "owner_vk_497246_linear_with_leading_likes"),
    (reactions_before_views, "p06_reactions_before_views_telegram"),
    (reactions_before_views, "owner_vk_497246_linear_with_leading_likes"),
    (reactions_before_views, "owner_vk_reaction_jumps_on_decayed_post"),
    (reactions_exceed_views, "p07_reactions_exceed_views_max"),
    (synchronous_rise, "p08_synchronous_rise_telegram"),
    (burst_plateau, "p09_burst_plateau_telegram"),
    (burst_plateau, "owner_vk_reaction_jumps_on_decayed_post"),
    (burst_plateau, "owner_vk_views_jump_second_day"),
])
def test_detector_finds_its_pattern_with_a_numeric_formula(detector, name):
    signs = run(detector, name)
    assert signs, name
    strongest = max(signs, key=lambda sign: sign.strength)
    assert strongest.pattern == detector.PATTERN and strongest.strength >= 0.7
    assert re.search(r"\d", strongest.formula) and strongest.render["kind"]
    assert not detector.NEEDS_NORM and strongest.norm_confidence is None


def test_linear_feed_formula_names_rate_fit_and_interval():
    (sign,) = [item for item in run(linear_feed, "owner_vk_497246_linear_with_leading_likes")
               if item.metric.value == "views"]
    # Просмотры растут с ~300 до ~26 000 за сутки после 1 д 21 ч.
    assert re.fullmatch(r"Δпросмотры ≈ 1 0\d\d·t \(t в часах\), R² = (0\.99\d|1\.000), t ∈ \[1д2[01]ч; 2д2[01]ч\], "
                        r"масштаб 1 ч", sign.formula), sign.formula
    assert sign.render["slope"] == pytest.approx(1070, rel=0.03)


def test_owner_reaction_jumps_are_both_found():
    jumps = sorted(sign.render["reactionsDelta"] for sign in run(reactions_before_views,
                                                                 "owner_vk_reaction_jumps_on_decayed_post"))
    assert jumps == [pytest.approx(1450, rel=0.02), pytest.approx(3300, rel=0.02)]


@pytest.mark.parametrize("name", HONEST)
@pytest.mark.parametrize("detector", ABSOLUTE_DETECTORS, ids=lambda item: item.ID)
def test_detector_is_silent_on_honest_cases(detector, name):
    assert run(detector, name) == ()


def test_synchronous_rise_needs_the_other_posts():
    case = CASES["p08_synchronous_rise_telegram"]
    prepared = prepare(case.subject, case.subject.observed_at[-1], CollectionCadence())
    assert synchronous_rise.detect(prepared, DetectorContext("telegram")) == ()


@pytest.mark.benchmark
def test_five_absolute_detectors_on_1200_points_are_fast():
    subject = CASES["honest_organic_telegram"].subject
    assert len(subject.observed_at) >= 1200
    prepared = prepare(subject, subject.observed_at[-1], CollectionCadence())

    def once():
        context = DetectorContext(subject.platform)
        started = time.perf_counter()
        for detector in ABSOLUTE_DETECTORS:
            detector.detect(prepared, context)
        return time.perf_counter() - started

    once()
    assert np.min([once() for _ in range(15)]) < 0.010
