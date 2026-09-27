#!/usr/bin/env python3
"""Evaluate account-day bounded ranks on an isolated historical archive.

The change-only archive omits unchanged successful reads. Output is shadow
diagnostics, never a product anomaly decision or a false-alert estimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.v2.post_tail import EARLY_CHECKPOINTS  # noqa: E402
from anomaly_analysis.v2.receipt_panel import consecutive_growth  # noqa: E402
from anomaly_analysis.v2.rounded_tail import (  # noqa: E402
    BoundedInterval, BoundedTailReference,
)
from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead  # noqa: E402
from run_historical_m2_shadow import (  # noqa: E402
    HASH_DIVISOR, MAX_GAP, POSTS, SNAPSHOTS,
)


def _fixed_post_plan(holdout, ranks, metadata, checkpoints):
    by_post = defaultdict(list)
    for row, result in zip(holdout, ranks, strict=True):
        by_post[row.post.publication_id].append((row, result))
    evaluable = []
    resolution_floors = []
    statuses = Counter()
    for post_id, rows in by_post.items():
        chosen = []
        for check in checkpoints:
            candidate = [
                (abs((row.after.observed_at - metadata[post_id].published_at).total_seconds()
                     - check.age_seconds), row.after.observed_at, result)
                for row, result in rows
                if abs((row.after.observed_at - metadata[post_id].published_at).total_seconds()
                       - check.age_seconds) <= check.tolerance_seconds
            ]
            if not candidate:
                statuses["missing_checkpoint"] += 1
                break
            _distance, _at, result = min(candidate, key=lambda item: item[:2])
            if result.status != "shadow_only" or result.upper_tail_rank is None:
                statuses[result.status] += 1
                break
            chosen.append(result)
        if len(chosen) == len(checkpoints):
            evaluable.append((post_id, min(1.0, len(checkpoints) * min(
                result.upper_tail_rank for result in chosen))))
            resolution_floors.append(min(1.0, len(checkpoints) * min(
                1 / (result.calibration_days + 1) for result in chosen)))
    return {
        "checkpoints": [check.name for check in checkpoints],
        "posts_with_intervals": len(by_post),
        "evaluable_posts": len(evaluable),
        "abstention_reasons": dict(sorted(statuses.items())),
        "best_attainable_bound_for_evaluable_posts": min(resolution_floors, default=None),
        "post_bound_at_most_5pct": sum(rank <= .05 for _post, rank in evaluable),
        "post_bound_at_most_10pct": sum(rank <= .10 for _post, rank in evaluable),
        "least_post_bound": min((rank for _post, rank in evaluable), default=None),
    }


def _checkpoint_coverage(holdout, ranks, metadata):
    by_post = defaultdict(list)
    for row, result in zip(holdout, ranks, strict=True):
        by_post[row.post.publication_id].append((row, result))
    coverage = {}
    for check in EARLY_CHECKPOINTS[:3]:
        statuses = Counter()
        reference_days = []
        for post_id, rows in by_post.items():
            candidates = [
                (abs((row.after.observed_at - metadata[post_id].published_at).total_seconds()
                     - check.age_seconds), row.after.observed_at, result)
                for row, result in rows
                if abs((row.after.observed_at - metadata[post_id].published_at).total_seconds()
                       - check.age_seconds) <= check.tolerance_seconds
            ]
            if not candidates:
                statuses["missing_checkpoint"] += 1
                continue
            result = min(candidates, key=lambda item: item[:2])[2]
            statuses[result.status] += 1
            reference_days.append(result.calibration_days)
        coverage[check.name] = {
            "posts_by_status": dict(sorted(statuses.items())),
            "median_reference_days_when_candidate_exists": (
                median(reference_days) if reference_days else None),
            "maximum_reference_days_when_candidate_exists": (
                max(reference_days, default=None)),
        }
    return coverage


def _next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def _read_window(connection, platform: str, start: date, end: date):
    with connection.cursor() as cursor:
        cursor.execute(POSTS, (platform, start, end))
        posts = cursor.fetchall()
        # Whole accounts preserve every observed post within an account-day.
        # Sampling individual posts makes daily maxima artificially small.
        selected_accounts = {
            row["primary_account_id"] for row in posts
            if int.from_bytes(hashlib.sha256(row["primary_account_id"].bytes).digest()[:8],
                              "big") % HASH_DIVISOR == 0
        }
        selected = [PublishedPost(row["id"], row["primary_account_id"],
                                  row["published_at"])
                    for row in posts if row["primary_account_id"] in selected_accounts]
        reads = []
        month = start.replace(day=1)
        while month < end:
            month_ids = [post.publication_id for post in selected
                         if post.published_at.date().replace(day=1) == month]
            if month_ids:
                cursor.execute(SNAPSHOTS, (month_ids, month, start, end))
                reads.extend(SuccessfulRead(
                    row["publication_id"], row["primary_account_id"],
                    row["observed_at"], row["views_count"],
                    row["views_quality"], row["interval_uncertain"],
                ) for row in cursor)
            month = _next_month(month)
    return selected, reads


def _split_window(intervals, selected, start: date, holdout_start: date, end: date):
    groups = {"reference": [], "holdout": []}
    discarded = Counter()
    publication_day = {post.publication_id: post.published_at.date() for post in selected}
    for row in intervals:
        if row.status != "usable" or row.rounded:
            discarded[row.status if row.status != "usable" else "rounded"] += 1
            continue
        if row.end_at - row.start_at > MAX_GAP:
            discarded["excessive_gap"] += 1
            continue
        day = row.end_at.date()
        if day != row.start_at.date():
            discarded["cross_day"] += 1
            continue
        if start <= day < holdout_start:
            period = "reference"
            lower, upper = start, holdout_start
        elif holdout_start <= day < end:
            period = "holdout"
            lower, upper = holdout_start, end
        else:
            continue
        if not lower <= publication_day[row.publication_id] < upper:
            discarded["post_outside_period_cohort"] += 1
            continue
        groups[period].append(row)
    return groups, discarded


def run(connection, platform: str, start: date, holdout_start: date, end: date):
    if not start < holdout_start < end:
        raise ValueError("expected start < holdout_start < end")
    selected, reads = _read_window(connection, platform, start, end)
    if not selected or not reads:
        return {"platform": platform, "status": "insufficient_data",
                "selected_posts": len(selected), "saved_reads": len(reads)}
    metadata = {post.publication_id: post for post in selected}
    intervals = consecutive_growth(
        reads, selected, {post.account_id: platform for post in selected},
        max_gap_by_platform={platform: MAX_GAP},
    )
    split, discarded = _split_window(intervals, selected, start, holdout_start, end)
    result = {
        "kind": "change_only_archive_shadow_not_public_validation",
        "platform": platform,
        "periods": {"reference": [str(start), str(holdout_start)],
                    "holdout": [str(holdout_start), str(end)]},
        "selected_posts": len(selected),
        "selected_accounts": len({post.account_id for post in selected}),
        "saved_reads": len(reads),
        "discarded_pairs": dict(sorted(discarded.items())),
        "exact_pairs_by_split": {name: len(rows) for name, rows in split.items()},
    }
    if not split["reference"] or not split["holdout"]:
        return result | {"status": "insufficient_data"}
    read_by_key = {(read.publication_id, read.observed_at): read for read in reads}

    def bounded(rows):
        return tuple(BoundedInterval(
            platform, metadata[row.publication_id],
            read_by_key[(row.publication_id, row.start_at)],
            read_by_key[(row.publication_id, row.end_at)],
        ) for row in rows)

    calibration, holdout = bounded(split["reference"]), bounded(split["holdout"])
    reference = BoundedTailReference.fit(
        calibration, source="change_only_shadow", max_gap=MAX_GAP,
        min_days=7, min_posts=5,
    )
    reference_days = sorted({day for block in reference.blocks.values() for day in block})
    ranks = tuple(reference.rank(row) for row in holdout)
    ranked = [(row, rank) for row, rank in zip(holdout, ranks, strict=True)
              if rank.status == "shadow_only" and rank.upper_tail_rank is not None]
    return result | {
        "status": "shadow_only",
        "reference_cells": len(reference.blocks),
        "reference_day_range": [str(reference_days[0]), str(reference_days[-1])],
        "reference_distinct_days": len(reference_days),
        "saved_read_quality_by_month": {
            month: dict(sorted(counts.items()))
            for month, counts in sorted(_read_quality_by_month(reads).items())
        },
        "interval_rank_status": dict(sorted(Counter(rank.status for rank in ranks).items())),
        "ranked_intervals": len(ranked),
        "ranked_posts": len({row.post.publication_id for row, _rank in ranked}),
        "ranked_reference_days": {
            "median": median((rank.calibration_days for _row, rank in ranked))
            if ranked else None,
            "maximum": max((rank.calibration_days for _row, rank in ranked), default=None),
        },
        "interval_rank_at_most_5pct": sum(rank.upper_tail_rank <= .05
                                          for _row, rank in ranked),
        "checkpoint_coverage": _checkpoint_coverage(holdout, ranks, metadata),
        "fixed_post_plan": {
            check.name: _fixed_post_plan(holdout, ranks, metadata, (check,))
            for check in EARLY_CHECKPOINTS[:3]
        } | {"1h_6h_24h": _fixed_post_plan(
            holdout, ranks, metadata, EARLY_CHECKPOINTS[:3],
        )},
        "limits": [
            "Saved snapshots omit unchanged successful reads.",
            "A rank is descriptive; the account-day reference is not a validated null model.",
            "Fixed post checkpoints require every planned interval to be present and ranked.",
        ],
    }


def _read_quality_by_month(reads):
    result = defaultdict(Counter)
    for read in reads:
        result[read.observed_at.date().strftime("%Y-%m")][read.views_quality] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("max", "telegram"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat,
                        default=date(2026, 8, 1))
    parser.add_argument("--holdout-start", type=date.fromisoformat,
                        default=date(2026, 9, 14))
    parser.add_argument("--end", type=date.fromisoformat,
                        default=date(2026, 9, 24))
    args = parser.parse_args()
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, row_factory=dict_row,
                         options="-c default_transaction_read_only=on -c statement_timeout=120000") as connection:
        result = run(connection, args.platform, args.start, args.holdout_start, args.end)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"limits"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
