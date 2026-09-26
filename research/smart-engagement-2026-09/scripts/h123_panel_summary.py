#!/usr/bin/env python3
"""Exploratory H1-H3 fixed-age, two-week account diagnostics.

Input is the temporary, headerless result of sql/h123_fixed_age_panel.sql.
Output is aggregate JSON only, with no account or publication identities.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "platform account_rank primary_account_id institution_id publication_id "
    "published_at publication_type is_repost history_completeness "
    "age_24h v24 r24 vq24 rq24 uncertain24 "
    "age_14d v14 r14 vq14 rq14 uncertain14"
).split()
CUTOFF = datetime(2026, 9, 5, tzinfo=timezone.utc)


def med(values):
    return round(statistics.median(values), 4) if values else None


def mean(values):
    return round(statistics.mean(values), 4) if values else None


def ranks(values):
    ordered = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index in ordered[start:end]:
            result[index] = average_rank
        start = end
    return result


def corr(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    numer = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    denom = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return round(numer / denom, 4) if denom else None


def summarize(path: Path) -> dict:
    by_platform = defaultdict(list)
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle, fieldnames=FIELDS):
            if None in row:
                raise ValueError("Unexpected CSV width")
            published_text = row["published_at"].replace(" ", "T")
            if published_text.endswith("+00"):
                published_text += ":00"
            time_pattern = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in published_text else "%Y-%m-%dT%H:%M:%S%z"
            published = datetime.strptime(published_text, time_pattern)
            week = "A" if published < CUTOFF else "B"
            late = (
                row["age_14d"] and row["v14"] and row["r14"]
                and row["vq14"] in {"exact", "rounded"}
                and row["rq14"] in {"exact", "rounded"}
                and row["uncertain14"] == "f"
                and int(row["v14"]) > 0
            )
            early = (
                row["age_24h"] and row["v24"] and row["r24"]
                and row["vq24"] in {"exact", "rounded"}
                and row["rq24"] in {"exact", "rounded"}
                and row["uncertain24"] == "f"
                and int(row["v24"]) > 0
            )
            by_platform[row["platform"]].append({
                "account": row["primary_account_id"],
                "week": week,
                "format": row["publication_type"],
                "early": bool(early),
                "late": bool(late),
                "v": int(row["v14"]) if late else None,
                "r": int(row["r14"]) if late else None,
            })
    out = {"frame": {}, "platforms": {}}
    for platform, rows in sorted(by_platform.items()):
        usable = [row for row in rows if row["late"]]
        view_bins = {}
        for label, lo, hi in (("1_49", 1, 50), ("50_199", 50, 200),
                              ("200_999", 200, 1000), ("1000_plus", 1000, float("inf"))):
            bin_rows = [row for row in usable if lo <= row["v"] < hi]
            view_bins[label] = {
                "posts": len(bin_rows),
                "zero_reactions": sum(row["r"] == 0 for row in bin_rows),
                "accounts_with_zero_reactions": len({row["account"] for row in bin_rows if row["r"] == 0}),
            }
        by_account = defaultdict(lambda: {"A": [], "B": []})
        for row in usable:
            by_account[row["account"]][row["week"]].append(row)
        eligible = {account: weeks for account, weeks in by_account.items()
                    if min(len(weeks["A"]), len(weeks["B"])) >= 3}
        modal_format = {}
        for account, weeks in by_account.items():
            counts = Counter(x["format"] for x in weeks["A"] + weeks["B"])
            if not counts:
                continue
            mode = sorted(counts, key=lambda key: (-counts[key], key))[0]
            a = [x for x in weeks["A"] if x["format"] == mode]
            b = [x for x in weeks["B"] if x["format"] == mode]
            if min(len(a), len(b)) >= 3:
                modal_format[account] = {"A": a, "B": b}
        positive_support = {account: weeks for account, weeks in eligible.items()
                            if min(sum(x["r"] > 0 for x in weeks["A"]),
                                   sum(x["r"] > 0 for x in weeks["B"])) >= 3}
        high_pairs = []
        dispersion_pairs = []
        prediction = []
        for account, weeks in eligible.items():
            train, test = weeks["A"], weeks["B"]
            ratio_train = [math.log1p(x["r"]) - math.log1p(x["v"]) for x in train]
            ratio_test = [math.log1p(x["r"]) - math.log1p(x["v"]) for x in test]
            high_pairs.append((statistics.median(ratio_train), statistics.median(ratio_test)))
            if min(len(train), len(test)) < 4:
                continue
            dispersion_pairs.append((statistics.stdev(ratio_train), statistics.stdev(ratio_test)))
            const = statistics.median(math.log1p(x["r"]) for x in train)
            prop_offset = statistics.median(ratio_train)
            const_errors = [abs(math.log1p(x["r"]) - const) for x in test]
            prop_errors = [abs(math.log1p(x["r"]) - max(0, math.log1p(x["v"]) + prop_offset))
                           for x in test]
            prediction.append({
                "const_mae": statistics.mean(const_errors),
                "proportional_mae": statistics.mean(prop_errors),
                "posts_test": len(test),
            })
        high_corr = corr(ranks([x[0] for x in high_pairs]),
                         ranks([x[1] for x in high_pairs])) if high_pairs else None
        modal_pairs = []
        modal_predict = []
        for weeks in modal_format.values():
            a, b = weeks["A"], weeks["B"]
            ra = [math.log1p(x["r"]) - math.log1p(x["v"]) for x in a]
            rb = [math.log1p(x["r"]) - math.log1p(x["v"]) for x in b]
            modal_pairs.append((statistics.median(ra), statistics.median(rb)))
            const = statistics.median(math.log1p(x["r"]) for x in a)
            offset = statistics.median(ra)
            modal_predict.append((
                statistics.mean(abs(math.log1p(x["r"]) - const) for x in b),
                statistics.mean(abs(math.log1p(x["r"]) - max(0, math.log1p(x["v"]) + offset))
                                for x in b),
            ))
        modal_corr = corr(ranks([x[0] for x in modal_pairs]),
                          ranks([x[1] for x in modal_pairs])) if modal_pairs else None
        low_dispersion = []
        rest_dispersion = []
        if len(dispersion_pairs) >= 4:
            cutoff = sorted(x[0] for x in dispersion_pairs)[max(0, math.ceil(len(dispersion_pairs)/4)-1)]
            low_dispersion = [y for x, y in dispersion_pairs if x <= cutoff]
            rest_dispersion = [y for x, y in dispersion_pairs if x > cutoff]
        # Per-account cross-week comparisons avoid treating many posts from one
        # account as independent experiments.
        out["platforms"][platform] = {
            "accounts_selected": len({row["account"] for row in rows}),
            "posts_selected": len(rows),
            "early_24h_usable_posts": sum(row["early"] for row in rows),
            "late_14d_usable_posts": len(usable),
            "late_14d_median_views": med([row["v"] for row in usable]),
            "late_14d_median_reactions": med([row["r"] for row in usable]),
            "late_14d_zero_reaction_posts": sum(row["r"] == 0 for row in usable),
            "late_14d_accounts_with_zero_reactions": len({row["account"] for row in usable if row["r"] == 0}),
            "late_14d_zero_reactions_by_view_bin": view_bins,
            "late_14d_median_r_over_v": med([row["r"] / row["v"] for row in usable]),
            "accounts_with_at_least_3_posts_each_week": len(eligible),
            "accounts_with_at_least_3_positive_reaction_posts_each_week": len(positive_support),
            "h1_spearman_week_a_vs_b_account_median_log_ratio": high_corr,
            "modal_format_accounts_with_at_least_3_each_week": len(modal_format),
            "h1_modal_format_spearman_week_a_vs_b": modal_corr,
            "h1_week_a_account_median_log_ratio_range": [
                round(min(x[0] for x in high_pairs), 4),
                round(max(x[0] for x in high_pairs), 4)] if high_pairs else None,
            "h2_accounts_with_at_least_4_posts_each_week": len(dispersion_pairs),
            "h2_week_a_median_within_account_sd_log_ratio": med([x[0] for x in dispersion_pairs]),
            "h2_week_b_median_within_account_sd_log_ratio": med([x[1] for x in dispersion_pairs]),
            "h2_lowest_quartile_a_count": len(low_dispersion),
            "h2_lowest_quartile_a_median_sd_in_b": med(low_dispersion),
            "h2_other_accounts_median_sd_in_b": med(rest_dispersion),
            "h3_accounts_tested": len(prediction),
            "h3_week_b_posts_tested": sum(x["posts_test"] for x in prediction),
            "h3_constant_better_accounts": sum(x["const_mae"] < x["proportional_mae"] for x in prediction),
            "h3_proportional_better_accounts": sum(x["const_mae"] > x["proportional_mae"] for x in prediction),
            "h3_median_constant_log_mae": med([x["const_mae"] for x in prediction]),
            "h3_median_proportional_log_mae": med([x["proportional_mae"] for x in prediction]),
            "h3_median_account_mae_diff_proportional_minus_constant": med([
                x["proportional_mae"] - x["const_mae"] for x in prediction]),
            "h3_modal_format_constant_better_accounts": sum(a < b for a, b in modal_predict),
            "h3_modal_format_proportional_better_accounts": sum(a > b for a, b in modal_predict),
        }
        positive_predictions = []
        for weeks in positive_support.values():
            train, test = weeks["A"], weeks["B"]
            const = statistics.median(math.log1p(x["r"]) for x in train)
            offset = statistics.median(math.log1p(x["r"]) - math.log1p(x["v"]) for x in train)
            positive_predictions.append((
                statistics.mean(abs(math.log1p(x["r"]) - const) for x in test),
                statistics.mean(abs(math.log1p(x["r"]) - max(0, math.log1p(x["v"]) + offset))
                                for x in test),
            ))
        out["platforms"][platform]["h3_positive_support_accounts_tested"] = len(positive_predictions)
        out["platforms"][platform]["h3_positive_support_constant_better_accounts"] = sum(
            a < b for a, b in positive_predictions)
        out["platforms"][platform]["h3_positive_support_proportional_better_accounts"] = sum(
            a > b for a, b in positive_predictions)
    out["frame"] = {
        "selected_accounts": sum(x["accounts_selected"] for x in out["platforms"].values()),
        "selected_posts": sum(x["posts_selected"] for x in out["platforms"].values()),
        "usable_14d_posts": sum(x["late_14d_usable_posts"] for x in out["platforms"].values()),
        "usable_24h_posts": sum(x["early_24h_usable_posts"] for x in out["platforms"].values()),
    }
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: h123_panel_summary.py TEMP_FIXED_AGE_CSV")
    result = summarize(Path(sys.argv[1]))
    output = ROOT / "evidence" / "h123_fixed_age_summary_2026-09-26.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
