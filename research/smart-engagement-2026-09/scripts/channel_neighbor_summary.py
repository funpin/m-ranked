#!/usr/bin/env python3
"""Aggregate the bounded candidate_channel_snapshots.sql CSV without raw export."""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "publication_id primary_account_id published_at first_observation_age_seconds "
    "history_completeness observed_at age_seconds sampling_bucket views_count "
    "reactions_count views_quality reactions_quality synthetic correction_sequence"
).split()
CANDIDATES = {
    "5124e3e9-0af2-5e9d-8e47-a12219d014fa",
    "918ec5a0-0d52-51e9-83d8-aa48f745317a",
}


def near_horizon(points: list[dict[str, str]], days: int, max_lag_hours: int):
    target = days * 86400
    earlier = [r for r in points if int(r["age_seconds"]) <= target]
    if not earlier:
        return None
    latest = earlier[-1]
    return latest if target - int(latest["age_seconds"]) <= max_lag_hours * 3600 else None


def main(path: Path) -> None:
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source, fieldnames=FIELDS))
    if not rows or any(None in row for row in rows):
        raise ValueError("Unexpected CSV width or empty source")
    by_post: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_post[row["publication_id"]].append(row)
    accounts: dict[str, list[dict]] = defaultdict(list)
    large_steps: dict[str, list[dict]] = defaultdict(list)
    for publication_id, raw in by_post.items():
        usable = sorted(
            (r for r in raw if r["observed_at"] and r["synthetic"] == "f"),
            key=lambda r: int(r["age_seconds"]),
        )
        for before, after in zip(usable, usable[1:]):
            if int(before["age_seconds"]) < 3 * 86400:
                continue
            if not before["reactions_count"] or not after["reactions_count"]:
                continue
            change_r = int(after["reactions_count"]) - int(before["reactions_count"])
            if change_r < 50:
                continue
            change_v = None
            if before["views_count"] and after["views_count"]:
                change_v = int(after["views_count"]) - int(before["views_count"])
            duration_hours = (
                int(after["age_seconds"]) - int(before["age_seconds"])
            ) / 3600
            large_steps[raw[0]["primary_account_id"]].append({
                "publication_id": publication_id,
                "end": after["observed_at"],
                "reactions": change_r,
                "views": change_v,
                "interval_hours": duration_hours,
                "corrected_end": int(after["correction_sequence"] or 0) > 0,
            })
        initial_age = int(raw[0]["first_observation_age_seconds"] or -1)
        day3 = near_horizon(usable, 3, 12)
        day14 = near_horizon(usable, 14, 24)
        change = None
        if initial_age >= 0 and initial_age <= 86400 and day3 and day14:
            if day3["reactions_count"] and day14["reactions_count"]:
                change = int(day14["reactions_count"]) - int(day3["reactions_count"])
        accounts[raw[0]["primary_account_id"]].append({
            "id": publication_id,
            "late_reaction_change": change,
            "first_under_24h": initial_age >= 0 and initial_age <= 86400,
            "has_day3": day3 is not None,
            "has_day14": day14 is not None,
        })
    if len(by_post) != 66 or len(accounts) != 2:
        raise ValueError(f"Expected 66 posts from two accounts; got {len(by_post)}, {len(accounts)}")
    result = []
    for account_id, posts in sorted(accounts.items()):
        candidate = next((p for p in posts if p["id"] in CANDIDATES), None)
        if candidate is None:
            raise ValueError(f"Missing candidate in {account_id}")
        eligible = sorted(p["late_reaction_change"] for p in posts
                          if p["late_reaction_change"] is not None)
        value = candidate["late_reaction_change"]
        by_day: dict[str, list[dict]] = defaultdict(list)
        for step in large_steps[account_id]:
            by_day[step["end"][:10]].append(step)
        day_summaries = []
        for day, steps in sorted(by_day.items()):
            end_counts = Counter(s["end"] for s in steps)
            view_changes = [s["views"] for s in steps if s["views"] is not None]
            day_summaries.append({
                "end_date_utc": day,
                "steps_with_delta_reactions_at_least_50": len(steps),
                "distinct_posts": len({s["publication_id"] for s in steps}),
                "largest_shared_exact_observed_at": max(end_counts.values()),
                "delta_reactions_range": [min(s["reactions"] for s in steps),
                                          max(s["reactions"] for s in steps)],
                "delta_views_range": [min(view_changes), max(view_changes)]
                    if view_changes else None,
                "median_stored_interval_hours": round(statistics.median(
                    s["interval_hours"] for s in steps), 2),
                "corrected_end_steps": sum(s["corrected_end"] for s in steps),
            })
        result.append({
            "candidate_id": candidate["id"],
            "account_id": account_id,
            "week_posts": len(posts),
            "first_under_24h": sum(p["first_under_24h"] for p in posts),
            "both_horizons_usable": len(eligible),
            "late_reaction_changes_sorted": eligible,
            "median_change": statistics.median(eligible) if eligible else None,
            "candidate_change": value,
            "candidate_rank_from_top": (1 + sum(x > value for x in eligible))
                if value is not None else None,
            "ties_at_candidate": sum(x == value for x in eligible) if value is not None else None,
            "large_late_steps_by_calendar_day": day_summaries,
        })
    output = ROOT / "annotation" / "channel_neighbor_summary.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: channel_neighbor_summary.py INPUT_CSV")
    main(Path(sys.argv[1]))
