import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("post_curve_similarity", SCRIPTS / "post_curve_similarity.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def test_level_and_shape_are_different_properties():
    y = np.arange(1, 9)[:, None]*np.array([3, 2, 1, 1])[None]
    values, n = C.curve_statistics(y, np.full(y.shape, 24.))
    assert n[0] == 8 and values[0, 0] > .4
    assert values[0, 1] == pytest.approx(0, abs=1e-15)
    same_total = np.array([[3, 0, 0, 0], [0, 3, 0, 0], [0, 0, 3, 0], [0, 0, 0, 3]]*2)
    values, _ = C.curve_statistics(same_total, np.full(same_total.shape, 24.))
    assert values[0, 0] == 0 and values[0, 1] > .5


def test_vectorized_pair_distance_matches_explicit_pairs():
    y = np.random.default_rng(45).poisson(3, (11, 4))
    y[0] = 0
    h = np.full(y.shape, 24.)
    measured, _ = C.curve_statistics(y, h)
    active = y[y.sum(axis=1) >= 3]
    proportions = active/active.sum(axis=1, keepdims=True)
    pairs = [np.abs(a-b).sum()/2 for i, a in enumerate(proportions) for b in proportions[i+1:]]
    assert measured[0, 1] == pytest.approx(np.mean(pairs))


def test_zero_and_small_integer_curves_cannot_be_evidence_of_copying():
    y = np.zeros((20, 4), int)
    y[:, 0] = 1
    values, n = C.curve_statistics(y, np.full(y.shape, 24.))
    assert n[0] == 0 and np.all(np.isnan(values))
    out = C.assess(y, np.full(y.shape, 24.), {}, 44)
    assert out["status"] == "abstain"


def test_missing_age_is_not_filled_from_neighbouring_post_or_day():
    rows = [{"id": "a", "actual_start_age": a+.2, "day": str(a)} for a in (4, 5, 7)]
    rows += [{"id": "b", "actual_start_age": 6.2, "day": "6"}]
    complete, seen = C.profiles(rows, (4, 5, 6, 7))
    assert complete == {} and seen == 2


def test_observed_interval_duration_changes_rate_not_count_totals():
    y = np.full((8, 4), 4)
    h = np.full((8, 4), 24.)
    h[0] = 18
    values, _ = C.curve_statistics(y, h)
    assert values[0, 0] > 0 and values[0, 1] == pytest.approx(0, abs=1e-15)


def test_null_ties_are_conservative_and_post_order_does_not_define_similarity():
    y = np.full((10, 4), 3)
    hours = np.full(y.shape, 24.)
    a, _ = C.curve_statistics(y, hours)
    b, _ = C.curve_statistics(y[::-1], hours[::-1])
    np.testing.assert_allclose(a, b)
    assert np.all(a == 0)


def test_simulated_profiles_are_age_aligned_whole_posts_in_test_period():
    data = C.P.ordinary_world(np.random.default_rng(71))
    one = {k: v[0] for k, v in data.items()}
    y, h, means = C.sim_profiles(one, C.P.sim_reference(data))
    assert y.shape == (14, 4) and h.shape == y.shape
    assert all(m.shape == y.shape for m in means.values())
