"""Tests protect exclusion, observation support and scientific counterexamples."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.optimize import check_grad

SCRIPTS = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("tail_generalization", SCRIPTS / "tail_generalization.py")
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
P = G.P


def world():
    data = P.ordinary_world(np.random.default_rng(347))
    return data, {k: v[0].copy() for k, v in data.items()}, P.sim_reference(data)


def test_weighted_nb_gradient_matches_finite_differences():
    r = np.random.default_rng(23)
    x = np.column_stack((np.ones(70), r.normal(size=(70, 3))))
    y, off, w = r.poisson(2, 70), r.normal(size=70), r.uniform(.1, 3, 70)
    params = np.array([.1, .2, -.1, .1, -.3])
    assert check_grad(lambda b: G.nb_objective(b, x, y, off, w)[0],
                      lambda b: G.nb_objective(b, x, y, off, w)[1], params) < 1e-4


def test_equal_account_weight_is_not_equal_row_weight():
    rows = [{"account": "a"}] * 7 + [{"account": "b"}] * 3
    w = G.balanced_weights(rows, {"a": 1, "b": 1})
    assert w.sum() == pytest.approx(10)
    assert w[:7].sum() == pytest.approx(w[7:].sum())


def test_context_scaling_excludes_target_and_ignores_unrelated_accounts():
    c = {str(i): np.array([i/10, i % 3]) for i in range(25)}
    fit = [str(i) for i in range(1, 25)]
    w, a = G.context_weights(c, fit, "0")
    c["not_in_fit"] = np.array([1e12, -1e12])
    w2, a2 = G.context_weights(c, fit, "0")
    assert w == w2
    np.testing.assert_array_equal(a["scale"], a2["scale"])
    with pytest.raises(ValueError):
        G.context_weights(c, ["0"] + fit, "0")


def test_preperiod_context_does_not_read_outcomes_or_later_publications():
    def post(date, kind, repost=False):
        return {"published": P.tail.dt(date), "post": {"primary_account_id": "a", "publication_type": kind,
                                                        "is_repost": repost}, "early24": {"r": 10000}}
    initial = [post("2026-09-13T21:00:00+03:00", "text")]
    a, _ = G.publication_context(initial, ["a"])
    initial[0]["early24"]["r"] = 0
    b, _ = G.publication_context(initial+[post("2026-09-14T00:00:00+03:00", "video")], ["a"])
    np.testing.assert_array_equal(a["a"], b["a"])


def test_new_core_matches_previous_components_when_fully_observed():
    data, one, ref = world()
    f = G.features(one, ref, np.ones((10, 20), bool))
    old = P.sim_account_scores(one, ref, 20)
    assert max(P.joint(f[:4]), P.joint(f[4:8])) == pytest.approx(old["independent_joint"])
    assert np.all(np.isfinite(f)) and f.shape == (18,)


def test_missing_counts_cannot_influence_features():
    _, one, ref = world()
    mask = np.ones((10, 20), bool)
    mask[:, [0, 4, 9, 15]] = False
    before = G.features(one, ref, mask)
    one["r"][20:][~mask] = 100000
    one["v"][20:][~mask] = 1
    np.testing.assert_allclose(before, G.features(one, ref, mask))


def test_no_bridging_missing_days_or_posts_for_pair_support():
    _, one, ref = world()
    mask = np.zeros((10, 20), bool)
    mask[[0, 2, 4, 6, 8]] = True
    assert G.features(one, ref, mask) is None  # No adjacent observed days.
    mask[:] = False
    mask[:, ::2] = True
    assert G.features(one, ref, mask) is None  # No adjacent observed archive positions.
    mask[:] = True
    mask[2:] = False
    assert G.features(one, ref, mask) is None  # Only two days.


def test_temporal_pairs_really_are_the_same_post():
    np.testing.assert_array_equal(P.POST_INDEX[20:29, :-2], P.POST_INDEX[21:30, 2:])


def test_change_dependent_mask_is_applied_after_injection():
    _, one, _ = world()
    one["r"][:] = 0
    u = np.full((10, 20), .6)
    assert not G.observation_mask(one, u, "change_biased").any()
    one["r"][20:] += 1
    assert G.observation_mask(one, u, "change_biased").all()


def test_ordinary_sessions_add_views_with_reactions_in_generator():
    data, _, _ = world()
    for family in ("contiguous_walk", "regular_reader", "dense_walk", "scheduled_campaign"):
        one = G.alter(data, 0, family, np.random.default_rng(24))
        dr, dv = one["r"]-data["r"][0], one["v"]-data["v"][0]
        assert np.all(dr >= 0) and np.all(dr <= dv)


def test_identical_delayed_reactors_are_an_explicit_aggregate_counterexample():
    data, _, ref = world()
    organic = G.alter(data, 0, "delayed_reactors", np.random.default_rng(90))
    artificial = G.alter(data, 0, "small_daily30", np.random.default_rng(90))
    for key in organic:
        np.testing.assert_array_equal(organic[key], artificial[key])
    np.testing.assert_array_equal(G.features(organic, ref, np.ones((10, 20), bool)),
                                  G.features(artificial, ref, np.ones((10, 20), bool)))


def test_whole_target_exclusion_keeps_reference_for_persistent_change():
    data, _, ref = world()
    for key in data:
        data[key][0] += 10000
    changed = P.sim_reference(data)
    assert changed["conditional"] == ref["conditional"]
    np.testing.assert_array_equal(changed["structural"], ref["structural"])


def test_external_threshold_rejects_insufficient_support_and_handles_ties():
    assert G.conservative_threshold(np.ones(199)) is None
    assert G.conservative_threshold(np.ones(400)) == 1
    assert G.rates(np.array([1., 1., np.nan]), 1)["flags"] == 0
    assert G.rates(np.array([1., 1., np.nan]), 1)["abstained"] == 1
    assert G.rates(np.array([100.]), None)["status"] == "abstain_insufficient_calibration"


def test_stricter_calibration_is_fixed_by_order_statistic_not_test_scores():
    values = np.arange(400, dtype=float)
    relaxed = G.conservative_threshold(values, alpha=.025)
    strict = G.conservative_threshold(values, alpha=.005)
    assert (values > relaxed).sum() == 9
    assert (values > strict).sum() == 1
    assert strict > relaxed


def test_availability_query_cannot_change_storage_or_read_unbounded_history():
    sql = G.AVAILABILITY_SQL.upper()
    assert "BEGIN READ ONLY" in sql and "LIMIT 100001" in sql and "INTERVAL '7 DAYS'" in sql
    assert all(word not in sql for word in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))
