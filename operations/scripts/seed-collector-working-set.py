#!/usr/bin/env python3
"""Seed bounded collector state without deleting canonical history.

Run with the collector host's operator DSN in COLLECTOR_DATABASE_URL. Each
publication page commits independently. The capture trigger mirrors concurrent
old-writer inserts; a restart can resume the seed safely. The ready marker is
written only after the last page and account state have committed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import psycopg
from collector_target.working_set import prune


def seed(connection, *, batch_size: int = 200) -> tuple[int, int]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("seed batch size must be between 1 and 1000")
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout='1s'")
        connection.execute("INSERT INTO ops_and_admin.collector_working_set_seed(singleton) VALUES(true) ON CONFLICT DO NOTHING")
    cursor = None
    while True:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='20s'")
            connection.execute("SET LOCAL lock_timeout='1s'")
            rows = connection.execute(
                """SELECT id FROM ingest.publication
                    WHERE %s::uuid IS NULL OR id>%s ORDER BY id LIMIT %s""",
                (cursor, cursor, batch_size),
            ).fetchall()
            if not rows:
                break
            ids = [row[0] for row in rows]
            connection.execute(
                """INSERT INTO ingest.collector_publication_working_set AS current (
                       publication_id,published_month,sampling_bucket,observed_at,
                       collected_at,synthetic,views_count,reactions_count,comments_count,
                       shares_count,source_fingerprint,semantic_fingerprint
                   )
                   SELECT s.publication_id,s.published_month,s.sampling_bucket,
                          s.observed_at,s.collected_at,s.synthetic,s.views_count,
                          s.reactions_count,s.comments_count,s.shares_count,
                          s.source_fingerprint,s.semantic_fingerprint
                     FROM ingest.publication p CROSS JOIN LATERAL (
                         SELECT * FROM ingest.publication_metric_snapshot_active s
                          WHERE s.publication_id=p.id
                            AND s.published_month=date_trunc('month',p.published_at)::date
                            AND s.observed_at>=transaction_timestamp()-interval '31 days'
                          ORDER BY s.observed_at DESC,s.id DESC LIMIT 24
                     ) s WHERE p.id=ANY(%s::uuid[])
                   ON CONFLICT (publication_id,sampling_bucket) DO UPDATE SET
                       id=DEFAULT,published_month=excluded.published_month,
                       observed_at=excluded.observed_at,
                       collected_at=excluded.collected_at,synthetic=excluded.synthetic,
                       views_count=excluded.views_count,reactions_count=excluded.reactions_count,
                       comments_count=excluded.comments_count,shares_count=excluded.shares_count,
                       source_fingerprint=excluded.source_fingerprint,
                       semantic_fingerprint=excluded.semantic_fingerprint
                   WHERE (excluded.observed_at,excluded.collected_at)
                             >= (current.observed_at,current.collected_at)
                     AND excluded.source_fingerprint IS DISTINCT FROM current.source_fingerprint""",
                (ids,),
            )
            prune(connection, ids)
            cursor = ids[-1]
        print("seed page committed publications=" + str(len(ids)), flush=True)
    with connection.transaction():
        connection.execute("SET LOCAL statement_timeout='20s'")
        connection.execute("SET LOCAL lock_timeout='1s'")
        connection.execute(
            """INSERT INTO ingest.collector_account_working_set AS current (
                   platform_account_id,observed_at,source_fingerprint,semantic_fingerprint
               ) SELECT DISTINCT ON (platform_account_id)
                        platform_account_id,observed_at,source_fingerprint,semantic_fingerprint
                   FROM ingest.account_metric_snapshot_active
                  WHERE observed_at>=transaction_timestamp()-interval '31 days'
                  ORDER BY platform_account_id,observed_at DESC,id DESC
               ON CONFLICT (platform_account_id) DO UPDATE SET
                   observed_at=excluded.observed_at,source_fingerprint=excluded.source_fingerprint,
                   semantic_fingerprint=excluded.semantic_fingerprint
               WHERE excluded.observed_at>=current.observed_at""",
        )
        counts = connection.execute(
            """SELECT (SELECT count(*) FROM ingest.collector_publication_working_set),
                      (SELECT count(*) FROM ingest.collector_account_working_set)""",
        ).fetchone()
        connection.execute(
            """UPDATE ops_and_admin.collector_working_set_seed SET completed_at=clock_timestamp(),
                      publication_rows=%s,account_rows=%s WHERE singleton""", counts,
        )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required; this command only seeds state and never deletes history")
    with psycopg.connect(os.environ["COLLECTOR_DATABASE_URL"], autocommit=True) as connection:
        print("seed complete publication_rows=%s account_rows=%s" % seed(connection, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
