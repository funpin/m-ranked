#!/usr/bin/env python3
"""Read-only prospective bounded post ranks from M0 receipts and daily reference."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from math import inf, nextafter
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead  # noqa: E402
from anomaly_analysis.v2.bounded_post import score_bounded_post  # noqa: E402
from anomaly_analysis.v2.cohort_coverage import audit_cohort_coverage  # noqa: E402
from anomaly_analysis.v2.post_tail import EARLY_CHECKPOINTS  # noqa: E402
from anomaly_analysis.v2.rounded_tail import (  # noqa: E402
    BoundedTailReference, DailyUpperBound,
)


def _utc(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("through must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("telegram", "max", "vk", "rutube"),
                        required=True)
    parser.add_argument("--account", type=UUID, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--through", type=_utc, required=True)
    parser.add_argument("--max-gap-minutes", type=int, required=True)
    parser.add_argument("--checkpoints", choices=("1h", "6h", "24h", "early3"),
                        required=True)
    args = parser.parse_args()
    if not args.start < args.end:
        parser.error("start must be before end")
    if not 5 <= args.max_gap_minutes <= 1440:
        parser.error("max gap must be 5–1440 minutes")
    start_at = datetime.combine(args.start, time.min, timezone.utc)
    end_at = datetime.combine(args.end, time.min, timezone.utc)
    if args.through < end_at:
        parser.error("through must include the whole publication window")
    checks = (EARLY_CHECKPOINTS[:3] if args.checkpoints == "early3" else
              tuple(check for check in EARLY_CHECKPOINTS[:3]
                    if check.name == args.checkpoints))
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    with psycopg.connect(dsn, row_factory=dict_row,
                         options="-c default_transaction_read_only=on -c statement_timeout=120000") as connection:
        if connection.execute(
            "SELECT to_regclass('analytics.bounded_poll_growth_daily') AS name"
        ).fetchone()["name"] is None:
            parser.error("migration 0048 is missing")
        reference_rows = connection.execute(
            """SELECT source,platform,account_id,publication_id,observed_day,
                      age_band,exposure_band,upper_rate_per_hour
                 FROM analytics.bounded_poll_growth_daily
                WHERE account_id=%s AND platform=%s
                  AND observed_day >= %s AND observed_day < %s""",
            (args.account, args.platform,
             args.start - timedelta(days=120), args.start),
        ).fetchall()
        frame = connection.execute(
            """SELECT p.id,p.primary_account_id,p.published_at
                 FROM ingest.publication p
                 JOIN catalog.platform_account a ON a.id=p.primary_account_id
                WHERE p.primary_account_id=%s AND a.platform::text=%s
                  AND p.published_at >= %s AND p.published_at < %s
                ORDER BY p.published_at,p.id LIMIT 5001""",
            (args.account, args.platform, start_at, end_at),
        ).fetchall()
        if len(frame) > 5000:
            parser.error("publication frame exceeds 5,000 posts")
        ids = [row["id"] for row in frame]
        receipt_rows = connection.execute(
            """SELECT r.publication_id,p.primary_account_id,r.observed_at,
                      r.views_count,r.views_quality::text AS views_quality,
                      r.interval_uncertain,r.views_display_unit
                 FROM ingest.publication_poll_receipt r
                 JOIN ingest.publication p ON p.id=r.publication_id
                WHERE r.publication_id=ANY(%s::uuid[])
                  AND r.observed_at <= %s
                ORDER BY r.publication_id,r.observed_at LIMIT 250001""",
            (ids, args.through),
        ).fetchall() if ids else []
    if len(receipt_rows) > 250_000:
        parser.error("receipt window exceeds 250,000 rows")
    posts = tuple(PublishedPost(row["id"], row["primary_account_id"],
                                row["published_at"]) for row in frame)
    reads = tuple(SuccessfulRead(
        row["publication_id"], row["primary_account_id"], row["observed_at"],
        row["views_count"], row["views_quality"], row["interval_uncertain"],
        row["views_display_unit"],
    ) for row in receipt_rows)
    reference_data = tuple(DailyUpperBound(
        row["source"], row["platform"], row["account_id"], row["publication_id"],
        row["observed_day"], row["age_band"], row["exposure_band"],
        nextafter(float(row["upper_rate_per_hour"]), inf),
    ) for row in reference_rows)
    reference = (BoundedTailReference.fit_daily(
        reference_data, source="successful_poll_receipts",
        max_gap=timedelta(minutes=args.max_gap_minutes),
    ) if reference_data else None)
    coverage = audit_cohort_coverage(
        posts, reads, {args.account: args.platform}, frozenset({args.account}),
        checks, cohort_start=start_at, cohort_end=end_at,
        observed_through=args.through,
        max_gap_by_platform={args.platform: timedelta(minutes=args.max_gap_minutes)},
        source="successful_poll_receipts", require_bounded_views=True,
    )
    by_post = {post.publication_id: post for post in posts}
    reads_by_post = {}
    for read in reads:
        reads_by_post.setdefault(read.publication_id, []).append(read)
    scores = [score_bounded_post(
        by_post[item.publication_id], item,
        reads_by_post.get(item.publication_id, ()), reference,
    ) for item in coverage] if reference else []
    statuses = Counter(score.status for score in scores)
    if not reference:
        statuses["insufficient_reference"] = len(posts)
    ranked = sorted((score for score in scores if score.post_rank_bound is not None),
                    key=lambda score: (score.post_rank_bound, str(score.publication_id)))
    print(json.dumps({
        "kind": "prospective_bounded_post_research_not_public_anomaly_verdict",
        "platform": args.platform,
        "checkpoint_plan": [check.name for check in checks],
        "eligible_posts": len(posts),
        "receipt_rows": len(reads),
        "reference_rows": len(reference_data),
        "coverage": dict(sorted(Counter(row.status for row in coverage).items())),
        "score_status": dict(sorted(statuses.items())),
        "rank_at_most_5pct": sum(score.post_rank_bound <= .05 for score in ranked),
        "best_attainable_bound": min(
            (score.best_attainable_bound for score in ranked), default=None),
        "lowest_ranked": [
            {"publication_id": str(score.publication_id),
             "post_rank_bound": score.post_rank_bound,
             "best_attainable_bound": score.best_attainable_bound}
            for score in ranked[:10]
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
