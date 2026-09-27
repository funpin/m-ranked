#!/usr/bin/env python3
"""Find reviewable Telegram neighbor-growth cases in a temporary read-only CSV.

Input comes from sql/neighbor_study_snapshots.sql. This selects cases for
inspection; a matched timestamp is not evidence of causation or manipulation.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from neighbor_study_summary import FIELDS, parse_time


def candidates(path: Path) -> list[dict]:
    posts: dict[str, dict] = {}
    by_account: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="") as source:
        for row in csv.DictReader(source, fieldnames=FIELDS):
            if None in row:
                raise ValueError("Unexpected CSV width")
            post_id = row["publication_id"]
            if post_id not in posts:
                post = {
                    "id": post_id,
                    "account": row["primary_account_id"],
                    "arm": row["arm"],
                    "published": parse_time(row["published_at"]),
                    "order": int(row["posting_order"]),
                    "points": [],
                }
                posts[post_id] = post
                by_account[post["account"]].append(post)
            if row["observed_at"] and row["synthetic"] == "f" and row["views_count"]:
                posts[post_id]["points"].append({
                    "at": parse_time(row["observed_at"]),
                    "age": int(row["age_seconds"]),
                    "views": int(row["views_count"]),
                    "quality": row["views_quality"],
                    "uncertain": row["interval_uncertain"] == "t",
                    "corrected": int(row["correction_sequence"] or 0) > 0,
                })
    for channel in by_account.values():
        channel.sort(key=lambda post: (post["published"], post["id"]))
    for post in posts.values():
        post["points"].sort(key=lambda point: point["at"])

    grouped: dict[tuple[str, str], dict] = {}
    for channel in by_account.values():
        for old in channel:
            for left, right in zip(old["points"], old["points"][1:]):
                duration = (right["at"] - left["at"]).total_seconds()
                if not (left["age"] >= 86400 and 300 <= duration <= 7200):
                    continue
                if any(point["uncertain"] or point["quality"] not in {"exact", "rounded"}
                       for point in (left, right)):
                    continue
                delta = right["views"] - left["views"]
                if delta < 20:
                    continue
                events = [post for post in channel if post["order"] > old["order"]
                          and left["at"] < post["published"] <= right["at"]]
                if len(events) != 1:
                    continue
                event = events[0]
                distance = event["order"] - old["order"]
                if distance > 4 or (right["at"] - event["published"]).total_seconds() / duration < 0.2:
                    continue
                observed_new = [point["views"] for point in event["points"]
                                if event["published"] <= point["at"] <= right["at"]
                                and not point["uncertain"]
                                and point["quality"] in {"exact", "rounded"}]
                if not observed_new or observed_new[-1] < 100:
                    continue
                key = (old["account"], event["id"])
                case = grouped.setdefault(key, {
                    "account": old["account"], "arm": old["arm"],
                    "new_post_id": event["id"], "new_published_utc": event["published"].isoformat(),
                    "old_intervals": [],
                })
                case["old_intervals"].append({
                    "old_post_id": old["id"], "old_published_utc": old["published"].isoformat(),
                    "distance": distance, "old_age_hours": round(left["age"] / 3600, 1),
                    "from_utc": left["at"].isoformat(), "to_utc": right["at"].isoformat(),
                    "old_views_before": left["views"], "old_views_after": right["views"],
                    "delta_displayed_views": delta, "new_views_by_old_end": observed_new[-1],
                    "quality": right["quality"],
                    "corrected_start": left["corrected"], "corrected_end": right["corrected"],
                })
    result = list(grouped.values())
    for case in result:
        case["old_intervals"].sort(key=lambda row: (-row["delta_displayed_views"], row["distance"]))
        case["old_post_count"] = len({row["old_post_id"] for row in case["old_intervals"]})
        case["max_old_delta"] = max(row["delta_displayed_views"] for row in case["old_intervals"])
    return sorted(result, key=lambda case: (-case["old_post_count"], -case["max_old_delta"]))


def attach_public_identities(cases: list[dict], path: Path) -> list[dict]:
    with path.open(newline="") as source:
        identities = {row[0]: row for row in csv.reader(source) if len(row) == 7}
    selected = []
    for case in cases:
        event = identities.get(case["new_post_id"])
        if not event:
            continue
        named = {**case, "institution": event[3], "new_external_id": event[5],
                 "new_public_url": event[6]}
        named["old_intervals"] = [
            {**row, "old_external_id": identities[row["old_post_id"]][5],
             "old_public_url": identities[row["old_post_id"]][6]}
            for row in case["old_intervals"] if row["old_post_id"] in identities
        ]
        selected.append(named)
    return selected


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: neighbor_case_candidates.py TEMP_SNAPSHOT_CSV [TEMP_IDENTITY_CSV]")
    found = candidates(Path(sys.argv[1]))
    if len(sys.argv) == 3:
        found = attach_public_identities(found, Path(sys.argv[2]))
    print(json.dumps(found, ensure_ascii=False, indent=2))
