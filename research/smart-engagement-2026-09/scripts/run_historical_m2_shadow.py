#!/usr/bin/env python3
"""Run the M1/M2 research chain on a bounded, historical MAX snapshot sample.

This is an archive demonstration, not a calibrated or public anomaly verdict.
Snapshots were retained on counter changes, so the sampled read pairs are not
the full set of successful polls. In particular, exact zero prevalence and
tail ranks cannot be generalized to all monitored posts. The script reads a
local database only; set ANOMALY_DATABASE_URL and pass --output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.neighbor_exposure import (  # noqa: E402
    PublishedPost, SuccessfulRead, interval_for_reads,
)
from anomaly_analysis.v2.event_adjusted_tail import (  # noqa: E402
    FeedObservedGrowth, feed_observation, validate_future_m2,
)
from anomaly_analysis.v2.receipt_panel import consecutive_growth  # noqa: E402


PLATFORM = "max"
FIRST_DAY = date(2026, 9, 7)
FIT_END = date(2026, 9, 14)
CAL_END = date(2026, 9, 19)
LAST_DAY = date(2026, 9, 24)
MAX_GAP = timedelta(hours=2)
HASH_DIVISOR = 10

POSTS = """
SELECT p.id,p.primary_account_id,p.published_at
FROM ingest.visible_publication p
JOIN catalog.visible_platform_account a ON a.id=p.primary_account_id
WHERE a.platform::text=%s AND p.published_at >= %s AND p.published_at < %s
ORDER BY p.primary_account_id,p.published_at,p.id
"""

SELECTED = """
SELECT id FROM ingest.visible_publication
WHERE id=ANY(%s) AND abs(hashtext(id::text)::bigint) %% %s=0
"""

SNAPSHOTS = """
SELECT DISTINCT ON (s.publication_id,s.observed_at)
 s.publication_id,p.primary_account_id,s.observed_at,s.views_count,
 s.views_quality::text AS views_quality,s.interval_uncertain
FROM ingest.publication_metric_snapshot_active s
JOIN ingest.visible_publication p ON p.id=s.publication_id
WHERE s.publication_id=ANY(%s) AND s.published_month=%s
 AND s.observed_at >= %s AND s.observed_at < %s
 AND s.observed_at >= p.published_at
 AND s.observed_at < p.published_at+interval '7 days'
 AND NOT s.synthetic
ORDER BY s.publication_id,s.observed_at,s.correction_sequence DESC
"""

FIRST_EVENT_READS = """
SELECT p.id,p.primary_account_id,s.observed_at,s.views_count
FROM ingest.visible_publication p
JOIN LATERAL (
 SELECT observed_at,views_count
 FROM ingest.publication_metric_snapshot_active s
 WHERE s.publication_id=p.id
   AND s.published_month=date_trunc('month',p.published_at)::date
   AND s.observed_at >= p.published_at AND s.observed_at < %s
   AND s.views_quality::text='exact' AND s.views_count IS NOT NULL
   AND NOT s.synthetic AND NOT s.interval_uncertain
 ORDER BY s.observed_at,s.correction_sequence DESC LIMIT 1
) s ON true
WHERE p.id=ANY(%s)
"""


def _read_archive(connection):
    """Return selected post metadata, all visible feed order, and saved reads."""
    with connection.cursor() as cursor:
        cursor.execute(POSTS, (PLATFORM, FIRST_DAY, LAST_DAY))
        post_rows = cursor.fetchall()
        cursor.execute(SELECTED, ([row["id"] for row in post_rows], HASH_DIVISOR))
        selected_ids = {row["id"] for row in cursor.fetchall()}
        by_account: dict[UUID, list[PublishedPost]] = defaultdict(list)
        for row in post_rows:
            by_account[row["primary_account_id"]].append(
                PublishedPost(row["id"], row["primary_account_id"], row["published_at"])
            )
        cursor.execute(SNAPSHOTS, (list(selected_ids), FIRST_DAY.replace(day=1),
                                   FIRST_DAY, LAST_DAY))
        snapshot_rows = cursor.fetchall()
    reads = [SuccessfulRead(row["publication_id"], row["primary_account_id"],
                            row["observed_at"], row["views_count"],
                            row["views_quality"], row["interval_uncertain"])
             for row in snapshot_rows]
    selected = [post for posts in by_account.values() for post in posts
                if post.publication_id in selected_ids]
    return selected, by_account, reads


def _split(intervals, selected):
    groups = {"fit": [], "calibration": [], "holdout": []}
    discarded = Counter()
    published_day = {post.publication_id: post.published_at.date() for post in selected}
    for row in intervals:
        if row.status != "usable" or row.rounded:
            discarded[row.status if row.status != "usable" else "rounded"] += 1
            continue
        if row.end_at - row.start_at > MAX_GAP:
            discarded["excessive_gap"] += 1
            continue
        # Account-day blocks must not cross a UTC calendar boundary.
        day = row.end_at.date()
        if day != row.start_at.date():
            discarded["cross_day"] += 1
            continue
        if FIRST_DAY <= day < FIT_END:
            period = "fit"
            lower, upper = FIRST_DAY, FIT_END
        elif FIT_END <= day < CAL_END:
            period = "calibration"
            lower, upper = FIT_END, CAL_END
        elif CAL_END <= day < LAST_DAY:
            period = "holdout"
            lower, upper = CAL_END, LAST_DAY
        else:
            continue
        if not lower <= published_day[row.publication_id] < upper:
            discarded["post_outside_period_cohort"] += 1
            continue
        groups[period].append(row)
    return groups, discarded


def _exposure_rows(group, by_account, reads_by_key):
    preliminary = []
    needed_ids = set()
    for row in group:
        before = reads_by_key[(row.publication_id, row.start_at)]
        after = reads_by_key[(row.publication_id, row.end_at)]
        # Archive-only proxy: today's visible feed does not prove historical
        # completeness. These M2 ranks must never be promoted to worker output.
        exposure = interval_for_reads(
            before, after, tuple(by_account[row.account_id]), max_gap=MAX_GAP,
            complete_order=True, max_neighbor_distance=32,
        )
        if exposure.status != "usable":
            raise ValueError(f"archive pair and feed exposure disagree: {exposure.status}")
        preliminary.append((row, exposure))
        needed_ids.update(exposure.event_publication_ids)
    return preliminary, needed_ids


def _event_reads(connection, ids):
    measured = {}
    with connection.cursor() as cursor:
        ordered = sorted(ids)
        for start in range(0, len(ordered), 400):
            cursor.execute(FIRST_EVENT_READS, (LAST_DAY, ordered[start:start + 400]))
            for row in cursor:
                measured[row["id"]] = SuccessfulRead(
                    row["id"], row["primary_account_id"], row["observed_at"],
                    row["views_count"], "exact",
                )
    return measured


def _example(row, paired):
    return {
        "publication_id": str(row.interval.publication_id),
        "account_id": str(row.interval.account_id),
        "start_at": row.interval.start_at.isoformat(),
        "end_at": row.interval.end_at.isoformat(),
        "before_views": row.interval.before_views,
        "delta_views": row.interval.displayed_delta_views,
        "new_post_distance": row.nearest_event_distance,
        "new_post_views": row.new_post_views,
        "m1_tail_rank": round(paired.m1.upper_tail_rank, 4),
        "m2_tail_rank": round(paired.m2.upper_tail_rank, 4),
        "m1_reference_blocks": paired.m1.calibration_blocks,
        "m2_reference_blocks": paired.m2.calibration_blocks,
    }


def _first_comparable_event_per_post(holdout, results):
    """One prespecified event observation per post, independent of its rank."""
    first = {}
    for row, result in zip(holdout, results, strict=True):
        if (row.nearest_event_distance is None
                or result.m1.status != "ranked" or result.m2.status != "ranked"):
            continue
        post_id = row.interval.publication_id
        previous = first.get(post_id)
        if previous is None or row.interval.end_at < previous[0].interval.end_at:
            first[post_id] = (row, result)
    selected = tuple(first.values())
    m1_small = sum(result.m1.upper_tail_rank <= .05 for _row, result in selected)
    m2_small = sum(result.m2.upper_tail_rank <= .05 for _row, result in selected)
    return {
        "selection": "earliest fully ranked new-post interval per publication; no rank-based selection",
        "posts": len(selected),
        "m1_small_tail_posts": m1_small,
        "m2_small_tail_posts": m2_small,
        "m1_only": sum(result.m1.upper_tail_rank <= .05 < result.m2.upper_tail_rank
                       for _row, result in selected),
        "m2_only": sum(result.m2.upper_tail_rank <= .05 < result.m1.upper_tail_rank
                       for _row, result in selected),
    }


def _summary(selected, reads, intervals, split, discarded, cal, holdout, validation):
    paired = [(row, result) for row, result in zip(holdout, validation.holdout, strict=True)
              if row.nearest_event_distance is not None
              and result.m1.status == result.m2.status == "ranked"]
    raised = sorted((item for item in paired
                     if item[1].m2.upper_tail_rank > item[1].m1.upper_tail_rank),
                    key=lambda item: item[1].m2.upper_tail_rank - item[1].m1.upper_tail_rank,
                    reverse=True)
    lowered = sorted((item for item in paired
                      if item[1].m2.upper_tail_rank < item[1].m1.upper_tail_rank),
                     key=lambda item: item[1].m1.upper_tail_rank - item[1].m2.upper_tail_rank,
                     reverse=True)
    m1_high = sum(result.m1.upper_tail_rank <= .05 for _row, result in paired)
    m2_high = sum(result.m2.upper_tail_rank <= .05 for _row, result in paired)
    m1_only = sum(result.m1.upper_tail_rank <= .05 < result.m2.upper_tail_rank
                  for _row, result in paired)
    m2_only = sum(result.m2.upper_tail_rank <= .05 < result.m1.upper_tail_rank
                  for _row, result in paired)
    context_counts = {}
    for name, event in (("new_post", True), ("no_new_post", False)):
        ranked = [(row, result) for row, result in zip(holdout, validation.holdout, strict=True)
                  if (row.nearest_event_distance is not None) == event
                  and result.m1.status == result.m2.status == "ranked"]
        context_counts[name] = {
            "pairs": len(ranked),
            "posts": len({row.interval.publication_id for row, _result in ranked}),
            "m1_small_tail_pairs": sum(result.m1.upper_tail_rank <= .05
                                       for _row, result in ranked),
            "m2_small_tail_pairs": sum(result.m2.upper_tail_rank <= .05
                                       for _row, result in ranked),
            "m1_small_tail_posts": len({row.interval.publication_id for row, result in ranked
                                        if result.m1.upper_tail_rank <= .05}),
            "m2_small_tail_posts": len({row.interval.publication_id for row, result in ranked
                                        if result.m2.upper_tail_rank <= .05}),
        }
    return {
        "kind": "historical_change_sample_shadow_not_public_validation",
        "platform": PLATFORM,
        "selection": "1/10 publication IDs by PostgreSQL hashtext; post-disjoint UTC cohorts; 7-day post age; 2-hour maximum saved-read gap",
        "utc_splits": {"fit": [str(FIRST_DAY), str(FIT_END)],
                       "calibration": [str(FIT_END), str(CAL_END)],
                       "holdout": [str(CAL_END), str(LAST_DAY)]},
        "selected_posts": len(selected),
        "selected_accounts": len({row.account_id for row in selected}),
        "posts_with_saved_reads": len({row.publication_id for row in reads}),
        "saved_reads": len(reads),
        "read_pairs_all_statuses": len(intervals),
        "discarded_pair_statuses": dict(sorted(discarded.items())),
        "exact_usable_pairs_by_split": {key: len(value) for key, value in split.items()},
        "posts_in_multiple_splits": len(
            {row.publication_id for row in split["fit"]}
            & ({row.publication_id for row in split["calibration"]}
               | {row.publication_id for row in split["holdout"]})
            | ({row.publication_id for row in split["calibration"]}
               & {row.publication_id for row in split["holdout"]})
        ),
        "fitted_m1_cells": len(validation.m1.baseline.cells),
        "calibrated_m1_cells": len(validation.m1.reference.blocks),
        "calibrated_m2_cells": len(validation.m2.blocks),
        "calibration_event_pairs": sum(row.nearest_event_distance is not None for row in cal),
        "holdout_event_pairs": sum(row.nearest_event_distance is not None for row in holdout),
        "holdout_m1_status": dict(sorted(Counter(item.m1.status for item in validation.holdout).items())),
        "holdout_m2_status": dict(sorted(Counter(item.m2.status for item in validation.holdout).items())),
        "holdout_paired_ranked": validation.paired_ranked_count,
        "holdout_event_paired_ranked": len(paired),
        "holdout_ranked_by_context": context_counts,
        "event_paired_5pct_diagnostic": {
            "m1_small_tail": m1_high, "m2_small_tail": m2_high,
            "m1_only": m1_only, "m2_only": m2_only,
        },
        "first_comparable_event_per_post": _first_comparable_event_per_post(
            holdout, validation.holdout),
        "event_examples_m2_less_unusual": [_example(*item) for item in raised[:3]],
        "event_examples_m2_more_unusual": [_example(*item) for item in lowered[:3]],
        "limits": [
            "Historical snapshots are change-triggered and omit many unchanged successful reads.",
            "Feed order is reconstructed from currently visible publications; deleted or missed posts may be absent.",
            "New-post reach is a displayed counter proxy, not observed referrals to the old post.",
            "The 5% rank cut is descriptive and has no validated false-alert interpretation.",
            "Posts are disjoint across periods, but repeated holdout intervals of one post are not independent alerts.",
            "The split dates were chosen after earlier exploration and are not a pristine prospective holdout.",
        ],
    }


def run(connection):
    selected, by_account, reads = _read_archive(connection)
    if not selected or not reads:
        raise ValueError(f"local archive selection empty: posts={len(selected)}, reads={len(reads)}")
    intervals = consecutive_growth(
        reads, selected, {post.account_id: PLATFORM for post in selected},
        max_gap_by_platform={PLATFORM: MAX_GAP},
    )
    split, discarded = _split(intervals, selected)
    reads_by_key = {(read.publication_id, read.observed_at): read for read in reads}
    cal_pre, cal_ids = _exposure_rows(split["calibration"], by_account, reads_by_key)
    hold_pre, hold_ids = _exposure_rows(split["holdout"], by_account, reads_by_key)
    event_reads = _event_reads(connection, cal_ids | hold_ids)
    cal = tuple(feed_observation(row, exposure, event_reads) for row, exposure in cal_pre)
    holdout = tuple(feed_observation(row, exposure, event_reads)
                    for row, exposure in hold_pre)
    validation = validate_future_m2(tuple(split["fit"]), cal, holdout)
    return _summary(selected, reads, intervals, split, discarded, cal, holdout, validation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, row_factory=dict_row,
                         options="-c default_transaction_read_only=on -c statement_timeout=120000") as connection:
        result = run(connection)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "selected_posts", "saved_reads", "exact_usable_pairs_by_split",
        "holdout_m1_status", "holdout_m2_status", "holdout_event_paired_ranked",
        "event_paired_5pct_diagnostic")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
