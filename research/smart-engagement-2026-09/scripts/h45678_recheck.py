#!/usr/bin/env python3
"""Summarize age/calendar structure of two bounded Telegram case channels.

Input: headerless CSV from sql/candidate_channel_snapshots.sql. Output has no
account or publication identifiers and is intentionally descriptive only.
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = (
    "publication_id primary_account_id published_at first_observation_age_seconds "
    "history_completeness observed_at age_seconds sampling_bucket views_count "
    "reactions_count views_quality reactions_quality synthetic correction_sequence"
).split()


def main(path):
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source, fieldnames=FIELDS))
    if not rows or any(None in row for row in rows):
        raise ValueError("Unexpected input width or empty data")
    by_post = defaultdict(list)
    for row in rows:
        if row["observed_at"] and row["synthetic"] == "f":
            by_post[row["publication_id"]].append(row)
    steps = []
    for points in by_post.values():
        points.sort(key=lambda row: int(row["age_seconds"]))
        for before, after in zip(points, points[1:]):
            if int(before["age_seconds"]) < 3 * 86400:
                continue
            if not before["reactions_count"] or not after["reactions_count"]:
                continue
            delta_r = int(after["reactions_count"]) - int(before["reactions_count"])
            if delta_r < 50:
                continue
            delta_v = None
            if before["views_count"] and after["views_count"]:
                delta_v = int(after["views_count"]) - int(before["views_count"])
            steps.append({
                "account": after["primary_account_id"],
                "post": after["publication_id"],
                "day": after["observed_at"][:10],
                "end": after["observed_at"],
                "age_days": int(after["age_seconds"]) / 86400,
                "duration_hours": (int(after["age_seconds"]) - int(before["age_seconds"])) / 3600,
                "delta_r": delta_r,
                "delta_v": delta_v,
                "vq_before": before["views_quality"],
                "vq_after": after["views_quality"],
                "rq_before": before["reactions_quality"],
                "rq_after": after["reactions_quality"],
                "corrected": int(after["correction_sequence"] or 0) > 0,
            })
    by_episode = defaultdict(list)
    for step in steps:
        by_episode[(step["account"], step["day"])].append(step)
    episodes = []
    for (_, day), group in sorted(by_episode.items(), key=lambda item: (item[0][1], item[0][0])):
        ages = [step["age_days"] for step in group]
        episodes.append({
            "day_utc": day,
            "steps": len(group),
            "distinct_posts": len({step["post"] for step in group}),
            "age_days_min": round(min(ages), 2),
            "age_days_median": round(statistics.median(ages), 2),
            "age_days_max": round(max(ages), 2),
            "age_days_span": round(max(ages) - min(ages), 2),
            "largest_same_observed_at_batch": max(Counter(step["end"] for step in group).values()),
            "median_interval_hours": round(statistics.median(step["duration_hours"] for step in group), 2),
        })
    out = {
        "bounded_post_count": len(by_post),
        "large_step_count": len(steps),
        "episodes": episodes,
        "all_four_endpoint_metric_qualities_rounded": sum(
            all(step[key] == "rounded" for key in ("vq_before", "vq_after", "rq_before", "rq_after"))
            for step in steps
        ),
        "delta_views_zero": sum(step["delta_v"] == 0 for step in steps),
        "delta_views_missing": sum(step["delta_v"] is None for step in steps),
        "corrected_end_count": sum(step["corrected"] for step in steps),
        "interval_over_six_hours": sum(step["duration_hours"] > 6 for step in steps),
    }
    destination = Path(__file__).resolve().parents[1] / "evidence" / "h45678_bounded_summary_2026-09-26.json"
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: h45678_recheck.py TEMP_CSV")
    main(Path(sys.argv[1]))
