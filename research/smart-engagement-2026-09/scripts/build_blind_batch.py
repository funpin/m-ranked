#!/usr/bin/env python3
"""Package a bounded SQL CSV into a reviewer-only directory and organizer key.

Run from this research directory:
  python3 scripts/build_blind_batch.py /private/tmp/tg_blind_batch_01.csv

Never give the organizer key or 05_pilot_annotations.md to reviewers.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_COLUMNS = (
    "platform publication_id sample_rank sampling_arm public_url published_at "
    "publication_type is_repost history_completeness first_observation_age_seconds "
    "content_group_id observed_at age_seconds sampling_bucket views_count "
    "reactions_count comments_count shares_count views_quality reactions_quality "
    "comments_quality shares_quality interval_uncertain synthetic correction_sequence"
).split()
SERIES_COLUMNS = (
    "card_id observed_at age_seconds views_count reactions_count comments_count "
    "shares_count views_quality reactions_quality comments_quality shares_quality "
    "interval_uncertain synthetic corrected"
).split()


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(source_path: Path) -> None:
    with source_path.open(newline="") as source:
        raw = list(csv.DictReader(source, fieldnames=INPUT_COLUMNS))
    if not raw or any(None in row for row in raw):
        raise ValueError("Missing rows or unexpected CSV width")
    by_post: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in raw:
        by_post[row["publication_id"]].append(row)
    if len(by_post) != 32:
        raise ValueError(f"Expected 32 publications, found {len(by_post)}")
    counts = Counter((rows[0]["platform"], rows[0]["sampling_arm"])
                     for rows in by_post.values())
    if set(counts.values()) != {4} or len(counts) != 8:
        raise ValueError(f"Expected four cases in each platform/arm: {counts}")

    # A fixed opaque order makes reruns stable. The label key remains outside
    # the reviewer directory; URL access alone cannot hide an earlier local file.
    ordered_ids = sorted(by_post, key=lambda value: hashlib.sha256(
        ("blind-batch-01-2026-09-26:" + value).encode()).hexdigest())
    labels: dict[str, dict[str, str]] = {}
    with (ROOT / "pilot_case_index.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            labels[row["publication_id"]] = row

    cards: list[dict[str, str]] = []
    series: list[dict[str, str]] = []
    forms: list[dict[str, str]] = []
    key: list[dict[str, str]] = []
    for number, publication_id in enumerate(ordered_ids, 1):
        card_id = f"B01-{number:03d}"
        rows = sorted(by_post[publication_id],
                      key=lambda row: (row["observed_at"], row["sampling_bucket"]))
        first = rows[0]
        actual = [row for row in rows if row["observed_at"]]
        cards.append({
            "card_id": card_id,
            "platform": first["platform"],
            "public_url": first["public_url"],
            "published_at_utc": first["published_at"],
            "publication_type": first["publication_type"],
            "is_repost": first["is_repost"],
            "history_completeness": first["history_completeness"],
            "first_observation_age_seconds": first["first_observation_age_seconds"],
            "stored_points": str(len(actual)),
            "first_stored_observation_utc": actual[0]["observed_at"] if actual else "",
            "last_stored_observation_utc": actual[-1]["observed_at"] if actual else "",
        })
        for row in actual:
            series.append({
                "card_id": card_id,
                **{field: row[field] for field in SERIES_COLUMNS[1:-1]},
                "corrected": "1" if int(row["correction_sequence"] or 0) > 0 else "0",
            })
        forms.append({
            "card_id": card_id,
            "reviewer_id": "",
            "reviewed_at_utc": "",
            "horizon": "",
            "observed_unusual": "",
            "measurement_issue": "",
            "external_explanation": "",
            "external_source_url": "",
            "external_source_accessed_at_utc": "",
            "origin_evidence": "",
            "metric_and_age_interval": "",
            "confidence": "",
            "reasoning": "",
        })
        prior = labels.get(publication_id, {})
        key.append({
            "card_id": card_id,
            "platform": first["platform"],
            "sampling_arm": first["sampling_arm"],
            "sample_rank": first["sample_rank"],
            "publication_id": publication_id,
            "provisional_label": prior.get("provisional_label", "not_previously_reviewed"),
            "content_group_id": first["content_group_id"],
        })

    reviewer = ROOT / "annotation" / "batch_01_reviewer_only"
    write_csv(reviewer / "cards.csv", list(cards[0]), cards)
    write_csv(reviewer / "effective_series.csv", SERIES_COLUMNS, series)
    write_csv(reviewer / "reviewer_form_template.csv", list(forms[0]), forms)
    write_csv(ROOT / "annotation" / "batch_01_organizer_key.csv", list(key[0]), key)
    print(f"32 cards, {len(series)} selected effective rows")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_blind_batch.py INPUT_CSV")
    main(Path(sys.argv[1]))
