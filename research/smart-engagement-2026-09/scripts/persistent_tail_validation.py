"""H42–H47: target-excluded recurring-tail diagnostics, never a fraud classifier.

Only existing frozen inputs are read. Numeric output is deterministic; runtime
measurement belongs outside this file. Run --help for numeric/plot modes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

import numpy as np
import scipy
from scipy.special import gammaln

import analyze_max_tail as tail

SEED = 20267228
PANEL_SHA = "1eadb3143f3ec42e3869ec2bdd315e1e9c176f3353d96feccf61622746c6cf2e"
FIRST = tuple(tail.DAYS[:7])
SECOND = tuple(tail.DAYS[7:])
METHODS = ("conditional_joint", "independent_joint", "independent_volume", "self_joint")
MODES = ("structural", "conditional")
MIN_CAL = 19
ALPHA = .05


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def partition(accounts, target=None):
    """The partition is frozen before removing the target; deletion cannot reshuffle peers."""
    ordered = sorted(accounts, key=lambda a: hashlib.sha256(a.encode()).digest())
    return ([a for a in ordered[::2] if a != target],
            [a for a in ordered[1::2] if a != target])


def rank(score, calibration, *, platform_name="max", alpha=ALPHA):
    if platform_name != "max":
        return {"status": "abstain", "reason": "platform_requires_separate_validation"}
    c = np.asarray(calibration, float)
    if not np.isfinite(score) or not np.all(np.isfinite(c)):
        raise ValueError("Nonfinite scores must not become a silent negative decision")
    if len(c) < MIN_CAL or 1 / (1 + len(c)) > alpha:
        return {"status": "abstain", "reason": "insufficient_calibration_accounts",
                "n_cal": len(c), "minimum_rank": 1 / (1 + len(c)), "rank": None}
    p = (1 + int(np.sum(c >= score))) / (1 + len(c))
    return {"status": "diagnostic_only", "n_cal": len(c), "rank": p,
            "flag": bool(p <= alpha), "minimum_rank": 1 / (1 + len(c))}


def components(y, mu, dispersion=.4):
    """Rows are days, columns are distinct old posts (not independent trials)."""
    y, mu = np.asarray(y, float), np.asarray(mu, float)
    if y.shape != mu.shape or y.ndim != 2 or np.any(y < 0) or np.any(mu <= 0):
        raise ValueError("A profile requires observed nonnegative counts and positive means")
    n = y.shape[1]
    if n < 2:
        raise ValueError("Pair agreement requires at least two posts")
    totals = y.sum(axis=1)
    log_volume = np.log((totals + .5) / (mu.sum(axis=1) + .5))
    weights = mu / mu.sum(axis=1, keepdims=True)
    # T=0 has occupancy 0; the clipping only protects floating-point log(0).
    occupancy = -np.expm1(totals[:, None] * np.log1p(-np.minimum(weights, 1-1e-15)))
    breadth = ((y > 0).sum(axis=1) - occupancy.sum(axis=1)) / n
    positive = np.clip((y - mu) / np.sqrt(mu + dispersion * mu * mu + 1), 0, 5)
    agreement = (positive.sum(axis=1)**2 - (positive**2).sum(axis=1)) / (n*(n-1))
    return np.column_stack((log_volume, breadth, agreement))


def block_features(daily):
    a = np.asarray(daily, float)
    if len(a) < 3:
        return None
    return np.array([a[:, 0].mean()/np.log(2), np.sort(a[:, 0])[-3]/np.log(2),
                     a[:, 1].mean()/.1, a[:, 2].mean()])


def joint(feature):
    v, recurrence, breadth, agreement = feature
    return float(min(v, recurrence, max(breadth, agreement)))


def score_pair(features):
    a, b = features
    return {"conditional_joint": joint(b),
            "independent_joint": max(joint(a), joint(b)),
            "independent_volume": max(min(a[0], a[1]), min(b[0], b[1]))}


def raw_design(rows, types, mode):
    age = np.log([r["age"] for r in rows])
    cols = [np.ones(len(rows)), age, age**2,
            np.log1p([r["new_posts"] for r in rows]),
            np.log1p([r["depth"] for r in rows]),
            np.array([tail.dt(r["day"]).weekday() >= 5 for r in rows], float)]
    if mode == "conditional":
        cols.append(np.log1p([r["v24"] for r in rows]))
    cols.extend(np.array([r["type"] == t for r in rows], float) for t in types[1:])
    x = np.column_stack(cols)
    if mode == "conditional":
        offset = np.log([r["dv"]+r["hours"]/24 for r in rows]) + np.log([r["q24"] for r in rows])
    else:
        offset = np.log([r["hours"]/24 for r in rows])
    return x, offset


def fit_model(rows, mode):
    if not rows:
        raise ValueError("No fitting rows")
    types = sorted({r["type"] for r in rows})
    x, offset = raw_design(rows, types, mode)
    center, scale = x.mean(axis=0), x.std(axis=0)
    center[0], scale[0] = 0, 1
    scale = np.maximum(scale, 1e-8)
    x = (x-center)/scale
    beta, dispersion, optimizer = tail.nbfit(x, np.array([r["dr"] for r in rows]), offset)
    if not optimizer["success"]:
        raise RuntimeError(f"NB fit failed: {optimizer}")
    return dict(mode=mode, types=types, center=center, scale=scale, beta=beta,
                dispersion=dispersion, optimizer=optimizer,
                accounts=sorted({r["account"] for r in rows}),
                days=sorted({r["day"] for r in rows}), n=len(rows))


def predict(model, rows):
    x, offset = raw_design(rows, model["types"], model["mode"])
    return np.exp(np.clip(offset + ((x-model["center"])/model["scale"]) @ model["beta"], -25, 25))


def model_digest(model):
    values = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in model.items()}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def observations(rows, opportunities, accounts):
    grouped = defaultdict(list)
    for r in rows:
        if r["actual_start_age"] >= 4 and r["q24"] is not None:
            grouped[r["account"], r["day"]].append(r)
    possible = Counter()
    for (a, d, band), n in opportunities.items():
        if band in tail.BANDS[2:]:
            possible[a, d] += n
    result = {}
    for a in accounts:
        result[a] = []
        for d in tail.DAYS:
            rs, denominator = grouped[a, d], possible[a, d]
            coverage = len(rs)/denominator if denominator else None
            result[a].append({"day": d, "n": len(rs), "possible": denominator,
                              "coverage": coverage, "eligible": bool(len(rs) >= 5 and coverage >= .5),
                              "rows": rs})
    return result


def profile(days, dates, models):
    selected = [d for d in days if d["day"] in dates and d["eligible"]]
    if len(selected) < 3:
        return {"status": "abstain", "reason": "fewer_than_three_observed_days",
                "days": len(selected), "intervals": sum(d["n"] for d in selected)}
    daily = []
    for d in selected:
        y = np.array([r["dr"] for r in d["rows"]])
        diagnostic = {}
        for m in models:
            mu = predict(m, d["rows"])
            feature = components(y[None, :], mu[None, :], m["dispersion"])[0]
            diagnostic[m["mode"]] = {"expected": float(mu.sum()), "components": feature.tolist()}
        daily.append({k: d[k] for k in ("day", "n", "possible", "coverage")} |
                     {"observed": int(y.sum()), "active": int((y > 0).sum()), "models": diagnostic})
    features = [block_features([d["models"][mode]["components"] for d in daily]) for mode in MODES]
    return {"status": "eligible", "days": len(selected), "intervals": sum(d["n"] for d in selected),
            "daily": daily, "features": {m: f.tolist() for m, f in zip(MODES, features)},
            "scores": score_pair(features)}


def drop_calendar_day(p, day):
    """H46 removes a whole day, with no interpolation or resampling of posts."""
    if p["status"] != "eligible":
        return p
    daily = [d for d in p["daily"] if d["day"] != day]
    if len(daily) < 3:
        return {"status": "abstain", "reason": "fewer_than_three_observed_days", "days": len(daily)}
    features = [block_features([d["models"][mode]["components"] for d in daily]) for mode in MODES]
    return {"status": "eligible", "days": len(daily), "scores": score_pair(features)}


def calendar_sensitivity(p, calibrations):
    results = []
    for fit_day, test_day in zip(FIRST, SECOND):
        test = drop_calendar_day(p, test_day)
        cal = [drop_calendar_day(c, fit_day) for c in calibrations]
        cal = [c["scores"]["independent_joint"] for c in cal if c["status"] == "eligible"]
        decision = (rank(test["scores"]["independent_joint"], cal) if test["status"] == "eligible"
                    else {"status": "abstain", "reason": test["reason"], "n_cal": len(cal)})
        results.append({"omitted_test_day": test_day, "omitted_cal_day": fit_day,
                        "remaining_test_days": test["days"], "decision": decision})
    valid = [r["decision"] for r in results if r["decision"]["status"] == "diagnostic_only"]
    return {"deletions": results, "rankable_deletions": len(valid),
            "flags": sum(d["flag"] for d in valid),
            "rank_range": [min(d["rank"] for d in valid), max(d["rank"] for d in valid)] if valid else None}


def nll(y, mu, a):
    k = 1/a
    return -(gammaln(y+k)-gammaln(k)-gammaln(y+1) +
             k*(np.log(k)-np.log(k+mu)) + y*(np.log(mu)-np.log(k+mu)))


def real_validation(posts, clocks, cohort, stale):
    accounts = [c["id"] for c in cohort]
    fit_accounts, cal_accounts = partition(accounts)
    rows, opp, audit, _ = tail.intervals(posts, clocks, stale=stale)
    usable = [r for r in rows if r["actual_start_age"] >= 4 and r["q24"] is not None]
    daily = observations(rows, opp, accounts)
    fit_by_account = defaultdict(list)
    for r in usable:
        if r["day"] in FIRST:
            fit_by_account[r["account"]].append(r)
    cache, result, errors = {}, {}, {m: [] for m in MODES}
    for target in sorted(accounts):
        fitting, calibrating = partition(accounts, target)
        key = tuple(fitting)
        if key not in cache:
            fitting_rows = [r for a in fitting for r in fit_by_account[a]]
            if len(fitting_rows) < 100 or len({r['account'] for r in fitting_rows}) < 10:
                raise RuntimeError("Insufficient model fitting support")
            cache[key] = [fit_model(fitting_rows, mode) for mode in MODES]
        models = cache[key]
        assert all(target not in m["accounts"] and set(m["days"]) <= set(FIRST) for m in models)
        c = [(a, profile(daily[a], FIRST, models)) for a in calibrating]
        eligible_cal = [(a, p) for a, p in c if p["status"] == "eligible"]
        p = profile(daily[target], SECOND, models)
        prior = profile(daily[target], FIRST, models)
        prior_rank = (rank(prior["scores"]["independent_joint"],
                           [v["scores"]["independent_joint"] for _, v in eligible_cal])
                      if prior["status"] == "eligible" else
                      {"status": "abstain", "reason": prior["reason"]})
        ranks = {}
        if p["status"] == "eligible":
            for method in p["scores"]:
                ranks[method] = rank(p["scores"][method], [v["scores"][method] for _, v in eligible_cal])
            family = rank(p["scores"]["independent_joint"],
                          [v["scores"]["independent_joint"] for _, v in eligible_cal], alpha=.05/len(accounts))
        else:
            family = {"status": "abstain", "reason": p["reason"]}
        test_rows = [r for r in usable if r["account"] == target and r["day"] in SECOND]
        err = {}
        if test_rows:
            y = np.array([r["dr"] for r in test_rows])
            for m in models:
                mu = predict(m, test_rows)
                mae, likelihood = np.abs(y-mu), nll(y, mu, m["dispersion"])
                errors[m["mode"]].append((len(y), float(mae.sum()), float(likelihood.sum())))
                err[m["mode"]] = {"n": len(y), "mae": float(mae.mean()), "mean_nll": float(likelihood.mean())}
        result[target] = {
            "case_name": tail.CASES.get(target),
            "fit_accounts": models[0]["accounts"], "n_fit": models[0]["n"],
            "cal_accounts": [a for a, _ in eligible_cal], "n_cal": len(eligible_cal),
            "reference_digest": [model_digest(m) for m in models],
            "dispersion": {m["mode"]: m["dispersion"] for m in models},
            "coverage": [{k: d[k] for k in ('day', 'n', 'possible', 'coverage', 'eligible')} for d in daily[target]],
            "test": p, "ranks": ranks, "familywise_resolution": family, "prediction_errors": err,
            "first_week_description": {k: v for k, v in prior.items() if k != "daily"} | {"rank": prior_rank},
            "calendar_sensitivity": calendar_sensitivity(p, [v for _, v in c]),
        }
    return {"endpoint_tolerance_hours": stale, "audit": audit, "fit_pool": fit_accounts,
            "cal_pool": cal_accounts, "usable_old_intervals_with_early": len(usable),
            "models_fitted": len(cache)*2, "accounts": result,
            "prediction_errors": {m: {"n": sum(x[0] for x in e),
                                      "mae": sum(x[1] for x in e)/sum(x[0] for x in e),
                                      "mean_nll": sum(x[2] for x in e)/sum(x[0] for x in e)} for m, e in errors.items()},
            "summary": {"eligible_test_accounts": sum(x["test"]["status"] == "eligible" for x in result.values()),
                        "rankable_accounts": sum(x["ranks"].get("independent_joint", {}).get("status") == "diagnostic_only" for x in result.values()),
                        "joint_flags": [a for a, x in result.items() if x["ranks"].get("independent_joint", {}).get("flag")],
                        "familywise_rankable": sum(x["familywise_resolution"]["status"] == "diagnostic_only" for x in result.values())}}


# Simulation constants are assumptions, not parameters inferred from named cases.
AGES = np.repeat(np.arange(4, 14), 2)
POST_INDEX = (np.arange(30)[:, None] - AGES[None, :] + 13)*2 + np.tile([0, 1], 10)
NPOSTS = int(POST_INDEX.max())+1
FIT = np.arange(1, 31)
CAL = np.arange(31, 61)
SCENARIOS = ["baseline", "shallow_sessions", "wide_sessions", "high_engagement",
             "audience_growth", "campaign", "vk_recommendation", "test_only_r100"] + [
             f"{kind}{dose}" for kind in ("persistent_r", "early_r", "preserve_er", "small_daily") for dose in (10, 30, 100)]
ORDINARY = {"baseline", "shallow_sessions", "wide_sessions", "high_engagement", "audience_growth", "campaign", "vk_recommendation"}
SIMULATION_SPEC = {
    "days": 30, "accounts": 61, "fit_peer_accounts": 30, "cal_peer_accounts": 30,
    "days_fit_cal_test": [10, 10, 10], "new_posts_per_day": 2, "old_posts_per_day": 20,
    "age_start": [4, 13], "size_lognormal_sigma": .55, "engagement_lognormal_sigma": .5,
    "post_popularity_lognormal_sigma": .45, "post_reaction_lognormal_sigma": .25,
    "view_base": 18, "view_age_decay": .16, "reaction_base": .045, "reaction_age_decay": .10,
    "daily_log_ar1": .6, "daily_log_stationary_sigma": .30,
    "early_views_mean": "150 * size * post_popularity", "assumed_conditional_decay": .08,
    "shallow_session_rate_per_day": .5, "shallow_depth_geometric_p": .25,
    "wide_session_rate_per_day": .4, "session_reaction_probability": .8,
    "ordinary_high_engagement_factor": 3, "ordinary_audience_growth_factor": 2,
    "campaign_days": [3, 13, 23], "campaign_extra_view_mean": 25,
    "vk_per_day_post_wave_probability": .05, "vk_extra_view_mean": 180,
    "enriched_peer_families": ["baseline", "shallow_sessions", "wide_sessions", "high_engagement", "audience_growth", "campaign"],
    "contaminated_peer_fraction": [0, .1, .3], "peer_contamination": "x2 early and late reactions, all 30 days",
    "measurement": "all simulated old intervals observed; exact integer synthetic counters, no Stars",
}


def ordinary_world(rng):
    size = rng.lognormal(-.55**2/2, .55, size=61)
    q = np.clip(.045*rng.lognormal(-.5**2/2, .5, size=61), .005, .25)
    popularity = rng.lognormal(-.45**2/2, .45, size=(61, NPOSTS))
    interest = rng.lognormal(-.25**2/2, .25, size=(61, NPOSTS))
    early_v = rng.poisson(150*size[:, None]*popularity)
    qpost = np.clip(q[:, None]*interest, .001, .4)
    early_r = rng.binomial(early_v, qpost)
    effect = np.empty((61, 30))
    effect[:, 0] = rng.normal(0, .30, size=61)
    for d in range(1, 30):
        effect[:, d] = .6*effect[:, d-1] + rng.normal(0, .30*np.sqrt(1-.6**2), size=61)
    mean_v = (18*size[:, None, None]*popularity[:, POST_INDEX] *
              np.exp(effect[:, :, None]-.30**2/2) * np.exp(-.16*(AGES[None, None, :]-4)))
    v = rng.poisson(mean_v)
    probability = np.clip(qpost[:, POST_INDEX]*np.exp(-.10*(AGES[None, None, :]-1)), 0, 1)
    r = rng.binomial(v, probability)
    # No latent size, interest, probability or effect is returned to the detector.
    return {"v": v, "r": r, "early_v": early_v, "early_r": early_r}


def clone(data):
    return {k: v.copy() for k, v in data.items()}


def scale_paths(values, early, f, rng):
    """One random phase per post, across early count and all observed increments."""
    added = np.zeros_like(values)
    phase = rng.random(len(early))
    running = early.astype(float).copy()
    previous = np.floor(f*running+phase).astype(np.int64)
    new_early = early + previous
    for d in range(values.shape[0]):
        ids = POST_INDEX[d]
        running[ids] += values[d]
        current = np.floor(f*running[ids]+phase[ids]).astype(np.int64)
        added[d] = current-previous[ids]
        previous[ids] = current
    return values+added, new_early


def alter(data, account, scenario, rng):
    """Copy only the target's arrays; callers decide whether it is a target or peer."""
    v, r = data["v"][account].copy(), data["r"][account].copy()
    ev, er = data["early_v"][account].copy(), data["early_r"][account].copy()
    if scenario == "baseline":
        pass
    elif scenario in ("shallow_sessions", "wide_sessions"):
        wide = scenario == "wide_sessions"
        for d in range(30):
            for _ in range(rng.poisson(.4 if wide else .5)):
                depth = 20 if wide else min(20, rng.geometric(.25))
                chosen = rng.choice(20, depth, replace=False)
                v[d, chosen] += 1
                r[d, chosen] += rng.binomial(1, .8, depth)
    elif scenario in ("campaign", "vk_recommendation"):
        q = np.clip((er[POST_INDEX]+.5)/(ev[POST_INDEX]+1), 0, 1)
        if scenario == "campaign":
            active = np.zeros((30, 20), bool)
            active[[3, 13, 23], :] = True
            extra = rng.poisson(25, size=v.shape)*active
        else:
            extra = rng.poisson(180, size=v.shape)*(rng.random(v.shape) < .05)
        v += extra
        r += rng.binomial(extra, q)
    elif scenario == "test_only_r100":
        r[20:] *= 2
    elif scenario.startswith("small_daily"):
        f = int(scenario.removeprefix("small_daily"))/100
        r += rng.binomial(1, f, size=r.shape)
    else:
        if scenario == "high_engagement":
            kind, f = "early_r", 2
        elif scenario == "audience_growth":
            kind, f = "preserve_er", 1
        else:
            kind = next(s for s in ("persistent_r", "early_r", "preserve_er") if scenario.startswith(s))
            f = int(scenario.removeprefix(kind))/100
        if kind == "preserve_er":
            v, ev = scale_paths(v, ev, f, rng)
        r, changed_er = scale_paths(r, er, f, rng)
        if kind != "persistent_r":
            er = changed_er
        if scenario == "high_engagement":
            # The ordinary alternative must still satisfy this generator's
            # one reaction per new view convention (not a universal MAX law).
            r, er = np.minimum(r, v), np.minimum(er, ev)
    return {"v": v, "r": r, "early_v": ev, "early_r": er}


def install(data, a, changed):
    for k in data:
        data[k][a] = changed[k]


def conditional_offset(data):
    q = (data["early_r"][:, POST_INDEX]+.5)/(data["early_v"][:, POST_INDEX]+1)
    return (data["v"]+1)*q*np.exp(-.08*(AGES[None, None, :]-1))


def sim_reference(data):
    """Peer fitting uses only FIT x days 0:10, never cal or target outcomes."""
    offset = conditional_offset(data)
    y = data["r"]
    # Both slots at an age share an estimated mean; .5/1 prevents zero means.
    sums = y[FIT, :10].reshape(30, 10, 10, 2).sum(axis=(0, 1, 3))
    structural = np.repeat((sums+.5)/(30*10*2+1), 2)
    conditional = (y[FIT, :10].sum()+.5)/(offset[FIT, :10].sum()+.5)
    own = (y[:, :10].reshape(61, 10, 10, 2).sum(axis=(1, 3))+.5)/(10*2+1)
    own_conditional = (y[:, :10].sum(axis=(1, 2))+.5)/(offset[:, :10].sum(axis=(1, 2))+.5)
    return {"structural": structural, "conditional": float(conditional),
            "own_structural": np.repeat(own, 2, axis=1), "own_conditional": own_conditional}


def sim_account_scores(one, reference, start, own_index=None):
    q = (one["early_r"][POST_INDEX]+.5)/(one["early_v"][POST_INDEX]+1)
    offset = (one["v"]+1)*q*np.exp(-.08*(AGES[None, :]-1))
    structural = reference["structural"]
    coefficient = reference["conditional"]
    if own_index is not None:
        structural = reference["own_structural"][own_index]
        coefficient = reference["own_conditional"][own_index]
    y = one["r"][start:start+10]
    features = [block_features(components(y, np.broadcast_to(structural, y.shape))),
                block_features(components(y, offset[start:start+10]*coefficient))]
    return score_pair(features)


def sim_calibration(data, reference):
    c = {m: [] for m in METHODS}
    for a in CAL:
        one = {k: v[a] for k, v in data.items()}
        p = sim_account_scores(one, reference, 10)
        for m in METHODS[:3]:
            c[m].append(p[m])
        c["self_joint"].append(sim_account_scores(one, reference, 10, own_index=a)["independent_joint"])
    return {k: np.asarray(v) for k, v in c.items()}


def target_reference(one, reference):
    """Re-estimate only self's fit after alteration; the independent reference is immutable."""
    own = (one["r"][:10].reshape(10, 10, 2).sum(axis=(0, 2))+.5)/(10*2+1)
    q = (one["early_r"][POST_INDEX]+.5)/(one["early_v"][POST_INDEX]+1)
    offset = (one["v"]+1)*q*np.exp(-.08*(AGES[None, :]-1))
    coeff = (one["r"][:10].sum()+.5)/(offset[:10].sum()+.5)
    return {**reference, "own_structural": np.repeat(own, 2)[None, :],
            "own_conditional": np.array([coeff])}


def decisions(one, reference, calibration):
    scores = sim_account_scores(one, reference, 20)
    own = target_reference(one, reference)
    scores["self_joint"] = sim_account_scores(one, own, 20, own_index=0)["independent_joint"]
    return {m: bool((1+np.sum(calibration[m] >= scores[m]))/(1+len(calibration[m])) <= ALPHA) for m in METHODS}


def inclusive_self_calibration(one, reference, calibration):
    own = target_reference(one, reference)
    target_cal = sim_account_scores(one, own, 10, own_index=0)["independent_joint"]
    return np.r_[calibration["self_joint"][:29], target_cal]


def inclusive_self_decision(one, reference, calibration):
    own = target_reference(one, reference)
    score = sim_account_scores(one, own, 20, own_index=0)["independent_joint"]
    c = inclusive_self_calibration(one, reference, calibration)
    return bool((1+np.sum(c >= score))/(1+len(c)) <= ALPHA)


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k/n
    den = 1+z*z/n
    mid = (p+z*z/(2*n))/den
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0., mid-radius), min(1., mid+radius)]


def simulation(worlds):
    buckets = defaultdict(lambda: {"worlds": 0, "common_unflagged": 0, "flags": Counter(),
                                    "new_flags": Counter(), "r_before": 0, "r_added": 0,
                                    "v_before": 0, "v_added": 0})
    inclusive = defaultdict(lambda: {"n": 0, "common_unflagged": 0, "flags": Counter(), "new_flags": Counter()})
    invariant = {"independent_reference_unchanged_by_target": True,
                 "audience_growth_equals_er_preserving_double": True}
    for w in range(worlds):
        base = ordinary_world(np.random.default_rng(np.random.SeedSequence([SEED, w, 1])))
        changed_targets = {}
        for j, scenario in enumerate(SCENARIOS):
            changed_targets[scenario] = alter(base, 0, scenario, np.random.default_rng(np.random.SeedSequence([SEED, w, 2, j])))
        # x2 is integer exact regardless of the random rounding phase.
        invariant["audience_growth_equals_er_preserving_double"] &= all(
            np.array_equal(changed_targets["audience_growth"][k], changed_targets["preserve_er100"][k]) for k in base)
        probe = clone(base)
        install(probe, 0, changed_targets["preserve_er100"])
        original_ref, probe_ref = sim_reference(base), sim_reference(probe)
        original_cal, probe_cal = sim_calibration(base, original_ref), sim_calibration(probe, probe_ref)
        invariant["independent_reference_unchanged_by_target"] &= bool(
            np.array_equal(original_ref["structural"], probe_ref["structural"]) and
            original_ref["conditional"] == probe_ref["conditional"] and
            all(np.array_equal(original_cal[m], probe_cal[m]) for m in METHODS))
        for enriched in (False, True):
            peers = clone(base)
            if enriched:
                families = SIMULATION_SPEC["enriched_peer_families"]
                for a in range(1, 61):
                    install(peers, a, alter(base, a, families[(a-1) % len(families)],
                                          np.random.default_rng(np.random.SeedSequence([SEED, w, 3, a]))))
            for fraction in (0, .1, .3):
                data = clone(peers)
                selected = [a for a in range(1, 61) if (a-1) % 10 < round(10*fraction)]
                for a in selected:
                    install(data, a, alter(peers, a, "early_r100", np.random.default_rng(np.random.SeedSequence([SEED, w, 4, a]))))
                reference = sim_reference(data)
                calibration = sim_calibration(data, reference)
                baseline = decisions(changed_targets["baseline"], reference, calibration)
                common = not any(baseline.values())
                baseline_inclusive = inclusive_self_decision(changed_targets["baseline"], reference, calibration)
                paired_common = not baseline["independent_joint"] and not baseline_inclusive
                for scenario, one in changed_targets.items():
                    flags = decisions(one, reference, calibration)
                    key = ("enriched" if enriched else "background", fraction, scenario)
                    added_flags = {"independent_joint": flags["independent_joint"],
                                   "self_inclusive_cal": inclusive_self_decision(one, reference, calibration)}
                    h = inclusive[key]
                    h["n"] += 1
                    h["common_unflagged"] += paired_common
                    h["flags"].update(m for m, yes in added_flags.items() if yes)
                    h["new_flags"].update(m for m, yes in added_flags.items() if paired_common and yes)
                    b = buckets[key]
                    b["worlds"] += 1
                    b["common_unflagged"] += common
                    b["flags"].update(m for m in METHODS if flags[m])
                    b["new_flags"].update(m for m in METHODS if common and flags[m])
                    b["r_before"] += int(base["r"][0].sum())
                    b["v_before"] += int(base["v"][0].sum())
                    b["r_added"] += int(one["r"].sum()-base["r"][0].sum())
                    b["v_added"] += int(one["v"].sum()-base["v"][0].sum())
                # A stronger identity check is in tests: change ALL target fields,
                # recompute fit/cal, and compare exact arrays, not a claimed seed.
        if (w+1) % 100 == 0:
            print(json.dumps({"simulation_worlds_completed": w+1}), flush=True)
    report = []
    for (family, fraction, scenario), b in sorted(buckets.items()):
        report.append({"reference_family": family, "contaminated_peer_fraction": fraction,
                       "scenario": scenario, "ordinary_by_construction": scenario in ORDINARY,
                       "n": b["worlds"], "common_unflagged": b["common_unflagged"],
                       "actual_added_r_fraction": b["r_added"]/b["r_before"],
                       "actual_added_v_fraction": b["v_added"]/b["v_before"],
                       "methods": {m: {"flags": b["flags"][m], "fraction": b["flags"][m]/b["worlds"],
                                        "wilson95": wilson(b["flags"][m], b["worlds"]),
                                        "new_flags": b["new_flags"][m],
                                        "new_fraction": b["new_flags"][m]/b["common_unflagged"] if b["common_unflagged"] else None,
                                        "new_wilson95": wilson(b["new_flags"][m], b["common_unflagged"])} for m in METHODS}})
    extra = []
    for (family, fraction, scenario), b in sorted(inclusive.items()):
        extra.append({"reference_family": family, "contaminated_peer_fraction": fraction,
                      "scenario": scenario, "n": b["n"], "common_unflagged": b["common_unflagged"],
                      "methods": {m: {"flags": b["flags"][m], "fraction": b["flags"][m]/b["n"],
                                       "wilson95": wilson(b["flags"][m], b["n"]),
                                       "new_flags": b["new_flags"][m],
                                       "new_fraction": b["new_flags"][m]/b["common_unflagged"] if b["common_unflagged"] else None,
                                       "new_wilson95": wilson(b["new_flags"][m], b["common_unflagged"])}
                                  for m in ("self_inclusive_cal", "independent_joint")}})
    return {"seed": SEED, "specification": SIMULATION_SPEC, "worlds": worlds,
            "scope": "conditional sensitivity and false signals in specified simulations, not real fraud accuracy",
            "invariants": invariant, "results": report,
            "h47_self_inclusive_calibration": {"calibration": "29 fixed peer windows plus target days 10:20; same 30-window count; not an independent guarantee", "results": extra}}


def plot_report(report, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.8))
    fig.subplots_adjust(top=.76, bottom=.26, left=.085, right=.97, wspace=.38)
    data = report["simulation"]["results"]
    chosen = ["persistent_r100", "early_r100", "preserve_er100", "small_daily30"]
    labels = ["R ×2\nвесь период", "R и ранние R ×2", "V/R ×2\nER сохранён", "+0,3 R\nна пост/день"]
    colors = ["#7c8798", "#147d92"]
    for j, method in enumerate(("self_joint", "independent_joint")):
        values = [next(x for x in data if x["reference_family"] == "background" and x["contaminated_peer_fraction"] == 0 and x["scenario"] == s) for s in chosen]
        axes[0].bar(np.arange(4)+(j-.5)*.35, [100*x["methods"][method]["new_fraction"] for x in values], width=.33, color=colors[j], label=["Своя история", "Аккаунт исключён"][j])
    axes[0].set_xticks(np.arange(4), labels)
    axes[0].set_ylabel("Новые сигналы среди общего неотмеченного фона, %")
    axes[0].set_ylim(0, 105)
    primary_n = next(x["common_unflagged"] for x in data if x["reference_family"] == "background" and x["contaminated_peer_fraction"] == 0)
    axes[0].set_title(f"A. Добавки во все 30 дней (n={primary_n})", loc="left", pad=18)
    axes[0].legend(frameon=False, loc="upper left")
    ordinary = ["baseline", "shallow_sessions", "wide_sessions", "high_engagement", "audience_growth", "campaign"]
    names = ["Фон", "Короткие сессии", "Широкие сессии", "Высокий отклик", "Приток аудитории", "Кампания"]
    for j, family in enumerate(("background", "enriched")):
        values = [next(x for x in data if x["reference_family"] == family and x["contaminated_peer_fraction"] == 0 and x["scenario"] == s) for s in ordinary]
        axes[1].barh(np.arange(6)+(j-.5)*.35, [100*x["methods"]["independent_joint"]["fraction"] for x in values], height=.33, color=colors[j], label=["Простой референс", "С обычными альтернативами"][j])
    axes[1].set_yticks(np.arange(6), names)
    axes[1].invert_yaxis()
    axes[1].axvline(5, color="#b45545", linestyle="--", linewidth=1)
    axes[1].set_xlim(0, 105)
    axes[1].set_xlabel("Сигналы на обычных симуляциях, %")
    axes[1].set_title("B. Цена независимого ориентира", loc="left", pad=18)
    axes[1].legend(frameon=False, loc="lower right", bbox_to_anchor=(1, -.38), fontsize=9)
    for ax in axes:
        ax.grid(axis="y" if ax is axes[0] else "x", alpha=.15)
        ax.set_axisbelow(True)
    fig.text(.06, .92, "Повторяющийся хвост: независимый ориентир и его ограничения", fontsize=16, weight="bold")
    fig.text(.06, .86, f"{report['simulation']['worlds']} независимых миров · 30 дней · отдельные fit/cal/test · неизменные правила", fontsize=11, color="#4c5965")
    fig.text(.085, .06, "Симуляции с заданными предпосылками, не точность выявления реальной накрутки.\n"
             "Приток аудитории и организованная добавка при одинаковых агрегатах неразличимы.\n"
             "Реальная панель MAX охватывает 14 дней; Telegram и VK не получают этот порог.\n"
             "+0,3 R на пост/день здесь даёт +122% реакций за месяц: малая порция — большой итог.", fontsize=10, color="#4c5965", linespacing=1.6)
    fig.savefig(output, dpi=165, facecolor="#fafbfc")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path)
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worlds", type=int, default=600)
    parser.add_argument("--plot-input", type=Path)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    if args.plot_input:
        plot_report(json.loads(args.plot_input.read_text()), args.figure)
        return
    if not all((args.panel, args.cohort, args.output)):
        parser.error("--panel, --cohort and --output are required for numeric mode")
    if args.worlds < 1:
        parser.error("--worlds must be positive")
    posts, clocks, panel_sha = tail.load(args.panel)
    if panel_sha != PANEL_SHA:
        raise ValueError("Frozen panel changed: a new protocol is required")
    cohort = json.loads(args.cohort.read_text())
    report = {"version": "persistent_tail_research_v1", "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "inputs": {"panel_uncompressed_sha256": panel_sha, "cohort_sha256": sha(args.cohort),
                         "script_sha256": sha(__file__), "endpoint_script_sha256": sha(tail.__file__)},
              "primary_method": "independent_joint", "real_panel_days": 14,
              "reference_calendar": {"fit": FIRST, "cal": FIRST, "test": SECOND},
              "limitations": ["Real peers have unknown origin, not organic labels", "Archive was previously explored; no new blind future validation",
                              "Change-dependent endpoint availability can bias observed days", "Shared calendar shocks violate naive account exchangeability",
                              "Individual empirical ranks do not justify a familywise or fraud-probability claim",
                              "Missing audience size and semantic content limit structural reference comparability"],
              "platform_admission": {"max": "research_only", "telegram": "abstain: no exact V/R or rounding step/Stars separation in this archive", "vk": "separate regime and calibration required; simulated late-wave counterexample only"}}
    document = (Path(__file__).parents[1]/"MAX_TAIL.md").read_text()
    begin = document.index("\n## 10. Продолжение: протокол H42")
    followup = document.index("\n### Дополнительная диагностика H46", begin)
    inclusive_start = document.index("\n### Дополнительная проверка H47", followup)
    end = document.find("\n## 11.", inclusive_start)
    if end < 0:
        end = len(document)
    protocol_hash = hashlib.sha256(document[begin:followup].encode()).hexdigest()
    followup_hash = hashlib.sha256(document[followup:inclusive_start].encode()).hexdigest()
    inclusive_hash = hashlib.sha256(document[inclusive_start:end].encode()).hexdigest()
    assert protocol_hash == "5ea5b527c20572ff5d6ceeafa66024d6da0296f613452a24911d6f5d343108a1"
    assert followup_hash == "3b9276d18c2c2b83d86d51aed4297803ebafbb5e29ff768d38d090b64b8f8189"
    assert inclusive_hash == "32fae9c7035c75714255f2c4faec3e10fc26c9347a41ec0ea8dea6689bc233f3"
    report["provenance"] = {"initial_protocol_sha256": protocol_hash, "h46_protocol_sha256": followup_hash,
                            "starting_branch": "feat/smart-analizes", "starting_commit": "fa83f41046d554ce24d92f33e4d8af4023381a20",
                            "origin_main_at_start": "8de04625e7f4998df84db2e075a56c9bf83ad7fd",
                            "verified_running_application_commit": "e9dfc83c1158b859e12247bb66a343a7ea57781c",
                            "research_writes_only": True, "production_data_extracted": False,
                            "numeric_test_source_sha256": sha(Path(__file__).parents[3]/"tests/test_persistent_tail_research.py"),
                            "h46_timing": "added after primary results; calendar deletion and descriptive two-week profiles, no rule replacement",
                            "h47_protocol_sha256": inclusive_hash,
                            "h47_timing": "added after H43/H46; literal inclusion of target fit and cal; original comparisons preserved"}
    for stale in (3, 6):
        report[f"real_{stale}h"] = real_validation(posts, clocks, cohort, stale)
        print(json.dumps({f"real_{stale}h": report[f"real_{stale}h"]["summary"]}), flush=True)
    report["simulation"] = simulation(args.worlds)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    print(json.dumps({"output_bytes": args.output.stat().st_size, "worlds": args.worlds}))


if __name__ == "__main__":
    main()
