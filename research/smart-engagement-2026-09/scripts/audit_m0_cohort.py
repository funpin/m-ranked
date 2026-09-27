"""Read-only M0 coverage audit on a local database with real poll receipts.

The eligible denominator comes from ingest.publication, never from receipts.
The command reports readiness only; it does not assign anomaly levels.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anomaly_analysis.neighbor_exposure import PublishedPost, SuccessfulRead
from anomaly_analysis.v2.cohort_coverage import audit_cohort_coverage
from anomaly_analysis.v2.post_tail import EARLY_CHECKPOINTS, LATE_CHECKPOINTS


def _utc(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("all dates must include a timezone")
    return parsed.astimezone(timezone.utc)


def _gap(raw: str) -> tuple[str, timedelta]:
    platform, sep, minutes = raw.partition(":")
    if not sep or platform not in {"telegram", "vk", "max", "rutube"}:
        raise ValueError("gap must be platform:minutes")
    value = int(minutes)
    if not 1 <= value <= 1440:
        raise ValueError("gap minutes must be between 1 and 1440")
    return platform, timedelta(minutes=value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", action="append", required=True,
                        help="opt-in account UUID, repeat for each account")
    parser.add_argument("--start", required=True, help="inclusive publication time, ISO 8601")
    parser.add_argument("--end", required=True, help="exclusive publication time, ISO 8601")
    parser.add_argument("--through", required=True, help="last receipt time, ISO 8601")
    parser.add_argument("--horizon", choices=("early", "late"), required=True)
    parser.add_argument("--max-gap-minutes", action="append", required=True,
                        help="platform:minutes, repeat for each selected platform")
    args = parser.parse_args()
    accounts = frozenset(UUID(value) for value in args.account)
    if not accounts or len(accounts) > 16:
        parser.error("select between 1 and 16 accounts")
    start, end, through = _utc(args.start), _utc(args.end), _utc(args.through)
    gaps = dict(_gap(raw) for raw in args.max_gap_minutes)
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    with psycopg.connect(dsn, row_factory=dict_row,
                         options="-c statement_timeout=10000") as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            if connection.execute(
                "SELECT to_regclass('ingest.publication_poll_receipt')"
            ).fetchone()["to_regclass"] is None:
                parser.error("M0 receipt table is missing in the selected database")
            frame = connection.execute(
                """SELECT p.id, p.primary_account_id, p.published_at,
                          a.platform::text AS platform
                     FROM ingest.publication AS p
                     JOIN catalog.platform_account AS a
                       ON a.id = p.primary_account_id
                    WHERE p.primary_account_id = ANY(%s::uuid[])
                      AND p.published_at >= %s AND p.published_at < %s
                    ORDER BY p.published_at, p.id""",
                (list(accounts), start, end),
            ).fetchall()
            if len(frame) > 10_000:
                parser.error("cohort exceeds the 10,000-post local audit bound")
            ids = [row["id"] for row in frame]
            receipt_rows = connection.execute(
                """SELECT r.publication_id, p.primary_account_id,
                          r.observed_at, r.views_count,
                          r.views_quality::text AS views_quality,
                          r.interval_uncertain
                     FROM ingest.publication_poll_receipt AS r
                     JOIN ingest.publication AS p ON p.id = r.publication_id
                    WHERE r.publication_id = ANY(%s::uuid[])
                      AND r.observed_at <= %s
                    ORDER BY r.publication_id, r.observed_at""",
                (ids, through),
            ).fetchall() if ids else []
    posts = tuple(PublishedPost(row["id"], row["primary_account_id"],
                                row["published_at"]) for row in frame)
    reads = tuple(SuccessfulRead(row["publication_id"], row["primary_account_id"],
                                 row["observed_at"], row["views_count"],
                                 row["views_quality"], row["interval_uncertain"])
                  for row in receipt_rows)
    platforms = {row["primary_account_id"]: row["platform"] for row in frame}
    rows = audit_cohort_coverage(
        posts, reads, platforms, accounts,
        EARLY_CHECKPOINTS if args.horizon == "early" else LATE_CHECKPOINTS,
        cohort_start=start, cohort_end=end, observed_through=through,
        max_gap_by_platform=gaps, source="successful_poll_receipts",
    )
    summary: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        summary[row.platform][row.status] += 1
    output = {
        "kind": "prospective_m0_readiness_not_anomaly_accuracy",
        "horizon": args.horizon,
        "publication_window_utc": [start.isoformat(), end.isoformat()],
        "observed_through_utc": through.isoformat(),
        "eligible_posts": len(rows),
        "successful_reads": len(reads),
        "by_platform": {platform: dict(sorted(counts.items()))
                        for platform, counts in sorted(summary.items())},
        "posts": [
            {"publication_id": str(row.publication_id),
             "platform": row.platform, "status": row.status,
             "checkpoints": {check.name: check.status for check in row.checkpoints}}
            for row in rows
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
