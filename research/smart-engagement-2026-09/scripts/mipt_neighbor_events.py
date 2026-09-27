#!/usr/bin/env python3
"""Summarize the bounded MIPT snapshot CSV around four new post times.

Usage: python3 scripts/mipt_neighbor_events.py /private/tmp/tg_mipt_neighbor_snapshots.csv
The source CSV stays temporary; only ten event-crossing intervals are saved.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "publication_id external_id published_at observed_at age_seconds sampling_bucket "
    "views_count reactions_count views_quality reactions_quality interval_uncertain "
    "synthetic correction_sequence collection_run_id"
).split()
EVENT_IDS = (11343, 11344, 11345, 11346)
MOSCOW = timezone(timedelta(hours=3))


def instant(value: str) -> datetime:
    # PostgreSQL emits +00 rather than +00:00 in its text timestamptz format.
    normalized = value[:-3] + "+00:00" if value.endswith("+00") else value
    pattern = "%Y-%m-%d %H:%M:%S.%f%z" if "." in normalized else "%Y-%m-%d %H:%M:%S%z"
    return datetime.strptime(normalized, pattern)


def clock(value: str) -> str:
    return instant(value).astimezone(MOSCOW).isoformat(timespec="seconds")


def main(path: Path) -> None:
    with path.open(newline="") as source:
        rows = list(csv.DictReader(source, fieldnames=FIELDS))
    if not rows or any(None in row for row in rows):
        raise ValueError("Missing rows or unexpected CSV width")
    series: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["observed_at"] and row["synthetic"] == "f":
            series[int(row["external_id"].split(":")[1])].append(row)
    for values in series.values():
        values.sort(key=lambda row: row["observed_at"])
    if set(series) != set(range(11342, 11350)):
        raise ValueError(f"Unexpected publication set: {sorted(series)}")

    result = []
    for new_id in EVENT_IDS:
        new_points = series[new_id]
        published = new_points[0]["published_at"]
        for old_id in sorted(key for key in series if key < new_id):
            old_points = series[old_id]
            before = [row for row in old_points if row["observed_at"] <= published]
            after = [row for row in old_points if row["observed_at"] > published]
            if not before or not after:
                continue
            start, end = before[-1], after[0]
            new_at_end = [row for row in new_points if row["observed_at"] <= end["observed_at"]]
            result.append({
                "new_post": new_id,
                "new_published_msk": clock(published),
                "old_post": old_id,
                "old_start_msk": clock(start["observed_at"]),
                "old_end_msk": clock(end["observed_at"]),
                "stored_interval_minutes": round((instant(end["observed_at"])
                                                  - instant(start["observed_at"])).total_seconds() / 60, 2),
                "old_views_start": int(start["views_count"]),
                "old_views_end": int(end["views_count"]),
                "delta_rounded_views": int(end["views_count"]) - int(start["views_count"]),
                "delta_reactions": int(end["reactions_count"]) - int(start["reactions_count"]),
                "old_views_quality": end["views_quality"],
                "old_end_corrected": int(end["correction_sequence"]) > 0,
                "new_views_by_old_end": int(new_at_end[-1]["views_count"])
                    if new_at_end and new_at_end[-1]["views_count"] else None,
            })
    destination = ROOT / "evidence" / "mipt_neighbor_2026-09-26" / "event_windows.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(result)} event-crossing intervals saved")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: mipt_neighbor_events.py INPUT_CSV")
    main(Path(sys.argv[1]))
