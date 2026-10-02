"""H53: age-aligned post-curve similarity, descriptive MAX diagnostics only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

import tail_generalization as G
P = G.P
PROTOCOL_SHA = "7db5505cc656aed866c26dcbdc4813fd04f6bae9342c61506146458cd0d51baa"


def curve_statistics(counts, hours):
    """Batch x post x age; excluded zero/low-count profiles are not copied curves."""
    counts = np.asarray(counts, float)
    if counts.ndim == 2:
        counts = counts[None]
    active = counts.sum(axis=2) >= 3
    n = active.sum(axis=1)
    rates = counts / (np.asarray(hours)[None] / 24)
    totals = rates.sum(axis=2)
    mean = np.sum(np.where(active, totals, 0), axis=1)/np.maximum(n, 1)
    variance = np.sum(np.where(active, (totals-mean[:, None])**2, 0), axis=1)/np.maximum(n, 1)
    cv = np.sqrt(variance)/np.maximum(mean, 1e-100)
    normalized = rates/np.maximum(totals[:, :, None], 1e-100)
    ordered = np.sort(np.where(active[:, :, None], normalized, np.inf), axis=1)
    index = np.arange(counts.shape[1])[None, :]
    terms = np.where(index[:, :, None] < n[:, None, None], ordered, 0)
    pair_sum = np.sum(terms * (2*index-n[:, None]+1)[:, :, None], axis=(1, 2))
    distance = pair_sum/np.maximum(n*(n-1), 1)
    values = np.column_stack((cv, distance))
    values[n < 6] = np.nan
    return values, n


def assess(counts, hours, means, seed, draws=500):
    observed, active = curve_statistics(counts, hours)
    result = {"complete_posts": len(counts), "active_posts": int(active[0]),
              "statistics": {"level_cv": None, "shape_l1_distance": None}, "models": {}}
    if not np.all(np.isfinite(observed)):
        return result | {"status": "abstain", "reason": "fewer_than_six_complete_active_curves"}
    result["statistics"] = dict(zip(("level_cv", "shape_l1_distance"), observed[0].tolist()))
    totals = counts.sum(axis=0).astype(int)
    for j, (mode, mu) in enumerate(means.items()):
        random = G.rng(53, seed, j)
        weights = mu/mu.sum(axis=0, keepdims=True)
        simulated = np.stack([random.multinomial(int(total), weights[:, age], size=draws)
                              for age, total in enumerate(totals)], axis=2)
        values, _ = curve_statistics(simulated, hours)
        valid = np.all(np.isfinite(values), axis=1)
        support = int(valid.sum())
        if support < 200:
            result["models"][mode] = {"status": "abstain", "null_eligible": support}
            continue
        ranks = (1+np.sum(values[valid] <= observed, axis=0))/(1+support)
        result["models"][mode] = {"status": "diagnostic_only", "null_eligible": support,
            "level_rank": float(ranks[0]), "shape_rank": float(ranks[1]),
            "level_flag": bool(ranks[0] <= .05/4), "shape_flag": bool(ranks[1] <= .05/4),
            "null_median": np.median(values[valid], axis=0).tolist()}
    valid_models = [v for v in result["models"].values() if v["status"] == "diagnostic_only"]
    result["status"] = "diagnostic_only" if len(valid_models) == 2 else "abstain"
    result["level_flag"] = any(v["level_flag"] for v in valid_models) if len(valid_models) == 2 else None
    result["shape_flag"] = any(v["shape_flag"] for v in valid_models) if len(valid_models) == 2 else None
    result["either_flag"] = bool(result["level_flag"] or result["shape_flag"]) if len(valid_models) == 2 else None
    return result


def profiles(rows, ages):
    by_post = defaultdict(dict)
    for r in rows:
        age = int(np.floor(r["actual_start_age"]))
        if age not in ages:
            continue
        existing = by_post[r["id"]].get(age)
        if existing is None or (r["actual_start_age"], r["day"]) < (existing["actual_start_age"], existing["day"]):
            by_post[r["id"]][age] = r
    complete = {p: [a[k] for k in ages] for p, a in by_post.items() if all(k in a for k in ages)}
    return complete, len(by_post)


def distribution(values):
    x = np.asarray(values, float)
    if not len(x):
        return {"n": 0}
    return {"n": len(x), "mean": float(x.mean()), "cv": float(x.std()/x.mean()) if x.mean() else None,
            "p10": float(np.quantile(x, .1)), "median": float(np.median(x)), "p90": float(np.quantile(x, .9)),
            "zero": int(np.sum(x == 0))}


def fixed_horizons(posts, tolerance):
    """Exploratory level/curve displays requested by user; no hypothesis labels."""
    by_account = defaultdict(list)
    cutoff = P.tail.dt("2026-09-28T00:00:00+03:00")
    for p in posts:
        a = p["post"]["primary_account_id"]
        if p["post"]["is_repost"]:
            continue
        samples = [s for s in [p["early24"]]+(p["daily"] or []) if P.tail.good(s)]
        selected = []
        for age in range(1, 8):
            choices = [s for s in samples if abs(s["age_seconds"]/3600-age*24) <= tolerance]
            point = min(choices, key=lambda s: (abs(s["age_seconds"]/3600-age*24), s["observed_at"])) if choices else None
            selected.append(None if point is None else {"r": point["r"], "v": point["v"], "actual_age": point["age_seconds"]/86400})
        if any(x is not None for x in selected):
            by_account[a].append({"post": p["post"]["id"], "type": p["post"]["publication_type"],
                "published_at": p["published"].isoformat(), "mature_days": (cutoff-p["published"]).total_seconds()/86400,
                "points": selected})
    result = {}
    for a, ps in by_account.items():
        totals = {}
        for age in (1, 3, 5, 7):
            selected = [p for p in ps if p["points"][age-1] is not None and p["mature_days"] >= age]
            totals[str(age)] = {"r": distribution([p["points"][age-1]["r"] for p in selected]),
                                "v": distribution([p["points"][age-1]["v"] for p in selected]),
                                "by_type": {t: {m: distribution([p["points"][age-1][m] for p in selected if p["type"] == t]) for m in ("r", "v")}
                                            for t in sorted({p["type"] for p in selected})}}
        paired = [p for p in ps if p["mature_days"] >= 7 and p["points"][0] is not None and p["points"][6] is not None]
        negative_pairs = sum(any(p["points"][6][m] < p["points"][0][m] for m in ("r", "v")) for p in paired)
        paired = [p for p in paired if all(p["points"][6][m] >= p["points"][0][m] for m in ("r", "v"))]
        proportions = {m: distribution([p["points"][0][m]/p["points"][6][m] for p in paired if p["points"][6][m] > 0]) for m in ("r", "v")}
        paired_levels = {str(age): {m: distribution([p["points"][age-1][m] for p in paired]) for m in ("r", "v")} for age in (1, 7)}
        increments = {m: distribution([p["points"][6][m]-p["points"][0][m] for p in paired]) for m in ("r", "v")}
        result[a] = {"horizons": totals, "paired_1_to_7": {"posts": len(paired), "negative_pairs_excluded": negative_pairs,
                        "first_day_fraction": proportions, "levels": paired_levels, "increments": increments},
                     "curves": ps if a in P.tail.CASES else None}
    return result


def real_cycle(root):
    folder = root / "research/smart-engagement-2026-09/local_data"
    posts, clocks, sha = P.tail.load(folder / "max_tail_panel_2026-09-28.jsonl.gz")
    assert sha == P.PANEL_SHA
    accounts = [c["id"] for c in json.loads((folder / "max_tail_cohort_2026-09-28.json").read_text())]
    result = {"panel_sha256": sha, "whole_real_period": list(P.tail.DAYS), "tolerances": {}}
    for stale in (3, 6):
        rows, _, _, _ = P.tail.intervals(posts, clocks, stale=stale)
        rows = [r for r in rows if r["q24"] is not None]
        grouped = defaultdict(list)
        for r in rows:
            grouped[r["account"]].append(r)
        windows = {}
        for label, ages in (("1_to_7", tuple(range(1, 8))), ("4_to_7", tuple(range(4, 8)))):
            windows[label], cache = {}, {}
            for target in sorted(accounts):
                complete, observed_posts = profiles(grouped[target], ages)
                count = len(complete)
                summary = {"name": P.tail.CASES.get(target), "posts_with_any_eligible_interval": observed_posts,
                           "complete_posts": count, "coverage": count/observed_posts if observed_posts else None}
                if count < 6:
                    windows[label][target] = summary | {"status": "abstain", "reason": "fewer_than_six_complete_curves"}
                    continue
                ids = sorted(complete)
                flat = [r for p in ids for r in complete[p]]
                y = np.array([r["dr"] for r in flat]).reshape(count, len(ages))
                h = np.array([r["hours"] for r in flat]).reshape(y.shape)
                fitting, _ = P.partition(accounts, target)
                key = tuple(fitting)
                if key not in cache:
                    train = [r for a in fitting for r in grouped[a] if r["day"] in P.FIRST and r["actual_start_age"] >= ages[0]]
                    cache[key] = [P.fit_model(train, mode) for mode in P.MODES]
                models = cache[key]
                assert all(target not in m["accounts"] for m in models)
                means = {m["mode"]: P.predict(m, flat).reshape(y.shape) for m in models}
                seed = int(hashlib.sha256(f"{target}/{stale}/{label}".encode()).hexdigest()[:8], 16)
                assessed = assess(y, h, means, seed)
                windows[label][target] = summary | assessed | {"models_sha256": {m["mode"]: P.model_digest(m) for m in models},
                    "profiles": [{"id": p, "r": y[i].tolist(), "hours": h[i].tolist(), "type": complete[p][0]["type"]}
                                 for i, p in enumerate(ids)] if target in P.tail.CASES else None}
        result["tolerances"][str(stale)] = {"windows": windows, "fixed_age_descriptive": fixed_horizons(posts, stale)}
        print(json.dumps({"real_tolerance": stale, "support": {k: Counter(v["status"] for v in x.values()) for k, x in windows.items()}}), flush=True)
    return result


def sim_profiles(one, reference, ages=(4, 5, 6, 7)):
    q = (one["early_r"][P.POST_INDEX]+.5)/(one["early_v"][P.POST_INDEX]+1)
    mu_cond = (one["v"]+1)*q*np.exp(-.08*(P.AGES[None, :]-1))*reference["conditional"]
    found = defaultdict(dict)
    for day in range(20, 30):
        for slot, age in enumerate(P.AGES):
            if age in ages:
                found[int(P.POST_INDEX[day, slot])][int(age)] = (day, slot)
    complete = [a for _, a in sorted(found.items()) if all(age in a for age in ages)]
    y = np.array([[one["r"][a[age]] for age in ages] for a in complete])
    means = {"structural": np.array([[reference["structural"][a[age][1]] for age in ages] for a in complete]),
             "conditional": np.array([[mu_cond[a[age]] for age in ages] for a in complete])}
    return y, np.full(y.shape, 24.), means


def sim_cycle(worlds=400):
    families = ("baseline", "shallow_sessions", "wide_sessions", "high_engagement", "campaign", "regular_reader",
                "flat_tail", "decay_tail", "scheduled_readers", "scheduled_artificial")
    buckets = {f: Counter() for f in families}
    invariants = {"target_excluded": True, "scheduled_alias_same_decisions": True}
    for w in range(worlds):
        base = P.ordinary_world(G.rng(6, w, 1))
        peer = P.clone(base)
        for j, a in enumerate(P.FIT):
            P.install(peer, a, G.alter(base, a, G.ORDINARY[j % 6], G.rng(6, w, 2, int(a))))
        ref = P.sim_reference(peer)
        previous = None
        for j, family in enumerate(families):
            if family in ("flat_tail", "decay_tail", "scheduled_readers", "scheduled_artificial"):
                one = {k: v[0].copy() for k, v in base.items()}
                added = np.array([({4: 3, 5: 2, 6: 1, 7: 1}.get(int(age), 0) if family == "decay_tail" else int(4 <= age <= 7)) for age in P.AGES])
                one["r"] += added[None]
                if family.startswith("scheduled_"):
                    one["v"] += added[None]
            else:
                one = G.alter(base, 0, family, G.rng(6, w, 3, j))
            y, h, means = sim_profiles(one, ref)
            # Alias scenarios use identical draws, so Monte Carlo cannot fake a difference.
            assessment = assess(y, h, means, 10000*w+(8 if family.startswith("scheduled_") else j))
            buckets[family]["worlds"] += 1
            if assessment["status"] == "diagnostic_only":
                buckets[family]["eligible"] += 1
                for feature in ("level", "shape", "either"):
                    buckets[family][feature+"_flags"] += int(assessment[feature+"_flag"])
            if family == "scheduled_readers":
                previous = assessment
            if family == "scheduled_artificial":
                invariants["scheduled_alias_same_decisions"] &= previous == assessment
        for k in peer:
            peer[k][0] += 100000
        check = P.sim_reference(peer)
        invariants["target_excluded"] &= np.array_equal(ref["structural"], check["structural"]) and ref["conditional"] == check["conditional"]
        if (w+1) % 100 == 0:
            print(json.dumps({"H53_worlds_done": w+1, "total": worlds}), flush=True)
    assert all(invariants.values())
    for f, counts in buckets.items():
        counts["rates"] = {k: {"rate": counts[k+"_flags"]/counts["eligible"] if counts["eligible"] else None,
                               "wilson95": P.wilson(counts[k+"_flags"], counts["eligible"])} for k in ("level", "shape", "either")}
    return {"families": buckets, "invariants": invariants, "production_ready": False}


def plot_cases(source, output):
    import matplotlib.pyplot as plt
    data = json.loads(source.read_text())
    if "curves_real" in data:
        data = data["curves_real"]
    panel = data["real"]["tolerances"]["6"]
    names = list(P.tail.CASES.items())[:4]
    fig, axes = plt.subplots(4, 3, figsize=(15, 12), sharex=True, layout="constrained")
    colors = ("#325d91", "#23866b", "#b47724", "#a54b62")
    for row, ((account, name), color) in enumerate(zip(names, colors)):
        desc = panel["fixed_age_descriptive"][account]
        curves = [p for p in desc["curves"] if p["mature_days"] >= 7 and p["points"][0] is not None and p["points"][6] is not None
                  and all(p["points"][6][m] >= p["points"][0][m] for m in ("r", "v"))]
        xs = np.arange(1, 8)
        arrays = {m: np.array([[np.nan if s is None else s[m] for s in p["points"]] for p in curves], float) for m in ("r", "v")}
        plotted = (arrays["r"], arrays["r"]/arrays["r"][:, 6, None], arrays["v"])
        for col, values in enumerate(plotted):
            ax = axes[row, col]
            for line in values:
                ax.plot(xs, line, color=color, alpha=.23, linewidth=.8, marker=".", markersize=3)
            # No line through age-specific medians: changing intermediate
            # coverage would create an artificial decrease of cumulative counts.
            ax.set_xticks(xs); ax.grid(alpha=.18)
            ax.spines[["top", "right"]].set_visible(False)
            if col == 1:
                ax.set_ylim(0, 1.05)
            if row == 0:
                ax.set_title(("Реакции, накопленный счётчик", "Доля реакций от значения на 7-е сутки", "Просмотры, накопленный счётчик")[col], fontsize=11)
            if row == 3:
                ax.set_xlabel("Возраст публикации, сутки")
        levels = desc["paired_1_to_7"]["levels"]["7"]
        axes[row, 0].set_ylabel(f"{name}\n{len(curves)} одних и тех же постов", fontsize=10)
        axes[row, 0].text(.97, .04, f"CV R₇ = {levels['r']['cv']:.2f}", transform=axes[row, 0].transAxes, ha="right", fontsize=10,
                          bbox={"facecolor": "white", "alpha": .8, "edgecolor": "none"})
        axes[row, 2].text(.97, .04, f"CV V₇ = {levels['v']['cv']:.2f}", transform=axes[row, 2].transAxes, ha="right", fontsize=10,
                          bbox={"facecolor": "white", "alpha": .8, "edgecolor": "none"})
    fig.suptitle("MAX: сходство постов по уровню и форме — реальные замеры\n"
                 "Панель 14–27 сентября 2026 • одинаковые посты на 1-е и 7-е сутки • диагностический допуск ±6 ч", fontsize=15)
    fig.supxlabel("Линии — отдельные посты; точки — реальные замеры. Пропуски разрывают линии.\n"
                  "CV — относительный разброс; меньше означает более близкие числа. Оси уровней различаются между вузами.\n"
                  "Отбор по наличию обоих замеров ограничивает выводы; сходство не определяет происхождение активности.", fontsize=10)
    fig.savefig(output, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    ap.add_argument("--mode", choices=("real", "simulation", "plot"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source", type=Path)
    args = ap.parse_args()
    if args.mode == "plot":
        if args.source is None:
            ap.error("--source required for plot")
        plot_cases(args.source, args.output)
        return
    protocol = (args.root / "research/smart-engagement-2026-09/GENERALIZATION.md").read_text()
    digest = hashlib.sha256(protocol.split("## H53: похожие кривые разных постов — протокол\n", 1)[1].split("## H53: результаты\n", 1)[0].encode()).hexdigest()
    assert digest == PROTOCOL_SHA
    out = {"protocol_sha256": digest, "source_sha256": P.sha(__file__), "tests_sha256": P.sha(args.root / "tests/test_post_curve_similarity.py"),
           "parent_source_sha256": P.sha(G.__file__), "mode": args.mode, "platform": "max", "origin_not_identified": True}
    out[args.mode] = real_cycle(args.root) if args.mode == "real" else sim_cycle()
    G.dump(out, args.output)
    print(json.dumps({"output": str(args.output), "sha256": P.sha(args.output)}), flush=True)


if __name__ == "__main__":
    main()
