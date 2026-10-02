"""H48–H51: research diagnostics; no production imports, writes or probabilities.

Numeric modes read frozen inputs; --availability-sql prints a bounded read-only
query. A separate prospective window is a plan, never a completed validation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import uuid

import numpy as np
import scipy
from scipy.optimize import minimize
from scipy.special import digamma, expit, gammaln

import persistent_tail_validation as P

SEED = 20268228
PROTOCOL_SHA = "cee63d71b8f998ba5958d98177bd52f85ddb2bec3053919c504b4b0f2ff4921e"
H52_PROTOCOL_SHA = "ec225a3c58f87bdc04f25983772d7f7f7fc623a3a32c9c83b16a9a9d34a95fa6"
H49_MODEL_SHA = "ab9fe07ddf2831a705606d9ecbbfcd6d82ebfe6a5d514374819a3dd94d26d079"
ORDINARY = ("baseline", "shallow_sessions", "wide_sessions", "high_engagement",
            "audience_growth", "campaign", "contiguous_walk", "regular_reader")
STRESS = ("dense_walk", "scheduled_campaign", "vk_recommendation", "delayed_reactors")
INJECTIONS = tuple(f"{kind}{dose}" for kind in ("persistent_r", "early_r", "preserve_er")
                   for dose in (10, 30, 100)) + ("small_daily10", "small_daily30", "test_only_r100")
FAMILIES = ORDINARY + INJECTIONS + STRESS
MASKS = ("full", "independent", "change_biased")
SCORES = ("joint", "core", "shape")


def rng(*keys):
    return np.random.default_rng(np.random.SeedSequence([SEED, *keys]))


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def dump(value, path):
    Path(path).write_text(json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                                     indent=2, allow_nan=False) + "\n")


def protocol_hash(root):
    text = (root / "research/smart-engagement-2026-09/GENERALIZATION.md").read_text()
    return hashlib.sha256(text.split("## Протокол до расчётов\n", 1)[1]
                          .split("## Результаты\n", 1)[0].encode()).hexdigest()


def provenance(root):
    if protocol_hash(root) != PROTOCOL_SHA:
        raise ValueError("Preregistered protocol has changed")
    return {"seed": SEED, "protocol_sha256": protocol_hash(root),
            "script_sha256": P.sha(__file__),
            "parent_script_sha256": P.sha(Path(P.__file__)),
            "tests_sha256": P.sha(root / "tests/test_tail_generalization.py"),
            "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "scope": "research_only_no_production_changes", "platform": "max",
            "new_real_holdout_completed": False}


def bootstrap_difference(values, key=0):
    a = np.asarray(values, float)
    if not len(a):
        return None
    means = a[rng(990, key).integers(0, len(a), size=(2000, len(a)))].mean(axis=1)
    return {"n": len(a), "mean": float(a.mean()), "ci95": np.quantile(means, [.025, .975]).tolist(),
            "unit": "whole_account_or_independent_world", "refitted": False}


def publication_context(posts, accounts):
    start, end = P.tail.dt("2026-08-31T00:00:00+03:00"), P.tail.dt("2026-09-14T00:00:00+03:00")
    selected = [p for p in posts if start <= p["published"] < end]
    types = sorted({p["post"]["publication_type"] for p in selected})
    grouped = defaultdict(list)
    for p in selected:
        grouped[p["post"]["primary_account_id"]].append(p)
    contexts, support = {}, {}
    for a in accounts:
        all_posts = grouped[a]
        original = [p for p in all_posts if not p["post"]["is_repost"]]
        contexts[a] = np.array([np.log1p(len(original)/14)] +
                              [sum(p["post"]["publication_type"] == t for p in original)/max(1, len(original)) for t in types] +
                              [1-len(original)/len(all_posts) if all_posts else 0])
        support[a] = {"original_posts": len(original), "all_posts": len(all_posts)}
    return contexts, {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
                      "types": types, "accounts": support, "archive_completeness_verified": False}


def context_weights(context, fitting, target):
    if target in fitting:
        raise ValueError("Target must be excluded before constructing the reference")
    x = np.array([context[a] for a in fitting])
    scale = np.maximum(x.std(axis=0), .1)
    distance = np.linalg.norm((x-context[target])/scale, axis=1)
    h = max(.1, float(np.sort(distance)[min(19, len(distance)-1)]))
    weights = np.exp(-.5*(distance/h)**2)
    effective = weights.sum()**2/(weights @ weights)
    return dict(zip(fitting, weights)), {"effective_accounts": float(effective), "bandwidth": h,
                                        "scale": scale, "distances": dict(zip(fitting, distance))}


def balanced_weights(rows, account_weights):
    counts = Counter(r["account"] for r in rows)
    w = np.array([account_weights[r["account"]]/counts[r["account"]] for r in rows])
    return w * len(rows)/w.sum()


def nb_objective(params, x, y, offset, weights):
    beta, k = params[:-1], np.exp(-params[-1])
    eta = offset+x @ beta
    mu = np.exp(np.clip(eta, -25, 25))
    penalty = np.full(len(beta), 10.); penalty[0] = 0
    ll = gammaln(y+k)-gammaln(k)-gammaln(y+1)+k*(np.log(k)-np.log(k+mu))+y*(np.log(mu)-np.log(k+mu))
    loss = -weights @ ll + .5*np.sum(penalty*beta**2)
    score = weights*(mu-y)/(1+mu/k) * ((eta > -25) & (eta < 25))
    db = x.T @ score + penalty*beta
    dk = digamma(y+k)-digamma(k)+np.log(k)+1-np.log(k+mu)-(k+y)/(k+mu)
    return float(loss), np.r_[db, k*(weights @ dk)]


def weighted_model(rows, mode, weights):
    types = sorted({r["type"] for r in rows})
    x, offset = P.raw_design(rows, types, mode)
    center = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x-center)**2, axis=0, weights=weights))
    center[0], scale[0] = 0, 1
    scale = np.maximum(scale, 1e-8)
    x = (x-center)/scale
    y = np.array([r["dr"] for r in rows])
    init = np.zeros(x.shape[1]+1)
    init[0] = np.log((weights @ y+.5)/(weights @ np.exp(offset)+.5))
    fit = minimize(nb_objective, init, args=(x, y, offset, weights), jac=True,
                   method="L-BFGS-B", bounds=[(None, None)]*x.shape[1]+[(-9, 5)],
                   options={"maxiter": 700, "ftol": 1e-10})
    if not fit.success:
        raise RuntimeError(f"Weighted NB did not converge: {fit.message}")
    return dict(mode=mode, types=types, center=center, scale=scale, beta=fit.x[:-1],
                dispersion=float(np.exp(fit.x[-1])), optimizer={"success": True, "iterations": fit.nit},
                accounts=sorted({r["account"] for r in rows}), days=sorted({r["day"] for r in rows}), n=len(rows))


def real_cycle(root):
    data_root = root / "research/smart-engagement-2026-09/local_data"
    posts, clocks, digest = P.tail.load(data_root / "max_tail_panel_2026-09-28.jsonl.gz")
    if digest != P.PANEL_SHA:
        raise ValueError("Frozen panel changed")
    cohort_path = data_root / "max_tail_cohort_2026-09-28.json"
    accounts = [c["id"] for c in json.loads(cohort_path.read_text())]
    context, context_audit = publication_context(posts, accounts)
    report = {"panel_sha256": digest, "cohort_sha256": P.sha(cohort_path), "context": context_audit, "tolerances": {}}
    for stale in (3, 6):
        rows, opp, audit, _ = P.tail.intervals(posts, clocks, stale=stale)
        usable = [r for r in rows if r["actual_start_age"] >= 4 and r["q24"] is not None]
        days = P.observations(rows, opp, accounts)
        first = defaultdict(list)
        for r in usable:
            if r["day"] in P.FIRST:
                first[r["account"]].append(r)
        results, cache = {}, {}
        for target in sorted(accounts):
            selected = [d for d in days[target] if d["day"] in P.SECOND and d["eligible"]]
            if len(selected) < 3:
                results[target] = {"status": "abstain", "reason": "fewer_than_three_observed_days"}
                continue
            test = [r for d in selected for r in d["rows"]]
            fitting, _ = P.partition(accounts, target)
            fitting = [a for a in fitting if first[a]]
            local, support = context_weights(context, fitting, target)
            if support["effective_accounts"] < 20:
                results[target] = {"status": "abstain", "reason": "effective_reference_below_20", "support": support}
                continue
            train = [r for a in fitting for r in first[a]]
            assert target not in fitting and all(r["day"] in P.FIRST for r in train)
            y = np.array([r["dr"] for r in test])
            result = {"status": "eligible", "test_days": len(selected), "test_intervals": len(test),
                      "support": support, "fit_accounts": fitting, "models": {}}
            for mode in P.MODES:
                result["models"][mode] = {}
                for strategy in ("pooled", "balanced", "local"):
                    key = (mode, strategy, tuple(fitting), target if strategy == "local" else None)
                    if key not in cache:
                        weights = (np.ones(len(train)) if strategy == "pooled" else
                                   balanced_weights(train, local if strategy == "local" else dict.fromkeys(fitting, 1.)))
                        cache[key] = weighted_model(train, mode, weights)
                    model = cache[key]
                    mu = P.predict(model, test)
                    result["models"][mode][strategy] = {"mae": float(np.abs(y-mu).mean()),
                        "nll": float(P.nll(y, mu, model["dispersion"]).mean()), "model_digest": P.model_digest(model)}
            results[target] = result
        eligible = [r for r in results.values() if r["status"] == "eligible"]
        summary = {}
        for i, mode in enumerate(P.MODES):
            summary[mode] = {}
            for metric in ("mae", "nll"):
                values = {s: np.array([r["models"][mode][s][metric] for r in eligible]) for s in ("pooled", "balanced", "local")}
                summary[mode][metric] = {"means": {s: float(v.mean()) for s, v in values.items()},
                    "local_minus_balanced": bootstrap_difference(values["local"]-values["balanced"], stale*10+i),
                    "balanced_minus_pooled": bootstrap_difference(values["balanced"]-values["pooled"], stale*10+i)}
            summary[mode]["localization_gate_pass"] = all(summary[mode][m]["local_minus_balanced"]["ci95"][1] < 0 for m in ("mae", "nll"))
        report["tolerances"][str(stale)] = {"eligible_accounts": len(eligible), "accounts": results, "summary": summary,
                                            "interval_audit": audit, "no_new_independent_period": True}
        print(json.dumps({"real_tolerance": stale, "eligible": len(eligible), "summary": summary}), flush=True)
    return report


def alter(data, account, family, random):
    if family == "delayed_reactors":
        family = "small_daily30"
    if family not in ("contiguous_walk", "regular_reader", "dense_walk", "scheduled_campaign"):
        return P.alter(data, account, family, random)
    one = {k: v[account].copy() for k, v in data.items()}
    v, r = one["v"], one["r"]
    if family == "scheduled_campaign":
        q = np.clip((one["early_r"][P.POST_INDEX]+.5)/(one["early_v"][P.POST_INDEX]+1), 0, 1)
        extra = random.poisson(25, size=v.shape)*(np.arange(30)[:, None] % 2 == 0)
        v += extra; r += random.binomial(extra, q)
    else:
        for day in range(30):
            count = 1 if family == "regular_reader" else random.poisson(1 if family == "dense_walk" else .5)
            for _ in range(count):
                depth = min(20, random.geometric(.1 if family == "dense_walk" else .25))
                start = random.integers(0, 21-depth)
                v[day, start:start+depth] += 1
                r[day, start:start+depth] += random.binomial(1, .8, depth)
    return one


def observation_mask(one, uniform, kind):
    if kind == "full":
        return np.ones_like(uniform, bool)
    if kind == "independent":
        return uniform < .6
    if kind == "change_biased":
        return uniform < np.where(one["r"][20:30] > 0, .85, .35)
    raise ValueError(kind)


def covariance(left, right, known):
    if known.sum() < 10:
        return None
    a, b = left[known].astype(float), right[known].astype(float)
    return float(np.mean(a*b)-a.mean()*b.mean())


def features(one, reference, mask, start=20):
    y = one["r"][start:start+10].astype(float)
    mask = np.asarray(mask, bool).copy()
    if mask.shape != y.shape:
        raise ValueError("Mask must describe observed intervals")
    eligible = mask.sum(axis=1) >= 10
    if eligible.sum() < 3:
        return None
    mask[~eligible] = False
    active = y > 0
    adjacent = covariance(active[:, :-1], active[:, 1:], mask[:, :-1] & mask[:, 1:])
    # Same post ages one day: next day's matching position is two slots older.
    temporal = covariance(active[:-1, :-2], active[1:, 2:], mask[:-1, :-2] & mask[1:, 2:])
    if adjacent is None or temporal is None:
        return None
    q = (one["early_r"][P.POST_INDEX]+.5)/(one["early_v"][P.POST_INDEX]+1)
    conditional = (one["v"][start:start+10]+1)*q[start:start+10]*np.exp(-.08*(P.AGES[None, :]-1))*reference["conditional"]
    mus = (np.broadcast_to(reference["structural"], y.shape), conditional)
    core, shape = [], []
    for mu in mus:
        ym, mm, known = y[eligible], mu[eligible], mask[eligible]
        n = known.sum(axis=1)
        total = np.where(known, ym, 0).sum(axis=1)
        expected = np.where(known, mm, 0).sum(axis=1)
        log_volume = np.log((total+.5)/(expected+.5))
        weights = np.where(known, mm, 0)/expected[:, None]
        occupancy = -np.expm1(total[:, None]*np.log1p(-np.minimum(weights, 1-1e-15)))
        breadth = ((known & (ym > 0)).sum(axis=1)-occupancy.sum(axis=1))/n
        residual = np.clip((ym-mm)/np.sqrt(mm+.4*mm**2+1), -5, 5)
        positive = np.where(known, np.maximum(residual, 0), 0)
        agreement = (positive.sum(axis=1)**2-(positive**2).sum(axis=1))/(n*(n-1))
        core.extend(P.block_features(np.column_stack((log_volume, breadth, agreement))))
        excess = np.maximum(total-expected, 0)
        concentration = float(np.sum((excess/excess.sum())**2)) if excess.sum() else 0.
        age = np.broadcast_to(np.log(P.AGES), ym.shape)[known]
        res = residual[known]
        slope = float(np.mean((age-age.mean())*(res-res.mean()))/np.var(age))
        shape.extend((float(log_volume.std()), concentration, slope, adjacent, temporal))
    return np.r_[core, shape]


def train_classifier(x, y):
    center, scale = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-8)
    design = np.column_stack((np.ones(len(x)), (x-center)/scale))
    def fg(beta):
        z = design @ beta
        return (float(np.sum(np.logaddexp(0, z)-y*z)+5*np.sum(beta[1:]**2)),
                design.T @ (expit(z)-y)+np.r_[0., 10*beta[1:]])
    fit = minimize(fg, np.zeros(design.shape[1]), jac=True, method="L-BFGS-B",
                   options={"maxiter": 500, "ftol": 1e-11})
    if not fit.success:
        raise RuntimeError(f"Logistic fit failed: {fit.message}")
    return {"center": center, "scale": scale, "beta": fit.x, "optimizer_iterations": fit.nit,
            "training_rows": len(x), "interpretation": "linear_mechanism_score_not_probability"}


def scores(x, models):
    a = np.minimum(x[:, 0], np.minimum(x[:, 1], np.maximum(x[:, 2], x[:, 3])))
    b = np.minimum(x[:, 4], np.minimum(x[:, 5], np.maximum(x[:, 6], x[:, 7])))
    out = {"joint": np.maximum(a, b)}
    for key, length in (("core", 8), ("shape", 18)):
        m = models[key]
        out[key] = m["beta"][0]+((x[:, :length]-m["center"])/m["scale"]) @ m["beta"][1:]
    return out


def conservative_threshold(values, minimum=200, alpha=.025):
    values = np.asarray(values, float)
    values = values[np.isfinite(values)]
    if len(values) < minimum:
        return None
    k = math.ceil((len(values)+1)*(1-alpha))
    if k > len(values):
        return None
    return float(np.sort(values)[k-1])


def rates(values, threshold):
    valid = np.isfinite(values)
    if threshold is None:
        return {"worlds": len(values), "eligible": int(valid.sum()), "status": "abstain_insufficient_calibration"}
    flags = valid & (values > threshold)
    n, k = int(valid.sum()), int(flags.sum())
    return {"worlds": len(values), "eligible": n, "abstained": len(values)-n, "flags": k,
            "rate_among_eligible": k/n if n else None, "wilson95": P.wilson(k, n)}


def generate_phase(phase, worlds, include_contamination=None):
    kinds = ("full",) if phase == 1 else MASKS
    families = ORDINARY+INJECTIONS if phase == 1 else FAMILIES
    out = {kind: {f: np.full((worlds, 18), np.nan) for f in families} for kind in kinds}
    include_contamination = phase == 3 if include_contamination is None else include_contamination
    contaminated = {f: np.full((worlds, 18), np.nan) for f in families} if include_contamination else None
    checks = {"target_excluded": True, "growth_alias": True, "delayed_alias": True,
              "persistent_doubling_same_test_as_test_only": True}
    additions = {f: Counter() for f in families}
    for world in range(worlds):
        base = P.ordinary_world(rng(phase, world, 1))
        peer = P.clone(base)
        for j, a in enumerate(P.FIT):
            P.install(peer, a, alter(base, a, ORDINARY[j % 6], rng(phase, world, 2, int(a))))
        ref = P.sim_reference(peer)
        if include_contamination:
            changed_peer = P.clone(peer)
            for a in P.FIT[:9]:
                P.install(changed_peer, a, P.alter(peer, a, "early_r100", rng(phase, world, 3, int(a))))
            changed_ref = P.sim_reference(changed_peer)
        uniform = rng(phase, world, 4).random((10, 20))
        changed = {}
        for j, family in enumerate(families):
            if family == "delayed_reactors":
                one = changed["small_daily30"]
            else:
                one = alter(base, 0, family, rng(phase, world, 5, j))
            changed[family] = one
            additions[family].update({"r_before": int(base["r"][0, 20:].sum()), "r_added": int((one["r"][20:]-base["r"][0, 20:]).sum()),
                                      "v_before": int(base["v"][0, 20:].sum()), "v_added": int((one["v"][20:]-base["v"][0, 20:]).sum())})
            for kind in kinds:
                f = features(one, ref, observation_mask(one, uniform, kind))
                if f is not None:
                    out[kind][family][world] = f
            if contaminated is not None:
                contaminated[family][world] = features(one, changed_ref, np.ones((10, 20), bool))
        for k in base:
            checks["growth_alias"] &= np.array_equal(changed["audience_growth"][k], changed["preserve_er100"][k])
        if "delayed_reactors" in changed:
            checks["delayed_alias"] &= all(np.array_equal(changed["small_daily30"][k], changed["delayed_reactors"][k]) for k in base)
        checks["persistent_doubling_same_test_as_test_only"] &= np.array_equal(changed["persistent_r100"]["r"][20:], changed["test_only_r100"]["r"][20:])
        # Alter all target values, including its fit/cal history. Peer estimates must remain identical.
        probe = P.clone(peer)
        for k in probe:
            probe[k][0] += 100000
        probe_ref = P.sim_reference(probe)
        checks["target_excluded"] &= np.array_equal(ref["structural"], probe_ref["structural"]) and ref["conditional"] == probe_ref["conditional"]
        if (world+1) % 100 == 0:
            print(json.dumps({"phase": phase, "worlds_done": world+1, "worlds_total": worlds}), flush=True)
    if not all(checks.values()):
        raise AssertionError(checks)
    return out, contaminated, checks, additions


def simulation_cycle(train_n=400, cal_n=400, test_n=600):
    train, _, train_checks, _ = generate_phase(1, train_n)
    x = np.concatenate([train["full"][f] for f in ORDINARY+INJECTIONS])
    y = np.concatenate([np.full(train_n, float(f in INJECTIONS)) for f in ORDINARY+INJECTIONS])
    if not np.all(np.isfinite(x)):
        raise AssertionError("Complete train must be observable")
    models = {"core": train_classifier(x[:, :8], y), "shape": train_classifier(x, y)}
    cal, _, cal_checks, _ = generate_phase(2, cal_n)
    test, contaminated, test_checks, additions = generate_phase(3, test_n)
    cal_scores = {kind: {f: scores(x, models) for f, x in fs.items()} for kind, fs in cal.items()}
    test_scores = {kind: {f: scores(x, models) for f, x in fs.items()} for kind, fs in test.items()}
    thresholds = {}
    for kind in MASKS:
        thresholds[kind] = {}
        for method in SCORES:
            by_family = {f: conservative_threshold(cal_scores[kind][f][method]) for f in ORDINARY}
            valid = all(v is not None for v in by_family.values())
            thresholds[kind][method] = {"threshold": max(by_family.values()) if valid else None,
                                        "by_family": by_family,
                                        "cal_eligible": {f: int(np.isfinite(cal_scores[kind][f][method]).sum()) for f in ORDINARY}}
    evaluations = {}
    for kind in MASKS:
        evaluations[kind] = {}
        for calibration in ("full", "matched"):
            threshold_kind = "full" if calibration == "full" else kind
            evaluations[kind][calibration] = {f: {method: rates(test_scores[kind][f][method], thresholds[threshold_kind][method]["threshold"])
                                                  for method in SCORES} for f in FAMILIES}
    control = evaluations["full"]["full"]
    per_family_gate = {f: control[f]["shape"]["wilson95"][1] <= .05 for f in ORDINARY}
    comparable = {f: control[f]["shape"]["rate_among_eligible"]-control[f]["core"]["rate_among_eligible"] <= .01+1e-12 for f in ORDINARY}
    core = test_scores["full"]["small_daily30"]["core"] > thresholds["full"]["core"]["threshold"]
    shape = test_scores["full"]["small_daily30"]["shape"] > thresholds["full"]["shape"]["threshold"]
    gain = bootstrap_difference(shape.astype(float)-core.astype(float), 49)
    contamination = {f: {m: rates(v, thresholds["full"][m]["threshold"]) for m, v in scores(a, models).items()} for f, a in contaminated.items()}
    common = np.ones(test_n, bool)
    for method in SCORES:
        common &= test_scores["full"]["baseline"][method] <= thresholds["full"][method]["threshold"]
    new_flags = {f: {m: int(np.sum(common & (test_scores["full"][f][m] > thresholds["full"][m]["threshold"]))) for m in SCORES} for f in INJECTIONS}
    return {"worlds": {"train": train_n, "cal": cal_n, "test": test_n}, "models": models,
            "train_checks": train_checks, "cal_checks": cal_checks, "test_checks": test_checks,
            "thresholds": thresholds, "evaluations": evaluations, "peer_contamination_30pct": contamination,
            "test_doses": additions, "common_baseline_unflagged": int(common.sum()), "new_flags": new_flags,
            "shape_gate": {"ordinary_family_wilson_upper_below_5pct": per_family_gate,
                           "no_family_error_increase_over_1pp": comparable, "small_daily30_gain": gain,
                           "pass": bool(all(per_family_gate.values()) and all(comparable.values()) and gain["mean"] >= .1 and gain["ci95"][0] > 0)},
            "production_ready": False, "classification_of_real_fraud_measured": False}


AVAILABILITY_SQL = """BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SET LOCAL lock_timeout='1s';
WITH recent AS MATERIALIZED (
 SELECT publication_id,observed_at,views_quality,reactions_quality,interval_uncertain
 FROM ingest.publication_poll_receipt
 WHERE observed_at >= now()-interval '7 days'
 ORDER BY observed_at DESC LIMIT 100001
), grouped AS (
 SELECT a.platform,count(*) AS receipts,count(DISTINCT r.publication_id) AS posts,
 count(DISTINCT p.primary_account_id) AS accounts,min(r.observed_at) AS first_read,
 max(r.observed_at) AS last_read,
 count(*) FILTER (WHERE r.observed_at-p.published_at>=interval '4 days') AS age_ge_4d,
 count(*) FILTER (WHERE r.observed_at-p.published_at>=interval '7 days') AS age_ge_7d,
 count(*) FILTER (WHERE r.views_quality='exact' AND r.reactions_quality='exact' AND NOT r.interval_uncertain) AS exact_vr
 FROM recent r JOIN ingest.publication p ON p.id=r.publication_id
 JOIN catalog.platform_account a ON a.id=p.primary_account_id GROUP BY a.platform
)
SELECT jsonb_build_object('query_time',now(),'bounded_to_7_days_and_100001_rows',true,
 'row_cap_reached',(SELECT count(*)>100000 FROM recent),
 'by_platform',(SELECT jsonb_agg(to_jsonb(g) ORDER BY g.platform) FROM grouped g));
COMMIT;
"""


def context_sql(root):
    folder = root / "research/smart-engagement-2026-09/local_data"
    cohort = json.loads((folder / "max_tail_cohort_2026-09-28.json").read_text())
    posts, _, digest = P.tail.load(folder / "max_tail_panel_2026-09-28.jsonl.gz")
    if digest != P.PANEL_SHA:
        raise ValueError("Panel changed")
    # UUID parsing prevents metadata from becoming SQL. No texts are retrieved.
    accounts = ",".join(f"('{uuid.UUID(c['id'])}'::uuid)" for c in cohort)
    ordered = sorted((p["post"]["id"] for p in posts), key=lambda x: hashlib.sha256(x.encode()).digest())[:1000]
    publications = ",".join(f"('{uuid.UUID(i)}'::uuid)" for i in ordered)
    return f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SET LOCAL lock_timeout='1s';
WITH accounts(id) AS (VALUES {accounts}), sample(id) AS (VALUES {publications}),
counts AS (
 SELECT a.id,s.subscriber_count,s.subscriber_quality FROM accounts a
 LEFT JOIN LATERAL (
  SELECT subscriber_count,subscriber_quality FROM ingest.account_metric_snapshot s
  WHERE s.platform_account_id=a.id
    AND s.observed_at>='2026-08-30 21:00:00+00'
    AND s.observed_at<'2026-09-13 21:00:00+00'
    AND s.created_at<'2026-09-13 21:00:00+00'
  ORDER BY s.observed_at DESC,s.correction_sequence DESC LIMIT 1
 ) s ON true
)
SELECT jsonb_build_object('query_time',now(),'scope','frozen_81_max_accounts_and_1000_hash_selected_panel_posts',
 'subscriber_scope','latest available before fit; presence only, not independently verified audience',
 'accounts',(SELECT count(*) FROM counts),
 'subscriber_count_available',(SELECT count(*) FROM counts WHERE subscriber_count IS NOT NULL),
 'subscriber_exact',(SELECT count(*) FROM counts WHERE subscriber_count IS NOT NULL AND subscriber_quality='exact'),
 'sample_posts',(SELECT count(*) FROM sample),
 'content_rows',(SELECT count(*) FROM sample p JOIN analytics.publication_content c ON c.publication_id=p.id),
 'nonempty_texts',(SELECT count(*) FROM sample p JOIN analytics.publication_content c ON c.publication_id=p.id WHERE length(btrim(coalesce(c.archived_text,'')))>0));
COMMIT;
"""


def h52_cycle(root, source):
    protocol = (root / "research/smart-engagement-2026-09/GENERALIZATION.md").read_text()
    digest = hashlib.sha256(protocol.split("## H52: последующая проверка калибровки — протокол\n", 1)[1]
                            .split("## H52: результаты\n", 1)[0].encode()).hexdigest()
    if digest != H52_PROTOCOL_SHA:
        raise ValueError("H52 protocol changed")
    original = json.loads(source.read_text())["simulation"]["models"]
    model_digest = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
    if model_digest != H49_MODEL_SHA:
        raise ValueError("H52 must use frozen H49 coefficients")
    models = {m: {k: np.asarray(v) if k in ("beta", "scale", "center") else v for k, v in a.items()} for m, a in original.items()}
    cal, _, cal_checks, _ = generate_phase(4, 1000)
    test, contaminated, test_checks, additions = generate_phase(5, 1200, include_contamination=True)
    cs = {kind: {f: scores(x, models) for f, x in fs.items()} for kind, fs in cal.items()}
    ts = {kind: {f: scores(x, models) for f, x in fs.items()} for kind, fs in test.items()}
    thresholds, evaluations, gates = {}, {}, {}
    for kind in MASKS:
        thresholds[kind] = {}
        for method in SCORES:
            alpha = .005 if method == "shape" else .025
            by_family = {f: conservative_threshold(cs[kind][f][method], alpha=alpha) for f in ORDINARY}
            valid = all(v is not None for v in by_family.values())
            thresholds[kind][method] = {"threshold": max(by_family.values()) if valid else None,
                                        "by_family": by_family, "alpha": alpha,
                                        "cal_eligible": {f: int(np.isfinite(cs[kind][f][method]).sum()) for f in ORDINARY}}
    for kind in MASKS:
        evaluations[kind] = {}
        for calibration in ("full", "matched"):
            threshold_kind = "full" if calibration == "full" else kind
            evaluations[kind][calibration] = {f: {m: rates(ts[kind][f][m], thresholds[threshold_kind][m]["threshold"]) for m in SCORES} for f in FAMILIES}
        table = evaluations[kind]["matched"]
        if any(thresholds[kind][m]["threshold"] is None for m in SCORES):
            gates[kind] = {"status": "abstain_insufficient_calibration"}
            continue
        error_gate = {f: table[f]["shape"]["wilson95"][1] <= .05 for f in ORDINARY}
        comparable = {f: table[f]["shape"]["rate_among_eligible"]-table[f]["core"]["rate_among_eligible"] <= .01+1e-12 for f in ORDINARY}
        valid = np.isfinite(ts[kind]["small_daily30"]["shape"]) & np.isfinite(ts[kind]["small_daily30"]["core"])
        a = ts[kind]["small_daily30"]["shape"][valid] > thresholds[kind]["shape"]["threshold"]
        b = ts[kind]["small_daily30"]["core"][valid] > thresholds[kind]["core"]["threshold"]
        gain = bootstrap_difference(a.astype(float)-b.astype(float), 52)
        gates[kind] = {"ordinary_family_wilson_upper_below_5pct": error_gate,
                       "no_family_error_increase_over_1pp": comparable, "small_daily30_gain": gain,
                       "pass": bool(all(error_gate.values()) and all(comparable.values()) and gain["mean"] >= .1 and gain["ci95"][0] > 0)}
    contamination = {f: {m: rates(v, thresholds["full"][m]["threshold"]) for m, v in scores(a, models).items()} for f, a in contaminated.items()}
    return {"protocol_sha256": digest, "source_models_sha256": model_digest, "source_report_sha256": P.sha(source),
            "worlds": {"new_cal": 1000, "new_test": 1200}, "cal_checks": cal_checks, "test_checks": test_checks,
            "thresholds": thresholds, "evaluations": evaluations, "gates": gates,
            "peer_contamination_30pct": contamination, "test_doses": additions,
            "production_ready": False, "classification_of_real_fraud_measured": False}


def bundle(root, folder):
    names = ("real", "simulation", "confirmatory", "curves_real", "curves_simulation")
    parts = {name: json.loads((folder / f"{name}.json").read_text()) for name in names}
    parts["part_sha256"] = {name: P.sha(folder / f"{name}.json") for name in names}
    parts["audit"] = {}
    for name in ("availability", "context"):
        value = json.loads((folder / f"{name}.json").read_text())
        # Only explicit research aggregates, never transport configuration/logs.
        parts["audit"][name] = value["result"][0] if value["status"] == "ok" else {"status": value["status"]}
        parts["audit"][name+"_sql_sha256"] = P.sha(folder / f"{name}.sql")
    parts["runtime"] = {name: json.loads((folder / f"{name}.json.runtime.json").read_text()) for name in names
                        if (folder / f"{name}.json.runtime.json").exists()}
    parts["prospective"] = {
        "platform": "max", "cohort": "same frozen 81 accounts", "cohort_sha256": parts["real"]["real"]["cohort_sha256"],
        "start_inclusive": "2026-09-29T00:00:00+03:00", "end_exclusive": "2026-10-06T00:00:00+03:00",
        "earliest_assessment": "2026-10-06T00:00:00+03:00", "completed": False, "automatic_run_scheduled": False,
        "purpose": "future descriptive transfer check, no new production score admitted",
        "reference": "H42 historical fit/cal frozen; target fully excluded; hash-fixed input panel",
        "main_staleness_hours": 3, "sensitivity_staleness_hours": 6,
        "missing_read": "unknown", "new_storage_or_ttl_or_polling": False,
        "caveat": "A future date alone does not repair calibration size or absence of ages 7–14 in receipts"}
    parts["decision"] = {"production_ready": False, "production_changed": False,
                         "confirmed_real_manipulation_labels": 0, "telegram_or_vk_transfer_validated": False}
    return parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--mode", choices=("real", "simulation", "confirmatory", "bundle"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-simulation", type=Path)
    parser.add_argument("--parts-dir", type=Path)
    parser.add_argument("--availability-sql", action="store_true")
    parser.add_argument("--context-sql", action="store_true")
    args = parser.parse_args()
    if args.availability_sql:
        print(AVAILABILITY_SQL)
        return
    if args.context_sql:
        print(context_sql(args.root))
        return
    if not args.mode or not args.output:
        parser.error("--mode and --output required")
    if args.mode == "bundle":
        if not args.parts_dir:
            parser.error("--parts-dir required")
        dump(bundle(args.root, args.parts_dir), args.output)
        print(json.dumps({"output": str(args.output), "sha256": P.sha(args.output)}), flush=True)
        return
    result = {"provenance": provenance(args.root), "mode": args.mode}
    if args.mode == "confirmatory":
        if not args.source_simulation:
            parser.error("--source-simulation required to freeze H49 coefficients")
        result[args.mode] = h52_cycle(args.root, args.source_simulation)
    else:
        result[args.mode] = real_cycle(args.root) if args.mode == "real" else simulation_cycle()
    dump(result, args.output)
    print(json.dumps({"output": str(args.output), "sha256": P.sha(args.output)}), flush=True)


if __name__ == "__main__":
    main()
