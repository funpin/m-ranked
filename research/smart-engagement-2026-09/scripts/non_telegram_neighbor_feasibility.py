#!/usr/bin/env python3
"""Anonymous platform aggregates for a bounded VK/MAX/RuTube event pilot."""

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

FIELDS = (
    "platform publication_id primary_account_id published_at posting_order "
    "observed_at age_seconds views_count views_quality interval_uncertain synthetic"
).split()


def time(value):
    if value.endswith("+00"):
        value += ":00"
    pattern = "%Y-%m-%d %H:%M:%S.%f%z" if "." in value else "%Y-%m-%d %H:%M:%S%z"
    return datetime.strptime(value, pattern)


def med(values):
    return round(statistics.median(values), 3) if values else None


def main(path):
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source, fieldnames=FIELDS))
    if not rows or any(None in row for row in rows):
        raise ValueError("Unexpected input width or empty source")
    platforms = defaultdict(list)
    for row in rows:
        platforms[row["platform"]].append(row)
    output = {}
    for platform, data in sorted(platforms.items()):
        posts = {}
        points = defaultdict(list)
        by_account = defaultdict(list)
        for row in data:
            post_id = row["publication_id"]
            if post_id not in posts:
                meta = {
                    "id": post_id,
                    "account": row["primary_account_id"],
                    "published": time(row["published_at"]),
                    "order": int(row["posting_order"]),
                }
                posts[post_id] = meta
                by_account[meta["account"]].append(meta)
            if row["observed_at"] and row["synthetic"] == "f":
                points[post_id].append({
                    "at": time(row["observed_at"]),
                    "age": int(row["age_seconds"]),
                    "views": int(row["views_count"]) if row["views_count"] else None,
                    "quality": row["views_quality"],
                    "uncertain": row["interval_uncertain"] == "t",
                })
        for series in points.values():
            series.sort(key=lambda item: item["at"])
        intervals = []
        excluded = Counter()
        long_event_windows = []
        for post_id, meta in posts.items():
            for left, right in zip(points[post_id], points[post_id][1:]):
                duration = (right["at"] - left["at"]).total_seconds()
                if platform == "rutube" and left["age"] >= 86400 and 7200 < duration <= 43200:
                    later_long = [item for item in by_account[meta["account"]]
                                  if item["order"] > meta["order"]
                                  and left["at"] < item["published"] <= right["at"]]
                    if (len(later_long) == 1 and left["views"] is not None
                            and right["views"] is not None
                            and left["quality"] in {"exact", "rounded"}
                            and right["quality"] in {"exact", "rounded"}
                            and not left["uncertain"] and not right["uncertain"]):
                        long_event_windows.append({"account": meta["account"],
                                                   "hours": duration / 3600})
                if left["age"] < 86400 or not 300 <= duration <= 7200:
                    excluded["age_or_duration"] += 1
                    continue
                if left["views"] is None or right["views"] is None:
                    excluded["missing_views"] += 1
                    continue
                if (left["quality"] not in {"exact", "rounded"}
                        or right["quality"] not in {"exact", "rounded"}
                        or left["uncertain"] or right["uncertain"]):
                    excluded["quality_or_uncertain"] += 1
                    continue
                delta = right["views"] - left["views"]
                if delta < 0:
                    excluded["negative_net"] += 1
                    continue
                later = [item for item in by_account[meta["account"]]
                         if item["order"] > meta["order"]]
                events = [item for item in later
                          if left["at"] < item["published"] <= right["at"]]
                if len(events) > 1:
                    excluded["multiple_events"] += 1
                    continue
                recent = any(left["at"] - timedelta(hours=2)
                             <= item["published"] <= right["at"] for item in later)
                kind = "event" if events else ("contaminated" if recent else "quiet")
                fraction_after = ((right["at"] - events[0]["published"]).total_seconds() / duration
                                  if events else None)
                intervals.append({
                    "account": meta["account"],
                    "post": post_id,
                    "start": left["at"],
                    "hours": duration / 3600,
                    "delta": delta,
                    "rate": delta * 3600 / duration,
                    "kind": kind,
                    "distance": events[0]["order"] - meta["order"] if events else None,
                    "fraction_after": fraction_after,
                })
        event = [x for x in intervals if x["kind"] == "event"]
        filtered = [x for x in event if x["distance"] <= 6 and x["fraction_after"] >= 0.2]
        quiet = [x for x in intervals if x["kind"] == "quiet"]
        pairs = []
        for x in filtered:
            matches = [y for y in quiet if y["post"] == x["post"]
                       and abs((y["start"] - x["start"]).total_seconds()) <= 86400
                       and 0.5 <= y["hours"] / x["hours"] <= 2]
            if matches:
                y = min(matches, key=lambda y: abs((y["start"] - x["start"]).total_seconds()))
                pairs.append((x, y))
        account_pairs = defaultdict(list)
        for x, y in pairs:
            account_pairs[x["account"]].append(x["rate"] - y["rate"])
        output[platform] = {
            "accounts": len(by_account),
            "publications": len(posts),
            "publications_without_points": sum(not points[post_id] for post_id in posts),
            "effective_rows": len(data),
            "eligible_intervals": len(intervals),
            "excluded_segments": dict(excluded),
            "event_intervals": len(event),
            "event_accounts": len({x["account"] for x in event}),
            "event_distance_1_to_6_after_20pct": len(filtered),
            "quiet_intervals": len(quiet),
            "matched_event_quiet_pairs": len(pairs),
            "matched_accounts": len(account_pairs),
            "median_event_delta_matched": med([x["delta"] for x, _ in pairs]),
            "median_quiet_delta_matched": med([y["delta"] for _, y in pairs]),
            "median_pair_rate_difference_per_hour": med([x["rate"]-y["rate"] for x, y in pairs]),
            "account_median_difference_positive": sum(statistics.median(v) > 0 for v in account_pairs.values()),
            "account_median_difference_nonpositive": sum(statistics.median(v) <= 0 for v in account_pairs.values()),
            "rutube_event_windows_2_to_12_hours": len(long_event_windows) if platform == "rutube" else None,
            "rutube_event_window_accounts_2_to_12_hours": len({x["account"] for x in long_event_windows})
                if platform == "rutube" else None,
        }
    destination = Path(__file__).resolve().parents[1] / "evidence" / "non_telegram_neighbor_feasibility_2026-09-26.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: non_telegram_neighbor_feasibility.py TEMP_CSV")
    main(Path(sys.argv[1]))
