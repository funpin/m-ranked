#!/usr/bin/env python3
"""Summarize a bounded CSV returned by sql/pilot_snapshots.sql.

This is an audit utility, not an anomaly detector. It writes no production data.
Run: python3 scripts/pilot_features.py /private/tmp/tg_pilot_snapshots.csv
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Point:
    age: int
    views: int | None
    reactions: int | None
    comments: int | None
    shares: int | None
    corrected: bool


def number(value: str) -> int | None:
    return int(value) if value else None


def horizon(points: list[Point], day: int, tolerance_hours: int) -> Point | None:
    target = day * 86400
    eligible = [point for point in points if point.age <= target]
    if not eligible:
        return None
    last = eligible[-1]
    return last if target - last.age <= tolerance_hours * 3600 else None


def summarize(path: Path) -> dict:
    series: dict[tuple[str, str, int, str], list[Point]] = defaultdict(list)
    with path.open(newline="") as source:
        for row in csv.reader(source):
            if len(row) != 24 or not row[9] or row[22] != "f":
                continue
            platform, publication_id, _, _, _, _, completeness, _, rank = row[:9]
            series[(platform, publication_id, int(rank), completeness)].append(
                Point(
                    age=int(row[10]),
                    views=number(row[12]),
                    reactions=number(row[13]),
                    comments=number(row[14]),
                    shares=number(row[15]),
                    corrected=int(row[23]) > 0,
                )
            )

    cases = []
    for (platform, publication_id, rank, completeness), points in series.items():
        points.sort(key=lambda point: point.age)
        at_3 = horizon(points, 3, 12)
        at_14 = horizon(points, 14, 24)
        reaction_steps = [
            {"start_day": round(a.age / 86400, 3),
             "end_day": round(b.age / 86400, 3),
             "delta_reactions": b.reactions - a.reactions,
             "delta_views": None if a.views is None or b.views is None else b.views - a.views}
            for a, b in zip(points, points[1:])
            if a.reactions is not None and b.reactions is not None
        ]
        later = [step for step in reaction_steps if step["start_day"] >= 3]
        late_change = (
            at_14.reactions - at_3.reactions
            if at_3 and at_14 and at_3.reactions is not None
            and at_14.reactions is not None and points[0].age <= 86400
            else None
        )
        cases.append({
            "platform": platform,
            "publication_id": publication_id,
            "sample_rank": rank,
            "history_completeness": completeness,
            "point_count": len(points),
            "first_age_hours": round(points[0].age / 3600, 2),
            "last_age_days": round(points[-1].age / 86400, 2),
            "corrected_point_count": sum(point.corrected for point in points),
            "negative_view_steps": sum(
                a.views is not None and b.views is not None and b.views < a.views
                for a, b in zip(points, points[1:])
            ),
            "negative_reaction_steps": sum(
                a.reactions is not None and b.reactions is not None
                and b.reactions < a.reactions for a, b in zip(points, points[1:])
            ),
            "day3_reactions": at_3.reactions if at_3 else None,
            "day14_views": at_14.views if at_14 else None,
            "day14_reactions": at_14.reactions if at_14 else None,
            "day3_to_day14_reaction_change": late_change,
            "largest_late_reaction_step": max(
                later, key=lambda step: step["delta_reactions"], default=None
            ),
        })
    cases.sort(key=lambda case: (case["platform"], case["sample_rank"]))
    platforms = {}
    for platform in sorted({case["platform"] for case in cases}):
        subset = [case for case in cases if case["platform"] == platform]
        platforms[platform] = {
            "posts": len(subset),
            "median_points": statistics.median(case["point_count"] for case in subset),
            "median_first_age_hours": round(statistics.median(
                case["first_age_hours"] for case in subset), 2),
            "first_after_24h": sum(case["first_age_hours"] > 24 for case in subset),
            "corrected_posts": sum(case["corrected_point_count"] > 0 for case in subset),
        }
    return {"platforms": platforms, "cases": cases}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: pilot_features.py INPUT_CSV")
    print(json.dumps(summarize(Path(sys.argv[1])), ensure_ascii=False, indent=2))
