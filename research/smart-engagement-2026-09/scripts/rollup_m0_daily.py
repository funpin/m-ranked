#!/usr/bin/env python3
"""Build a small 120-day M1 reference from complete opt-in poll receipts.

Dry run is the default. Writing requires an explicit database name and migration
0048. This command never reads the change-only metric snapshot table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead  # noqa: E402
from anomaly_analysis.v2.rounded_growth import bounded_view_growth  # noqa: E402
from anomaly_analysis.v2.rounded_tail import (  # noqa: E402
    BoundedInterval, summarize_daily_upper_bounds,
)


MAX_RECEIPTS = 250_000
RETENTION_DAYS = 120

READS = """
SELECT r.publication_id, p.primary_account_id, p.published_at,
       a.platform::text AS platform, r.observed_at, r.views_count,
       r.views_quality::text AS views_quality, r.interval_uncertain,
       r.views_display_unit
FROM ingest.publication_poll_receipt r
JOIN ingest.publication p ON p.id = r.publication_id
JOIN catalog.platform_account a ON a.id = p.primary_account_id
WHERE p.primary_account_id = ANY(%s::uuid[])
  AND a.platform::text = %s
  AND r.observed_at >= %s AND r.observed_at < %s
ORDER BY r.publication_id, r.observed_at
LIMIT %s
"""

UPSERT = """
INSERT INTO analytics.bounded_poll_growth_daily (
    publication_id, account_id, platform, observed_day,
    age_band, exposure_band, upper_rate_per_hour, source
) VALUES (%s, %s, %s, %s, %s, %s, %s, 'successful_poll_receipts')
ON CONFLICT (publication_id, observed_day, age_band, exposure_band)
DO UPDATE SET upper_rate_per_hour = GREATEST(
    analytics.bounded_poll_growth_daily.upper_rate_per_hour,
    EXCLUDED.upper_rate_per_hour
), updated_at = transaction_timestamp()
"""


def _summarize(rows, start: date, end: date, max_gap: timedelta):
    posts = {}
    platforms = {}
    groups = defaultdict(list)
    for row in rows:
        post_id = row["publication_id"]
        posts[post_id] = PublishedPost(
            post_id, row["primary_account_id"], row["published_at"],
        )
        platforms[post_id] = row["platform"]
        groups[post_id].append(SuccessfulRead(
            post_id, row["primary_account_id"], row["observed_at"],
            row["views_count"], row["views_quality"],
            row["interval_uncertain"], row["views_display_unit"],
        ))
    candidates = []
    statuses = Counter()
    for post_id, reads in groups.items():
        reads.sort(key=lambda item: item.observed_at)
        for before, after in zip(reads, reads[1:]):
            day = after.observed_at.astimezone(timezone.utc).date()
            if not start <= day < end:
                continue
            if before.observed_at >= after.observed_at:
                statuses["nonincreasing_read_time"] += 1
                continue
            if before.observed_at.astimezone(timezone.utc).date() != day:
                statuses["cross_day"] += 1
                continue
            if before.observed_at < posts[post_id].published_at:
                statuses["before_publication"] += 1
                continue
            growth = bounded_view_growth(before, after, max_gap=max_gap)
            statuses[growth.status] += 1
            if growth.status == "bounded":
                candidates.append(BoundedInterval(
                    platforms[post_id],
                    posts[post_id], before, after,
                ))
    daily = summarize_daily_upper_bounds(
        candidates, source="successful_poll_receipts", max_gap=max_gap,
    )
    return daily, statuses, len(posts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("telegram", "max", "vk", "rutube"),
                        required=True)
    parser.add_argument("--account", action="append", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--max-gap-minutes", type=int, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expected-database")
    args = parser.parse_args()
    accounts = tuple(UUID(raw) for raw in args.account)
    if not 1 <= len(set(accounts)) == len(accounts) <= 16:
        parser.error("select 1–16 distinct account IDs")
    if not args.start < args.end:
        parser.error("start must be before end")
    if not 5 <= args.max_gap_minutes <= 1440:
        parser.error("max gap must be 5–1440 minutes")
    if args.write and not args.expected_database:
        parser.error("--write requires --expected-database")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    start_at = datetime.combine(args.start, time.min, timezone.utc)
    end_at = datetime.combine(args.end, time.min, timezone.utc)
    max_gap = timedelta(minutes=args.max_gap_minutes)
    with psycopg.connect(dsn, row_factory=dict_row,
                         options="-c statement_timeout=120000") as connection:
        database = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if args.write and database != args.expected_database:
            parser.error("database name does not match --expected-database")
        with connection.cursor() as cursor:
            cursor.execute(READS, (list(accounts), args.platform, start_at - max_gap,
                                   end_at, MAX_RECEIPTS + 1))
            rows = cursor.fetchall()
        if len(rows) > MAX_RECEIPTS:
            parser.error("receipt window exceeds the bounded local run limit")
        daily, statuses, post_count = _summarize(rows, args.start, args.end, max_gap)
        pruned = 0
        if args.write:
            if connection.execute(
                "SELECT to_regclass('analytics.bounded_poll_growth_daily') AS name"
            ).fetchone()["name"] is None:
                parser.error("migration 0048 is missing")
            with connection.cursor() as cursor:
                cursor.executemany(UPSERT, [
                    (row.publication_id, row.account_id, row.platform,
                     row.observed_day, row.age_band, row.exposure_band,
                     Decimal(str(row.upper_rate_per_hour)).quantize(
                         Decimal("0.000001"), rounding=ROUND_CEILING))
                    for row in daily
                ])
                cursor.execute(
                    "DELETE FROM analytics.bounded_poll_growth_daily "
                    "WHERE observed_day < %s",
                    (datetime.now(timezone.utc).date() - timedelta(days=RETENTION_DAYS),),
                )
                pruned = cursor.rowcount
            connection.commit()
    print(json.dumps({
        "kind": "bounded_receipt_reference_rollup_not_anomaly_verdict",
        "database": database,
        "platform": args.platform,
        "window": [str(args.start), str(args.end)],
        "receipt_rows": len(rows),
        "posts_with_receipts": post_count,
        "pair_status": dict(sorted(statuses.items())),
        "daily_summary_rows": len(daily),
        "written": args.write,
        "pruned_older_than_120_days": pruned,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
