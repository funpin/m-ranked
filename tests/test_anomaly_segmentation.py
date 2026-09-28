import numpy as np
import pytest

from anomaly_analysis.v2.detectors.base import pelt


def optimal_boundaries(values, penalty):
    """Unpruned dynamic-programming oracle, including first-minimum ties."""
    first = np.r_[0.0, np.cumsum(values)]
    second = np.r_[0.0, np.cumsum(values * values)]
    costs, previous = [-penalty], [0]
    for end in range(1, len(values) + 1):
        starts = np.arange(end)
        totals = first[end] - first[starts]
        scores = (np.asarray(costs) + second[end] - second[starts]
                  - totals * totals / (end - starts) + penalty)
        chosen = int(np.argmin(scores))
        costs.append(float(scores[chosen]))
        previous.append(chosen)
    bounds = [len(values)]
    while bounds[-1]:
        bounds.append(previous[bounds[-1]])
    return bounds[::-1]


@pytest.mark.parametrize("size", [0, 1, 4, 15, 39, 64, 65, 96])
def test_pelt_matches_unpruned_optimum_across_scalar_boundary(size):
    rng = np.random.default_rng(size)
    for values in (np.zeros(size), np.arange(size, dtype=float),
                   rng.normal(size=size), np.round(rng.normal(size=size) * 4)):
        for penalty in (0.25, 2.0, 100.0):
            assert pelt(values, penalty) == optimal_boundaries(values, penalty)
