#!/usr/bin/env python3
"""Exploratory, observation-aware summary of Telegram neighboring-post events.

Input: temporary CSV from sql/neighbor_study_snapshots.sql. Output: aggregates
only. This is not a causal estimator or a public anomaly threshold.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "publication_id primary_account_id arm published_at publication_type "
    "history_completeness first_observation_age_seconds posting_order "
    "observed_at age_seconds sampling_bucket views_count views_quality "
    "interval_uncertain synthetic correction_sequence collection_run_id"
).split()


def parse_time(value: str) -> datetime:
    normalized = value[:-3] + "+00:00" if value.endswith("+00") else value
    pattern = "%Y-%m-%d %H:%M:%S.%f%z" if "." in normalized else "%Y-%m-%d %H:%M:%S%z"
    return datetime.strptime(normalized, pattern)


def median(values):
    return round(statistics.median(values), 3) if values else None


def summarize(path: Path) -> dict:
    with path.open(newline="") as source:
        source_rows = list(csv.DictReader(source, fieldnames=FIELDS))
    if not source_rows or any(None in row for row in source_rows):
        raise ValueError("Empty CSV or unexpected row width")
    by_post = defaultdict(list)
    metadata = {}
    account_posts = defaultdict(list)
    for row in source_rows:
        publication_id = row["publication_id"]
        if publication_id not in metadata:
            meta = {
                "id": publication_id,
                "account": row["primary_account_id"],
                "arm": row["arm"],
                "published": parse_time(row["published_at"]),
                "order": int(row["posting_order"]),
            }
            metadata[publication_id] = meta
            account_posts[meta["account"]].append(meta)
        if row["observed_at"] and row["synthetic"] == "f":
            by_post[publication_id].append({
                "at": parse_time(row["observed_at"]),
                "age": int(row["age_seconds"]),
                "views": int(row["views_count"]) if row["views_count"] else None,
                "quality": row["views_quality"],
                "uncertain": row["interval_uncertain"] == "t",
                "corrected": int(row["correction_sequence"] or 0) > 0,
            })
    for posts in account_posts.values():
        posts.sort(key=lambda item: (item["published"], item["id"]))
    for points in by_post.values():
        points.sort(key=lambda item: item["at"])

    intervals = []
    excluded = Counter()
    for post_id, meta in metadata.items():
        points = by_post[post_id]
        posts = account_posts[meta["account"]]
        for left, right in zip(points, points[1:]):
            duration = (right["at"] - left["at"]).total_seconds()
            if left["age"] < 86400 or duration < 300 or duration > 7200:
                excluded["age_or_duration"] += 1
                continue
            if left["views"] is None or right["views"] is None:
                excluded["null_views"] += 1
                continue
            if left["quality"] not in {"rounded", "exact"} or right["quality"] not in {"rounded", "exact"}:
                excluded["quality"] += 1
                continue
            if left["uncertain"] or right["uncertain"]:
                excluded["uncertain_interval"] += 1
                continue
            delta = right["views"] - left["views"]
            if delta < 0:
                excluded["negative_net"] += 1
                continue
            events = [item for item in posts
                      if item["order"] > meta["order"]
                      and left["at"] < item["published"] <= right["at"]]
            if len(events) > 1:
                excluded["multiple_publications_inside"] += 1
                continue
            recent_event = any(item["order"] > meta["order"] and
                               left["at"] - timedelta(hours=2) <= item["published"] <= right["at"]
                               for item in posts)
            kind = "event" if events else ("contaminated_quiet" if recent_event else "quiet")
            event = events[0] if events else None
            new_views = None
            if event:
                observed_new = [point for point in by_post[event["id"]]
                                if event["published"] <= point["at"] <= right["at"]
                                and point["views"] is not None]
                if observed_new:
                    new_views = observed_new[-1]["views"]
            intervals.append({
                "post_id": post_id,
                "account": meta["account"],
                "arm": meta["arm"],
                "start": left["at"],
                "duration_hours": duration / 3600,
                "age_days": left["age"] / 86400,
                "start_views": left["views"],
                "delta": delta,
                "rate": delta * 3600 / duration,
                "kind": kind,
                "distance": event["order"] - meta["order"] if event else None,
                "post_event_fraction": (right["at"] - event["published"]).total_seconds() / duration
                    if event else None,
                "new_views_by_old_end": new_views,
                "corrected_end": right["corrected"],
            })

    result = {
        "frame": {
            "accounts": len(account_posts),
            "hash_sample_accounts": sum(posts[0]["arm"] == "hash_sample"
                                        for posts in account_posts.values()),
            "publications": len(metadata),
            "publications_without_points_in_window": sum(not by_post[post_id]
                                                         for post_id in metadata),
            "effective_rows": len(source_rows),
            "eligible_intervals": len(intervals),
            "excluded_segments": dict(excluded),
        },
        "arms": {},
    }
    for arm in ("hash_sample", "case_mipt"):
        subset = [item for item in intervals if item["arm"] == arm]
        counts = Counter(item["kind"] for item in subset)
        event_groups = {}
        for label, test in (
            ("distance_1", lambda x: x["distance"] == 1),
            ("distance_2_3", lambda x: x["distance"] in {2, 3}),
            ("distance_4_6", lambda x: x["distance"] is not None and 4 <= x["distance"] <= 6),
            ("distance_7_plus", lambda x: x["distance"] is not None and x["distance"] >= 7),
        ):
            selected = [x for x in subset if x["kind"] == "event" and test(x)]
            after20 = [x for x in selected if x["post_event_fraction"] >= 0.2]
            with_new_views = [x for x in after20 if x["new_views_by_old_end"] is not None
                              and x["new_views_by_old_end"] > 0]
            above_100 = [x for x in with_new_views if x["new_views_by_old_end"] >= 100]
            above_500 = [x for x in with_new_views if x["new_views_by_old_end"] >= 500]
            event_groups[label] = {
                "intervals": len(selected),
                "intervals_at_least_20pct_after_publication": len(after20),
                "accounts": len({x["account"] for x in selected}),
                "old_posts": len({x["post_id"] for x in selected}),
                "median_delta_rounded_views": median([x["delta"] for x in selected]),
                "median_delta_after_20pct_filter": median([x["delta"] for x in after20]),
                "after_20pct_with_new_post_views": len(with_new_views),
                "median_new_post_views_by_old_end": median(
                    [x["new_views_by_old_end"] for x in with_new_views]),
                "median_old_delta_over_new_views": median(
                    [x["delta"] / x["new_views_by_old_end"] for x in with_new_views]),
                "zero_stored_delta_after_20pct_filter": sum(x["delta"] == 0 for x in after20),
                "new_views_at_least_100": len(above_100),
                "zero_stored_delta_when_new_views_at_least_100": sum(
                    x["delta"] == 0 for x in above_100),
                "new_views_at_least_500": len(above_500),
                "zero_stored_delta_when_new_views_at_least_500": sum(
                    x["delta"] == 0 for x in above_500),
                "median_duration_minutes": median([x["duration_hours"] * 60 for x in selected]),
                "median_post_event_fraction": median([x["post_event_fraction"] for x in selected]),
                "share_delta_at_least_50": round(sum(x["delta"] >= 50 for x in selected) / len(selected), 3)
                    if selected else None,
            }
        paired = []
        day_shift_paired = []
        for event in (x for x in subset if x["kind"] == "event" and x["distance"] <= 6
                      and x["post_event_fraction"] >= 0.2):
            quiet = [x for x in subset if x["kind"] == "quiet" and x["post_id"] == event["post_id"]
                     and abs((x["start"] - event["start"]).total_seconds()) <= 24 * 3600
                     and 0.5 <= x["duration_hours"] / event["duration_hours"] <= 2]
            if quiet:
                control = min(quiet, key=lambda x: (abs((x["start"] - event["start"]).total_seconds()),
                                                    abs(x["duration_hours"] - event["duration_hours"])))
                paired.append({
                    "account": event["account"],
                    "distance": event["distance"],
                    "event_delta": event["delta"],
                    "quiet_delta": control["delta"],
                    "event_rate": event["rate"],
                    "quiet_rate": control["rate"],
                })
            same_clock = [x for x in subset if x["kind"] == "quiet" and x["post_id"] == event["post_id"]
                          and abs(abs((x["start"] - event["start"]).total_seconds()) - 24 * 3600)
                          <= 2 * 3600
                          and 0.5 <= x["duration_hours"] / event["duration_hours"] <= 2]
            if same_clock:
                control = min(same_clock, key=lambda x: (
                    abs(abs((x["start"] - event["start"]).total_seconds()) - 24 * 3600),
                    abs(x["duration_hours"] - event["duration_hours"])))
                day_shift_paired.append({
                    "account": event["account"],
                    "event_delta": event["delta"],
                    "quiet_delta": control["delta"],
                    "event_rate": event["rate"],
                    "quiet_rate": control["rate"],
                })
        by_account = defaultdict(list)
        for pair in paired:
            by_account[pair["account"]].append(pair["event_rate"] - pair["quiet_rate"])
        account_medians = [statistics.median(values) for values in by_account.values()]
        day_shift_by_account = defaultdict(list)
        for pair in day_shift_paired:
            day_shift_by_account[pair["account"]].append(pair["event_rate"] - pair["quiet_rate"])
        day_shift_medians = [statistics.median(values) for values in day_shift_by_account.values()]
        result["arms"][arm] = {
            "accounts": len({x["account"] for x in subset}),
            "interval_kinds": dict(counts),
            "event_distance_groups": event_groups,
            "paired_distance_1_to_6_events_after_20pct_filter": len(paired),
            "paired_accounts": len(by_account),
            "paired_median_event_delta": median([x["event_delta"] for x in paired]),
            "paired_median_quiet_delta": median([x["quiet_delta"] for x in paired]),
            "paired_median_rate_difference_per_hour": median(
                [x["event_rate"] - x["quiet_rate"] for x in paired]),
            "account_median_rate_difference_positive": sum(x > 0 for x in account_medians),
            "account_median_rate_difference_nonpositive": sum(x <= 0 for x in account_medians),
            "account_median_rate_differences_sorted": [round(x, 3) for x in sorted(account_medians)],
            "same_clock_day_shift_pairs": len(day_shift_paired),
            "same_clock_day_shift_accounts": len(day_shift_by_account),
            "same_clock_day_shift_median_event_delta": median(
                [x["event_delta"] for x in day_shift_paired]),
            "same_clock_day_shift_median_quiet_delta": median(
                [x["quiet_delta"] for x in day_shift_paired]),
            "same_clock_day_shift_median_rate_difference_per_hour": median(
                [x["event_rate"] - x["quiet_rate"] for x in day_shift_paired]),
            "same_clock_day_shift_account_positive": sum(x > 0 for x in day_shift_medians),
            "same_clock_day_shift_account_nonpositive": sum(x <= 0 for x in day_shift_medians),
        }
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: neighbor_study_summary.py INPUT_CSV")
    result = summarize(Path(sys.argv[1]))
    destination = ROOT / "evidence" / "neighbor_study_2026-09-26.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
