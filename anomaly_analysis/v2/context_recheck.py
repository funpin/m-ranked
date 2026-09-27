"""Bounded, repeatable contextual recheck of saved strong late-view signals.

Run as the analytics_worker database role, after migration 0044. A dry run is
the default. Each post is read and (with --apply) written in one repeatable-read
transaction, so the window, neighbor histories and source verdict are coherent.
This is a separate pass over saved v2 results; the original detector and its
signals remain untouched. No network or live collector access is required.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta
from statistics import median
from uuid import UUID

from .context_cap import VERSION, WindowEvidence, assess_context_cap


MAX_LATER_POSTS = 200
BOUNDARY_TOLERANCE = timedelta(hours=2)
TRUSTED_QUALITY = {"exact", "rounded"}

SOURCE = """
SELECT state.publication_id, state.level, state.signals, state.analyzed_at,
       state.review_status,
       publication.primary_account_id, publication.published_at,
       account.platform::text AS platform
  FROM analytics.post_anomaly_state state
  JOIN ingest.visible_publication publication ON publication.id=state.publication_id
  JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
 WHERE state.publication_id=%s AND state.analyzed_at IS NOT NULL
"""

CANDIDATES = """
SELECT state.publication_id
  FROM analytics.post_anomaly_state state
  JOIN ingest.visible_publication publication ON publication.id=state.publication_id
  JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
 WHERE state.level=2 AND state.analyzed_at IS NOT NULL
   AND account.platform::text IN ('telegram','max')
 ORDER BY state.analyzed_at DESC, state.publication_id
 LIMIT %s
"""

BEFORE = """
SELECT id, published_at FROM ingest.visible_publication
 WHERE primary_account_id=%s AND deleted_at IS NULL
   AND (published_at,id)<(%s,%s)
 ORDER BY published_at DESC,id DESC LIMIT 2
"""

AFTER = """
SELECT id, published_at FROM ingest.visible_publication
 WHERE primary_account_id=%s AND deleted_at IS NULL
   AND (published_at,id)>(%s,%s) AND published_at<=%s
 ORDER BY published_at,id LIMIT %s
"""

BOUNDARY = """
SELECT observed_at,views_count,views_quality::text AS quality
  FROM ingest.publication_metric_snapshot_active
 WHERE publication_id=%s AND published_month=%s AND NOT synthetic
   AND NOT interval_uncertain AND views_count IS NOT NULL
   AND views_quality::text IN ('exact','rounded')
   AND observed_at {comparison} %s
 ORDER BY observed_at {direction},correction_sequence DESC LIMIT 1
"""

NEW_POST_VIEW = """
SELECT views_count FROM ingest.publication_metric_snapshot_active
 WHERE publication_id=%s AND published_month=%s AND NOT synthetic
   AND NOT interval_uncertain AND views_count>0
   AND views_quality::text IN ('exact','rounded')
   AND observed_at >= %s AND observed_at <= %s
 ORDER BY observed_at,correction_sequence DESC LIMIT 1
"""

UPSERT = """
INSERT INTO analytics.post_anomaly_context_recheck
  (publication_id,source_analyzed_at,source_level,effective_level,method_version,reason,evidence)
VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
ON CONFLICT (publication_id) DO UPDATE SET
 source_analyzed_at=excluded.source_analyzed_at,
 source_level=excluded.source_level,
 effective_level=excluded.effective_level,
 method_version=excluded.method_version,
 reason=excluded.reason,
 evidence=excluded.evidence,
 reviewed_at=transaction_timestamp()
"""

DELETE_STALE = """
DELETE FROM analytics.post_anomaly_context_recheck
 WHERE publication_id=%s AND source_analyzed_at=%s AND source_level=%s
"""


def _measurement(cursor, post: dict, start: datetime, end: datetime) -> tuple[int, int] | None:
    month = post["published_at"].date().replace(day=1)
    publication_id = post.get("id", post.get("publication_id"))
    cursor.execute(BOUNDARY.format(comparison="<=", direction="DESC"),
                   (publication_id, month, start))
    before = cursor.fetchone()
    cursor.execute(BOUNDARY.format(comparison=">=", direction="ASC"),
                   (publication_id, month, end))
    after = cursor.fetchone()
    if (before is None or after is None
            or start - before["observed_at"] > BOUNDARY_TOLERANCE
            or after["observed_at"] - end > BOUNDARY_TOLERANCE
            or after["views_count"] < before["views_count"]):
        return None
    return before["views_count"], after["views_count"]


def _window(cursor, source: dict, signal: dict, old_posts: list[tuple[dict, int]],
            later_posts: list[dict]) -> tuple[WindowEvidence, dict]:
    start = datetime.fromisoformat(signal["startAt"])
    end = datetime.fromisoformat(signal["endAt"])
    target = _measurement(cursor, source, start, end)
    # The signal's start is a polling boundary, not publication time. A post
    # within the previous poll interval can still be a contextual event.
    tolerance = min(3600, max(900, int(signal.get("scaleSeconds") or 0)))
    events = [(post, distance) for distance, post in enumerate(later_posts, start=1)
              if start - timedelta(seconds=tolerance) <= post["published_at"] <= end]
    measured_new = 0
    for event, _distance in events[:6]:
        month = event["published_at"].date().replace(day=1)
        cursor.execute(NEW_POST_VIEW, (event["id"], month, event["published_at"],
                                       end + BOUNDARY_TOLERANCE))
        measured_new += cursor.fetchone() is not None
    old = [(post, distance) for post, distance in old_posts if post["published_at"] < start]
    measurements = [(post, distance, value) for post, distance in old
                    if (value := _measurement(cursor, post, start, end)) is not None]
    growth = [math.log1p(after) - math.log1p(before)
              for _post, _distance, (before, after) in measurements]
    positive = sum(after > before for _post, _distance, (before, after) in measurements)
    median_growth = median(growth) if growth else None
    evidence = WindowEvidence(signal["startAt"], signal["endAt"], target is not None,
                              True, tuple(str(post["id"]) for post, _ in events),
                              measured_new, positive, len(measurements), median_growth,
                              min((distance for _, distance in events), default=None),
                              sum(abs(distance) <= 2 for _, distance, _ in measurements))
    detail = {
        "startAt": signal["startAt"], "endAt": signal["endAt"],
        "targetMeasured": target is not None,
        "newPublicationIds": list(evidence.new_publication_ids[:6]),
        "nearestNewPostFeedDistance": evidence.nearest_event_feed_distance,
        "measuredNewPosts": measured_new,
        "measuredOldPosts": len(measurements), "positiveOldPosts": positive,
        "oldPostFeedDistances": [distance for _post, distance, _value in measurements],
        "medianOldGrowthPercent": round(math.expm1(median_growth) * 100, 2)
        if median_growth is not None else None,
    }
    return evidence, detail


def recheck_one(connection, publication_id: UUID, *, apply: bool) -> dict:
    from psycopg.rows import dict_row

    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute(SOURCE, (publication_id,))
            source = cursor.fetchone()
            if source is None:
                return {"publicationId": str(publication_id), "status": "absent"}
            strong = [signal for signal in source["signals"]
                      if float(signal.get("strength", 0)) >= .7]
            if (source["level"] != 2 or source["platform"] not in ("telegram", "max")
                    or source["review_status"] != "unreviewed"
                    or not strong or any(signal.get("pattern") != 2 or signal.get("metric") != "views"
                                         for signal in strong)):
                return {"publicationId": str(publication_id), "status": "ineligible"}
            latest_end = max(datetime.fromisoformat(signal["endAt"]) for signal in strong)
            cursor.execute(BEFORE, (source["primary_account_id"], source["published_at"], publication_id))
            previous = list(reversed(cursor.fetchall()))
            cursor.execute(AFTER, (source["primary_account_id"], source["published_at"],
                                   publication_id, latest_end, MAX_LATER_POSTS + 1))
            later = cursor.fetchall()
            if len(later) > MAX_LATER_POSTS:
                return {"publicationId": str(publication_id), "status": "too_many_neighbors"}
            # Match control posts to the target's feed depth: at most two slots
            # on either side. A later post is an old control only if published
            # before this signal; event distance is still measured from target.
            old_posts = [(post, index - len(previous)) for index, post in enumerate(previous)]
            old_posts += [(post, index) for index, post in enumerate(later[:2], start=1)]
            windows, details = [], []
            for signal in strong:
                window, detail = _window(cursor, source, signal, old_posts, later)
                windows.append(window)
                details.append(detail)
            decision = assess_context_cap(source["platform"], source["level"],
                                          source["signals"], windows)
            result = {"publicationId": str(publication_id), "originalLevel": source["level"],
                      "effectiveLevel": decision.effective_level,
                      "status": "capped" if decision.reason else "abstained",
                      "windows": details}
            if apply and decision.reason:
                cursor.execute(UPSERT, (publication_id, source["analyzed_at"], source["level"],
                                        decision.effective_level, VERSION, decision.reason,
                                        json.dumps({"windows": details, "source": "same_transaction_history"})))
                cursor.execute("SELECT pg_notify('mranked_cache', %s)",
                               (json.dumps({"tags": ["analysis", "comparison"]}),))
            elif apply:
                cursor.execute(DELETE_STALE, (publication_id, source["analyzed_at"], source["level"]))
                if cursor.rowcount:
                    cursor.execute("SELECT pg_notify('mranked_cache', %s)",
                                   (json.dumps({"tags": ["analysis", "comparison"]}),))
            return result


def main() -> None:
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-id", type=UUID, action="append", default=[])
    parser.add_argument("--limit", type=int, default=0, help="bounded newest level-2 candidate scan")
    parser.add_argument("--apply", action="store_true", help="persist capped decisions")
    args = parser.parse_args()
    if not args.publication_id and not 1 <= args.limit <= 1000:
        parser.error("supply --publication-id or --limit 1..1000")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("ANOMALY_DATABASE_URL is required")
    with psycopg.connect(dsn) as connection:
        ids = args.publication_id
        if not ids:
            with connection.cursor() as cursor:
                cursor.execute(CANDIDATES, (args.limit,))
                ids = [row[0] for row in cursor.fetchall()]
            connection.commit()
        for publication_id in ids:
            try:
                result = recheck_one(connection, publication_id, apply=args.apply)
            except Exception:
                connection.rollback()
                raise
            print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
