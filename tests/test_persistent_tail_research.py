"""Leakage, observed support and counterfactual invariants, not fitted coefficient tests."""
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("persistent_tail_validation", SCRIPTS / "persistent_tail_validation.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def test_partition_removes_account_without_repartitioning_the_others():
    accounts = [f"account-{i}" for i in range(81)]
    a, b = P.partition(accounts)
    for target in accounts:
        x, y = P.partition(accounts, target)
        assert x == [v for v in a if v != target]
        assert y == [v for v in b if v != target]
        assert target not in x+y and not set(x) & set(y)


def test_no_rank_when_resolution_is_insufficient_even_for_infinite_increase():
    assert P.rank(1e20, np.arange(18))["status"] == "abstain"
    assert P.rank(1e20, np.arange(19))["rank"] == .05
    assert P.rank(1e20, np.arange(80), alpha=.05/81)["status"] == "abstain"


def test_ties_are_conservative_and_other_platforms_do_not_inherit_max():
    assert P.rank(10, np.full(30, 10))["rank"] == 1
    for platform in ("telegram", "vk", "rutube"):
        assert P.rank(1e20, np.arange(300), platform_name=platform)["status"] == "abstain"


def test_nonfinite_input_is_not_silent_no_signal():
    with pytest.raises(ValueError):
        P.rank(float("nan"), np.arange(30))


def test_one_or_two_days_cannot_prove_three_day_recurrence():
    assert P.block_features([[10, 1, 4], [10, 1, 4]]) is None
    f = P.block_features([[10, 1, 4], [0, 0, 0], [0, 0, 0], [0, 0, 0]])
    assert f[1] == 0 and P.joint(f) == 0


def test_exact_occupancy_counterexample_and_pair_formula():
    y, mu = np.ones((1, 20)), np.ones((1, 20))
    c = P.components(y, mu)
    expected = 20*(1-(19/20)**20)
    assert c[0, 1] == pytest.approx((20-expected)/20)
    assert c[0, 2] == 0
    y = np.arange(1, 21)[None, :]
    positive = np.clip((y-mu)/np.sqrt(mu+.4*mu**2+1), 0, 5)[0]
    pairs = [positive[i]*positive[j] for i in range(20) for j in range(20) if i != j]
    assert P.components(y, mu)[0, 2] == pytest.approx(np.mean(pairs))


def test_observed_zero_counts_are_valid_and_missing_days_are_not_filled():
    row = dict(account="a", day=P.FIRST[0], actual_start_age=5, q24=.03, dr=0)
    rows = [dict(row) for _ in range(5)]
    opp = {("a", d, "4–7"): 10 for d in P.FIRST}
    days = P.observations(rows, opp, ["a"])["a"]
    assert days[0]["eligible"] and days[0]["coverage"] == .5
    assert not days[1]["eligible"] and days[1]["n"] == 0
    assert P.profile(days, P.FIRST, [])["reason"] == "fewer_than_three_observed_days"
    rows[0]["q24"] = None
    assert not P.observations(rows, opp, ["a"])["a"][0]["eligible"]


def world():
    return P.ordinary_world(np.random.default_rng(74))


def test_entire_target_history_is_excluded_from_peer_fit_and_calibration():
    data = world()
    before = P.clone(data)
    reference = P.sim_reference(data)
    calibration = P.sim_calibration(data, reference)
    changed = P.clone(data)
    for key in changed:
        changed[key][0] += 1000000
    new_reference = P.sim_reference(changed)
    new_calibration = P.sim_calibration(changed, new_reference)
    for key in ("structural", "conditional"):
        np.testing.assert_array_equal(reference[key], new_reference[key])
    for key in P.METHODS:
        np.testing.assert_array_equal(calibration[key], new_calibration[key])
    for key in data:
        np.testing.assert_array_equal(data[key], before[key])


def test_no_future_or_calibration_outcomes_leak_into_peer_fit():
    data = world()
    first = P.sim_reference(data)
    data["r"][:, 10:] += 10000
    data["r"][P.CAL, :10] += 10000
    second = P.sim_reference(data)
    np.testing.assert_array_equal(first["structural"], second["structural"])
    assert first["conditional"] == second["conditional"]


def test_fractional_dose_is_not_destroyed_by_per_interval_rounding():
    data = world()
    r, er = data["r"][0], data["early_r"][0]
    changed, early = P.scale_paths(r, er, .1, np.random.default_rng(3))
    assert changed.sum() > r.sum()
    for post in range(P.NPOSTS):
        locations = P.POST_INDEX == post
        actual = int(early[post]-er[post]) + int((changed-r)[locations].sum())
        expected = .1*(int(er[post])+int(r[locations].sum()))
        assert abs(actual-expected) < 1+1e-10


def test_integer_double_preserves_er_all_periods_and_the_observational_boundary():
    data = world()
    one = P.alter(data, 0, "preserve_er100", np.random.default_rng(4))
    alternative = P.alter(data, 0, "audience_growth", np.random.default_rng(17))
    for key in data:
        np.testing.assert_array_equal(one[key], 2*data[key][0])
        np.testing.assert_array_equal(one[key], alternative[key])
    np.testing.assert_array_equal(one["r"]*data["v"][0], data["r"][0]*one["v"])
    ref = P.sim_reference(data)
    cal = P.sim_calibration(data, ref)
    assert P.decisions(one, ref, cal) == P.decisions(alternative, ref, cal)


def test_daily_addition_includes_fit_cal_and_test_without_changing_early_er():
    data = world()
    one = P.alter(data, 0, "small_daily100", np.random.default_rng(6))
    np.testing.assert_array_equal(one["r"], data["r"][0]+1)
    np.testing.assert_array_equal(one["early_r"], data["early_r"][0])


def test_simulation_is_reproducible_and_never_receives_hidden_parameters():
    a, b = world(), world()
    assert set(a) == {"r", "v", "early_r", "early_v"}
    for key in a:
        np.testing.assert_array_equal(a[key], b[key])
    reference = P.sim_reference(a)
    for method, values in P.sim_calibration(a, reference).items():
        assert values.shape == (30,) and np.all(np.isfinite(values))


def test_ordinary_alternatives_respect_simulated_one_reaction_per_view():
    data = world()
    for i, scenario in enumerate(P.ORDINARY):
        x = P.alter(data, 0, scenario, np.random.default_rng(i))
        assert np.all(x["r"] <= x["v"])
        assert np.all(x["early_r"] <= x["early_v"])


def test_zero_events_still_have_nonzero_upper_uncertainty():
    assert P.wilson(0, 600)[1] > 0
    assert P.wilson(1, 0) is None


def test_calendar_block_removal_never_becomes_seven_independent_trials():
    days = [{"day": d, "models": {m: {"components": [1, .2, .3]} for m in P.MODES}}
            for d in P.SECOND[:3]]
    p = {"status": "eligible", "days": 3, "daily": days}
    assert P.drop_calendar_day(p, P.SECOND[0])["status"] == "abstain"
    assert P.drop_calendar_day(p, P.SECOND[4])["days"] == 3
    original = [d["day"] for d in p["daily"]]
    P.drop_calendar_day(p, P.SECOND[1])
    assert [d["day"] for d in p["daily"]] == original


def test_fit_transform_is_learned_only_from_training_not_evaluation_types():
    rows = []
    for i in range(100):
        rows.append(dict(age=4+i % 9, new_posts=i % 5, depth=i % 10, day=P.FIRST[i % 7],
                         type="text", hours=24, dv=i % 20, q24=.04, v24=100+i,
                         dr=i % 3, account=f"p{i % 10}"))
    model = P.fit_model(rows, "conditional")
    digest = P.model_digest(model)
    target = [dict(rows[0], type="unseen-target-type", account="excluded", day=P.SECOND[0], v24=10**9)]
    P.predict(model, target)
    assert P.model_digest(model) == digest
    assert "unseen-target-type" not in model["types"]
    assert "excluded" not in model["accounts"]


def test_inclusive_self_comparator_uses_target_cal_but_never_target_test():
    data = world()
    ref = P.sim_reference(data)
    cal = P.sim_calibration(data, ref)
    one = {k: v[0].copy() for k, v in data.items()}
    before = P.inclusive_self_calibration(one, ref, cal)
    one["r"][20:] += 10000
    np.testing.assert_array_equal(P.inclusive_self_calibration(one, ref, cal), before)
    one["r"][10:20] += 10000
    after = P.inclusive_self_calibration(one, ref, cal)
    assert len(after) == 30 and after[-1] != before[-1]
    np.testing.assert_array_equal(after[:29], before[:29])
