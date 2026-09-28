"""Guard the meaning of injected doses and the observation process."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import binom

SCRIPT = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts/masked_engagement_validation.py"
SPEC = importlib.util.spec_from_file_location("masked_research", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def sample():
    mask = np.ones((3, 12, 14), bool)
    mask[:, :, 4:6] = False
    mask[:, 2, [2, 9]] = False
    views = 10*mask.astype(int)
    reactions = 3*mask.astype(int)
    return views, reactions, mask, views.astype(float), .5*mask


@pytest.mark.parametrize("name", ["smooth_joint", "proportional_path", "diffuse_reactions",
    "shared_reaction_pulses", "independent_reaction_pulses", "common_exposure_event", "reaction_delay"])
def test_zero_dose_is_identity_and_inputs_are_not_mutated(name):
    original = sample()
    before = [a.copy() for a in original]
    zero = M.perturb(original, name, 0, 97)
    for a, b in zip(zero, before):
        np.testing.assert_array_equal(a, b)
    changed = M.perturb(original, name, .5, 98)
    for a, b in zip(original, before):
        np.testing.assert_array_equal(a, b)
    assert (changed[0][~original[2]] == 0).all()
    assert (changed[1][~original[2]] == 0).all()
    assert (changed[0] >= 0).all() and (changed[1] >= 0).all()
    assert np.isfinite(M.features(*changed)).all()


def test_sparse_dose_is_unbiased_and_preserves_cumulative_shape():
    counts = np.tile([0, 1, 0, 1, 0, 1], (100000, 1))
    extra = M.proportional_increments(counts, .1, np.random.default_rng(57))
    assert abs(extra.sum()/counts.sum()-.1) < .002
    assert (extra[:, [0, 2, 4]] == 0).all()
    assert (np.abs(np.cumsum(extra, axis=-1)-.1*np.cumsum(counts, axis=-1)) < 1).all()
    np.testing.assert_array_equal(M.proportional_increments(counts, 1, np.random.default_rng(12)), counts)


def test_exact_doubling_preserves_both_counter_paths():
    original = sample()
    changed = M.perturb(original, "proportional_path", 1, 12)
    np.testing.assert_array_equal(changed[0], 2*original[0])
    np.testing.assert_array_equal(changed[1], 2*original[1])


def test_delay_conserves_every_post_and_does_not_bridge_a_missing_day():
    original = sample()
    changed = M.perturb(original, "reaction_delay", 1, 13)
    np.testing.assert_array_equal(changed[1].sum(axis=-1), original[1].sum(axis=-1))
    # Last day before a gap retains its own reactions and receives the previous day's.
    np.testing.assert_array_equal(changed[1][:, :, 3], original[1][:, :, 2]+original[1][:, :, 3])
    assert (changed[1][:, :, 4:6] == 0).all()
    # First day after a gap transfers away, but never receives from before the gap.
    assert (changed[1][:, :, 6] == 0).all()
    np.testing.assert_array_equal(changed[0], original[0])
    with pytest.raises(ValueError):
        M.perturb(original, "reaction_delay", 1.1, 13)


def test_shared_and_independent_pulses_have_equal_expected_per_post_dose(monkeypatch):
    original = sample()
    # A deterministic mean oracle isolates allocation from negative-binomial noise.
    monkeypatch.setattr(M, "nb", lambda rng, mu, alpha=.4: np.rint(mu).astype(int))
    shared = M.perturb(original, "shared_reaction_pulses", 1, 17)
    independent = M.perturb(original, "independent_reaction_pulses", 1, 17)
    np.testing.assert_array_equal(shared[1].sum(axis=-1), independent[1].sum(axis=-1))
    np.testing.assert_array_equal(shared[1][:, 2], original[1][:, 2])
    assert not np.array_equal(shared[1], independent[1])


def test_generator_is_reproducible_without_filling_missing_observations(monkeypatch):
    monkeypatch.setattr(M, "N", 32)
    designs = sample()[2:]
    first, second = M.simulate(designs, 47), M.simulate(designs, 47)
    for a, b in zip(first, second):
        np.testing.assert_array_equal(a, b)
    assert (first[0][~first[2]] == 0).all()
    assert (first[1][~first[2]] == 0).all()
    assert np.isfinite(M.features(*first)).all()


def test_tolerance_order_controls_binomial_tail_and_ties_are_conservative():
    order = int(binom.ppf(.95, M.N, 1-M.ALPHA))+1
    assert binom.sf(order-1, M.N, .95) <= .05
    assert binom.sf(order-2, M.N, .95) > .05
    ranks = M.component_ranks(np.ones((4, 6)), np.ones((20, 6)))
    assert (ranks == 0).all()
    assert not (ranks.max(axis=1) > M.cutoff(ranks.max(axis=1))).any()
