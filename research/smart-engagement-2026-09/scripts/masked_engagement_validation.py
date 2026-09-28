"""Research stress tests, no production writes and no inferred fraud labels.

Run beside observable_validation.py and analyze_max_tail.py. All simulations
are calibrated to their stated generator, not to a certified organic MAX norm.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform

import numpy as np
import scipy
from scipy.stats import binom

SEED = 20260928 + 1300
N = 1500
ALPHA = .05
COMPONENTS = ("views_volume", "conditional_reactions", "breadth", "underdispersion",
              "residual_coordination", "reaction_lag")


def helper(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rate(flags):
    flags = np.asarray(flags, bool)
    n, hits = len(flags), int(flags.sum())
    if not n:
        return {"n": 0, "hits": 0, "rate": None}
    p, z = hits/n, 1.959963984540054
    center = (p+z*z/(2*n))/(1+z*z/n)
    half = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return {"n": n, "hits": hits, "rate": p, "wilson95": [center-half, center+half]}


def cutoff(values):
    ordered = np.sort(values)
    index = min(len(ordered)-1, int(np.ceil((len(ordered)+1)*(1-ALPHA)))-1)
    return float(ordered[index])


def early_masking(path):
    old = helper("observable_validation")
    posts, sha = old.load_panel(path)
    rows = [p for p in posts if p["platform"] == "max" and old.split(p) != "embargo"
            and old.valid(p["endpoints"][24], "v", True)
            and old.valid(p["endpoints"][72], "v", True)
            and p["endpoints"][72]["v"] >= p["endpoints"][24]["v"]]
    groups = {s: np.array([i for i, p in enumerate(rows) if old.split(p) == s])
              for s in ("fit", "cal", "test")}
    y = np.log1p([p["endpoints"][72]["v"] for p in rows])
    early = np.array([p["endpoints"][24]["v"] for p in rows])
    late = np.array([p["endpoints"][72]["v"] for p in rows])
    accounts = sorted({rows[i]["primary_account_id"] for i in groups["fit"]})
    result = {"input_sha256": sha, "counts": {k: len(v) for k, v in groups.items()}, "models": {}}
    for mode in ("conditional_v24", "historical_account_only"):
        def design(v24):
            if mode == "conditional_v24":
                return np.column_stack([np.ones(len(rows)), np.log1p(v24)])
            return np.column_stack([np.ones(len(rows))] + [np.array([
                p["primary_account_id"] == account for p in rows], float) for account in accounts])
        x = design(early)
        penalty = np.eye(x.shape[1])*10
        penalty[0, 0] = 0
        train, cal, test = (groups[k] for k in ("fit", "cal", "test"))
        beta = np.linalg.solve(x[train].T@x[train]+penalty, x[train].T@y[train])
        prediction = x@beta
        residual = y[cal]-prediction[cal]
        def flagged(v24, v72):
            score = np.log1p(v72[test])-(design(v24)@beta)[test]
            ranks = (1+(residual[:, None] >= score).sum(axis=0))/(len(cal)+1)
            return ranks <= ALPHA
        base = flagged(early, late)
        account_ids = np.array([rows[i]["primary_account_id"] for i in test])
        def empirical(flags, keep=None):
            keep = np.ones(len(test), bool) if keep is None else keep
            return old.observed_rate(flags[keep], account_ids[keep], np.random.default_rng(SEED+13))
        report = {"base_alerts_unlabeled": empirical(base),
                  "test_mae_log1p": float(np.abs(y[test]-prediction[test]).mean()),
                  "log_v24_coefficient": float(beta[1]) if mode == "conditional_v24" else None,
                  "injections": {}}
        for fraction in (.1, .3, 1.):
            changed_late = late + np.rint(fraction*late).astype(int)
            late_flags = flagged(early, changed_late)
            early_flags = flagged(early+np.rint(fraction*early).astype(int), changed_late)
            report["injections"][str(fraction)] = {
                "late_only": {"all": empirical(late_flags), "new_among_base_clear": empirical(late_flags, ~base)},
                "already_in_v24": {"all": empirical(early_flags), "new_among_base_clear": empirical(early_flags, ~base)}}
        result["models"][mode] = report
    result["scope"] = "actual held-out endpoints with specified additions; original posts are unlabeled; account bootstrap is not a population guarantee"
    return result


def contaminated_history():
    rng = np.random.default_rng(SEED+14)
    train = rng.normal(np.log(1000), .3, (N, 10, 40))
    cal = rng.normal(np.log(1000), .3, (N, 10, 40))
    test = rng.normal(np.log(1000), .3, N)
    order_fit = rng.random(train.shape)
    order_cal = rng.random(cal.shape)
    target = np.zeros((1, 10, 1), bool)
    target[:, :3] = True
    results = []
    for fraction in (0., .25, .5, .75, 1.):
        fit = train + ((order_fit < fraction) & target)*np.log(2)
        for contaminate_calibration in (False, True):
            calibration = cal + ((order_cal < fraction) & target)*np.log(2)*contaminate_calibration
            for method in ("own_mean", "own_median", "peer_median"):
                if method == "own_mean":
                    prediction = fit.mean(axis=2)
                elif method == "own_median":
                    prediction = np.median(fit, axis=2)
                else:
                    prediction = np.column_stack([np.median(np.delete(fit, i, axis=1).reshape(N, -1), axis=1)
                                                  for i in range(10)])
                scores = (calibration-prediction[:, :, None]).reshape(N, -1)
                # Every row is an independent world with its own disjoint calibration history.
                threshold = np.sort(scores, axis=1)[:, int(np.ceil((scores.shape[1]+1)*.95))-1]
                clean_score = test-prediction[:, 0]
                results.append({"contaminated_fraction": fraction, "calibration_also_contaminated": contaminate_calibration,
                                "method": method, "median_norm_multiplier": float(np.median(np.exp(prediction[:, 0])/1000)),
                                "clean_test_alerts": rate(clean_score > threshold),
                                "double_count_test_alerts": rate(clean_score+np.log(2) > threshold)})
    return {"worlds": N, "accounts_per_world": 10, "target_and_two_peers_modified": True,
            "fit_posts_per_account": 40, "calibration_posts_per_account": 40,
            "scope": "synthetic matched account populations; peer comparability is stipulated, not established for real universities",
            "results": results}


def templates(panel):
    tail = helper("analyze_max_tail")
    posts, clocks, sha = tail.load(panel)
    rows, _, audit, _ = tail.intervals(posts, clocks)
    by = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["actual_start_age"] >= 4 and row["q24"] is not None:
            by[row["account"]][row["id"]].append(row)
    output = []
    for account, post_rows in sorted(by.items()):
        selected = sorted((p for p, rs in post_rows.items() if len(rs) >= 2),
                          key=lambda p: hashlib.sha256(p.encode()).hexdigest())[:12]
        if len(selected) < 6 or sum(len(post_rows[p]) for p in selected) < 24:
            continue
        mask = np.zeros((12, 14), bool)
        mu = np.zeros((12, 14))
        q = np.zeros((12, 14))
        for i, post in enumerate(selected):
            for row in post_rows[post]:
                j = tail.DAYS.index(row["day"])
                mask[i, j] = True
                # Fixed exposure design, NOT an estimated organic expectation.
                mu[i, j] = max(.1, row["dv"])
                q[i, j] = np.clip(row["q24"], .005, .2)*np.exp(-.12*(row["age"]-1))
        output.append((mask, mu, q))
    if not output:
        raise ValueError("no eligible MAX observation templates")
    return tuple(np.stack([item[i] for item in output]) for i in range(3)), {
        "panel_sha256": sha, "accounts": len(output), "intervals": int(sum(t[0].sum() for t in output)),
        "audit_before_template_selection": audit,
        "selection": "at least 6 posts and 24 late intervals, >=2 intervals/post, up to 12 posts by SHA256(id); no anomaly-label selection"}


def nb(rng, mu, alpha=.4):
    return rng.negative_binomial(1/alpha, 1/(1+alpha*mu))


def simulate(designs, seed):
    rng = np.random.default_rng(seed)
    chosen = rng.integers(len(designs[0]), size=N)
    mask, mu, q = (a[chosen] for a in designs)
    post = np.exp(rng.normal(-.3**2/2, .3, (N, 12, 1)))
    day = np.exp(rng.normal(-.35**2/2, .35, (N, 1, 14)))
    views = rng.poisson(mu*post*day)*mask
    propensity = np.exp(rng.normal(-.25**2/2, .25, (N, 12, 1)))
    reaction_day = np.exp(rng.normal(-.2**2/2, .2, (N, 1, 14)))
    reactions = nb(rng, q*views*propensity*reaction_day)*mask
    return views, reactions, mask, mu, q


def features(views, reactions, mask, mu, q):
    axis = (1, 2)
    size = mask.sum(axis=axis)
    expected = q*views
    volume = np.log((views.sum(axis=axis)+.5)/(mu.sum(axis=axis)+.5))
    response = np.log((reactions.sum(axis=axis)+.5)/(expected.sum(axis=axis)+.5))
    active_expected = (1-(1+.4*expected)**(-1/.4))*mask
    breadth = ((reactions > 0).sum(axis=axis)-active_expected.sum(axis=axis))/np.sqrt(size)
    fitted_ratio = (reactions.sum(axis=axis)+.5)/(expected.sum(axis=axis)+.5)
    fitted = expected*fitted_ratio[:, None, None]
    underdispersion = -(((reactions-fitted)**2/(fitted+.4*fitted**2+.1))*mask).sum(axis=axis)/size
    z = (reactions-expected)/np.sqrt(expected+.4*expected**2+.1)*mask
    post_mean = z.sum(axis=2)/np.maximum(mask.sum(axis=2), 1)
    centered = (z-post_mean[:, :, None])*mask
    daily_n = mask.sum(axis=1)
    pair_score = (centered.sum(axis=1)**2-(centered**2).sum(axis=1))/np.maximum(daily_n*(daily_n-1), 1)
    pair_score[daily_n < 4] = 0
    coordination = pair_score.max(axis=1)
    zv = (views-mu)/np.sqrt(mu+.3*mu**2+.1)*mask
    adjacent = mask[:, :, 1:] & mask[:, :, :-1]
    lag = ((z[:, :, 1:]*(zv[:, :, :-1]-zv[:, :, 1:]))*adjacent).sum(axis=axis)/np.maximum(adjacent.sum(axis=axis), 1)
    result = np.column_stack([volume, response, breadth, underdispersion, coordination, lag])
    if not np.isfinite(result).all():
        raise ValueError("nonfinite research score")
    return result


def component_ranks(scores, fit_scores):
    return np.column_stack([np.searchsorted(np.sort(fit_scores[:, j]), scores[:, j], side="left")/(len(fit_scores)+1)
                            for j in range(scores.shape[1])])


def proportional_increments(counts, fraction, rng):
    """Unbiased integer scaling with one random phase per cumulative path.

    E[floor(f*C+U)] = f*C for U uniform on [0,1). Every cumulative
    discrepancy is <1, and zero increments remain zero. A fixed .5 phase
    would systematically erase small doses on paths with very few reactions.
    """
    if fraction < 0:
        raise ValueError("fraction must be nonnegative")
    phase = rng.random(counts.shape[:-1]+(1,))
    cumulative = np.floor(fraction*np.cumsum(counts, axis=-1)+phase).astype(int)
    return np.diff(cumulative, axis=-1, prepend=0)


def perturb(sample, name, fraction, seed):
    views, reactions, mask, mu, q = sample
    views, reactions = views.copy(), reactions.copy()
    rng = np.random.default_rng(seed)
    if name == "smooth_joint":
        extra = rng.poisson(fraction*mu)*mask
        views += extra
        reactions += nb(rng, q*extra)*mask
    elif name == "proportional_path":
        views += proportional_increments(views, fraction, rng)
        reactions += proportional_increments(reactions, fraction, rng)
    elif name == "diffuse_reactions":
        reactions += nb(rng, fraction*q*mu)*mask
    elif name in {"shared_reaction_pulses", "independent_reaction_pulses", "common_exposure_event"}:
        pulse = np.zeros(mask.shape, bool)
        if name != "independent_reaction_pulses":
            # Two calendar dates are fixed before outcomes, never selected by maximum score.
            pulse[:, :, [2, 9]] = mask[:, :, [2, 9]]
        else:
            for i in range(len(mask)):
                for j in range(mask.shape[1]):
                    days = np.flatnonzero(mask[i, j])
                    if len(days) and (mask[i, j, 2] or mask[i, j, 9]):
                        pulse[i, j, rng.choice(days, size=min(2, len(days)), replace=False)] = True
        # Same per-post expected dose where selected dates are observed.
        weights = pulse*mu
        total = weights.sum(axis=2, keepdims=True)
        allocation = weights/np.maximum(total, 1e-12)
        if name == "common_exposure_event":
            extra = rng.poisson(fraction*mu.sum(axis=2, keepdims=True)*allocation)
            views += extra
            reactions += nb(rng, q*extra)*mask
        else:
            reactions += nb(rng, fraction*(q*mu).sum(axis=2, keepdims=True)*allocation)*mask
    elif name == "reaction_delay":
        # Move a fraction to the NEXT CALENDAR day only if both days were observed.
        if fraction > 1:
            raise ValueError("delay fraction cannot exceed one")
        transferable = proportional_increments(reactions[:, :, :-1]*(mask[:, :, :-1] & mask[:, :, 1:]), fraction, rng)
        reactions[:, :, :-1] -= transferable
        reactions[:, :, 1:] += transferable
    elif name == "archive_reader_session":
        # One legitimate visitor reacts once to each available post on day 10.
        views[:, :, 9] += mask[:, :, 9]
        reactions[:, :, 9] += mask[:, :, 9]
    else:
        raise ValueError(name)
    assert (views[~mask] == 0).all() and (reactions[~mask] == 0).all()
    return views, reactions, mask, mu, q


def trajectory_stress(panel):
    designs, info = templates(panel)
    fit = features(*simulate(designs, SEED+150))
    calibration = component_ranks(features(*simulate(designs, SEED+151)), fit)
    threshold = cutoff(calibration.max(axis=1))
    individual_thresholds = [cutoff(calibration[:, i]) for i in range(len(COMPONENTS))]
    test = simulate(designs, SEED+152)
    base_ranks = component_ranks(features(*test), fit)
    base = base_ranks.max(axis=1) > threshold
    def evaluate(sample):
        ranks = component_ranks(features(*sample), fit)
        flags = ranks.max(axis=1) > threshold
        return {"joint": rate(flags), "new_among_base_clear": rate(flags[~base]),
                "component_alerts": {name: rate(ranks[:, j] > individual_thresholds[j])
                                     for j, name in enumerate(COMPONENTS)},
                "actual_added_views_fraction": float((sample[0].sum()-test[0].sum())/test[0].sum()),
                "actual_added_reactions_fraction": float((sample[1].sum()-test[1].sum())/test[1].sum())}
    scenarios = {}
    names = ("smooth_joint", "proportional_path", "diffuse_reactions", "shared_reaction_pulses",
             "independent_reaction_pulses", "common_exposure_event")
    for j, name in enumerate(names):
        scenarios[name] = {str(f): evaluate(perturb(test, name, f, SEED+200+j*10+k))
                           for k, f in enumerate((.1, .3, 1.))}
    scenarios["reaction_delay"] = {"0.5": evaluate(perturb(test, "reaction_delay", .5, SEED+301))}
    eligible_delays = test[1][:, :, :-1]*(test[2][:, :, :-1] & test[2][:, :, 1:])
    scenarios["reaction_delay"]["0.5"]["actual_moved_reaction_fraction"] = float(proportional_increments(eligible_delays, .5, np.random.default_rng(SEED+301)).sum()/test[1].sum())
    scenarios["archive_reader_session"] = {"one": evaluate(perturb(test, "archive_reader_session", 1, SEED+302))}
    shared = perturb(test, "common_exposure_event", .3, SEED+999)
    # Equal observables cannot reveal which unobserved provenance label is true.
    same_observables = np.array_equal(features(*shared), features(*tuple(x.copy() for x in shared)))
    return {"templates": info, "fit_worlds": N, "calibration_worlds": N, "test_worlds": N,
            "components": COMPONENTS, "joint_threshold": threshold,
            "individual_thresholds": dict(zip(COMPONENTS, individual_thresholds)),
            "clean_generator": evaluate(test),
            "uncorrected_component_union": rate((base_ranks > np.array(individual_thresholds)).any(axis=1)),
            "scenarios": scenarios, "same_campaign_or_organized_observables_same_scores": same_observables,
            "scope": "known-reference synthetic generator on fixed historical observation masks; not a validated organic model or empirical manipulation recall",
            "calibration_repeats": calibration_diagnostic(designs, fit),
            "dose_caveat": "shared and independent reaction pulses use the same per-post expected dose and eligibility on fixed dates; realized doses still fluctuate"}


def calibration_diagnostic(designs, fit_scores):
    """Post-hoc audit after the initial 6.8% null rate; no primary threshold retuning.

    The tolerance threshold is an order statistic chosen by a binomial tail,
    not by its test results. Its guarantee assumes iid calibration from the
    same generator and scores fixed independently of calibration.
    """
    records = []
    confidence = .95
    order = int(binom.ppf(confidence, N, 1-ALPHA))+1  # one-based order statistic
    for repeat in range(20):
        cal = component_ranks(features(*simulate(designs, SEED+4000+2*repeat)), fit_scores).max(axis=1)
        test = component_ranks(features(*simulate(designs, SEED+4001+2*repeat)), fit_scores).max(axis=1)
        marginal = cutoff(cal)
        tolerance = float(np.sort(cal)[order-1]) if order <= len(cal) else float("inf")
        records.append({"repeat": repeat, "nominal_quantile_rate": float((test > marginal).mean()),
                        "tolerance_rate": float((test > tolerance).mean())})
    return {"design": "post-hoc diagnostic with 20 new independent calibration/test pairs; original result retained",
            "worlds_per_calibration_and_test": N, "tolerance_confidence": confidence,
            "tolerance_order_one_based": order, "records": records,
            "mean_nominal_quantile_rate": float(np.mean([r["nominal_quantile_rate"] for r in records])),
            "mean_tolerance_rate": float(np.mean([r["tolerance_rate"] for r in records]))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint-panel", type=Path, required=True)
    parser.add_argument("--tail-panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"seed": SEED, "nominal_research_alpha": ALPHA,
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "early_masking": early_masking(args.endpoint_panel),
              "history_contamination": contaminated_history(),
              "trajectory_stress": trajectory_stress(args.tail_panel)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"output": str(args.output), "endpoint_counts": result["early_masking"]["counts"],
                      "templates": result["trajectory_stress"]["templates"]["accounts"],
                      "null": result["trajectory_stress"]["clean_generator"]["joint"]}))


if __name__ == "__main__":
    main()
