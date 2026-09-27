#!/usr/bin/env python3
"""Time-split M1 research baseline on a temporary fixed-age panel CSV.

Fit: Aug 29-Sep 1; calibration: Sep 2-4; later evaluation: Sep 5-11.
This is an observational calibration check, not a fraud classifier or a public
threshold. The periods were selected after exploratory work, so the later
slice is separate from fitting but is not a pristine prospective holdout.
Only platform aggregates are written to the project.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.research_baseline import (
    FixedAgePost, RobustPlatformBaseline, empirical_upper_tail,
)

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "platform account_rank primary_account_id institution_id publication_id "
    "published_at publication_type is_repost history_completeness "
    "age_24h v24 r24 vq24 rq24 uncertain24 "
    "age_14d v14 r14 vq14 rq14 uncertain14"
).split()
CAL_START = datetime(2026, 9, 2, tzinfo=timezone.utc)
TEST_START = datetime(2026, 9, 5, tzinfo=timezone.utc)


def parse_time(raw: str) -> datetime:
    raw = raw.replace(" ", "T")
    if raw.endswith("+00"):
        raw += ":00"
    return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%f%z" if "." in raw
                             else "%Y-%m-%dT%H:%M:%S%z")


def read_panel(path: Path, horizon: str):
    if horizon not in {"24h", "14d"}:
        raise ValueError("horizon must be 24h or 14d")
    age_field = "age_24h" if horizon == "24h" else "age_14d"
    suffix = "24" if horizon == "24h" else "14"
    by_platform = defaultdict(lambda: {"fit": [], "cal": [], "test": []})
    selected = defaultdict(int)
    candidate_by_period = defaultdict(lambda: {"fit": 0, "cal": 0, "test": 0})
    with path.open(newline="") as source:
        for source_row in csv.DictReader(source, fieldnames=FIELDS):
            if None in source_row:
                raise ValueError("unexpected CSV width")
            platform = source_row["platform"]
            selected[platform] += 1
            published = parse_time(source_row["published_at"])
            split = "fit" if published < CAL_START else "cal" if published < TEST_START else "test"
            candidate_by_period[platform][split] += 1
            if not (source_row[age_field] and source_row[f"v{suffix}"]
                    and source_row[f"r{suffix}"] and int(source_row[f"v{suffix}"]) > 0
                    and source_row[f"vq{suffix}"] in {"exact", "rounded"}
                    and source_row[f"rq{suffix}"] in {"exact", "rounded"}
                    and source_row[f"uncertain{suffix}"] == "f"):
                continue
            row = FixedAgePost(
                platform, source_row["primary_account_id"],
                source_row["publication_type"], int(source_row[f"v{suffix}"]),
                int(source_row[f"r{suffix}"]),
            )
            by_platform[platform][split].append(row)
    return by_platform, selected, candidate_by_period


def wilson_upper(successes: int, total: int) -> float | None:
    if total == 0:
        return None
    from math import sqrt
    z = 1.96
    p = successes / total
    denominator = 1 + z*z/total
    return round((p + z*z/(2*total) + z*sqrt(p*(1-p)/total + z*z/(4*total*total))) /
                 denominator, 4)


def summarize(path: Path, horizon: str):
    split_rows, selected, candidates = read_panel(path, horizon)
    output = {"horizon": horizon,
              "split": {"fit_before_utc": CAL_START.isoformat(),
                         "test_from_utc": TEST_START.isoformat()}, "platforms": {}}
    for platform, periods in sorted(split_rows.items()):
        fit, calibration, test = (periods[key] for key in ("fit", "cal", "test"))
        if len(fit) < 20 or len({row.account_id for row in fit}) < 2 or not calibration:
            output["platforms"][platform] = {
                "selected_posts": selected[platform], "fit_posts": len(fit),
                "calibration_posts": len(calibration), "test_posts": len(test),
                "candidate_posts_by_period": candidates[platform],
                "status": "insufficient_data",
            }
            continue
        model = RobustPlatformBaseline.fit(platform, fit)
        calibration_scores = tuple(model.predict(row).combined_score for row in calibration)
        test_predictions = tuple(model.predict(row) for row in test)
        p_values = tuple(empirical_upper_tail(item.combined_score, calibration_scores)
                         for item in test_predictions)
        counts = {str(level): sum(p <= level for p in p_values) for level in (0.1, 0.05, 0.01)}
        strongest = [(row, prediction) for row, prediction, p in
                     zip(test, test_predictions, p_values, strict=True) if p <= 0.01]
        strongest_accounts = defaultdict(int)
        strongest_directions = defaultdict(int)
        for row, prediction in strongest:
            strongest_accounts[row.account_id] += 1
            component = ("views" if abs(prediction.views_residual)
                         >= abs(prediction.reactions_residual) else "reactions_per_view")
            residual = (prediction.views_residual if component == "views"
                        else prediction.reactions_residual)
            strongest_directions[f"{component}_{'high' if residual > 0 else 'low'}"] += 1
        output["platforms"][platform] = {
            "selected_posts": selected[platform],
            "candidate_posts_by_period": candidates[platform],
            "fit_posts": len(fit), "calibration_posts": len(calibration),
            "test_posts": len(test),
            "fit_accounts": len({row.account_id for row in fit}),
            "calibration_accounts": len({row.account_id for row in calibration}),
            "test_accounts": len({row.account_id for row in test}),
            "minimum_attainable_empirical_p": round(1/(len(calibration)+1), 5),
            "combined_tail_test_counts": counts,
            "combined_tail_test_rates": {
                level: round(count/len(test), 4) if test else None
                for level, count in counts.items()
            },
            "strongest_tail_affected_accounts": len(strongest_accounts),
            "strongest_tail_max_flags_in_one_account": max(strongest_accounts.values(), default=0),
            "strongest_tail_dominant_component_direction": dict(strongest_directions),
            # Diagnostic only: posts cluster by account and calendar, so this
            # independent-Bernoulli interval is not a public error bound.
            "combined_95pct_rate_naive_iid_wilson_upper": wilson_upper(
                counts["0.05"], len(test)),
            "positive_views_residual_test_posts": sum(p.views_residual > 0 for p in test_predictions),
            "positive_reaction_rate_residual_test_posts": sum(
                p.reactions_residual > 0 for p in test_predictions
            ),
            "model_scales": {"log_views": round(model.views.scale, 4),
                             "log_reaction_rate": round(model.reactions.scale, 4)},
        }
    return output


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: evaluate_m1_fixed_age.py TEMP_PANEL_CSV 24h|14d")
    result = summarize(Path(sys.argv[1]), sys.argv[2])
    destination = ROOT / "evidence" / f"m1_fixed_age_{sys.argv[2]}_calibration_2026-09-26.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
