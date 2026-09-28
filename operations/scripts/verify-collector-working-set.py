#!/usr/bin/env python3
"""Compare every tracked publication's recent state without a large temp sort."""
from __future__ import annotations

import os
import psycopg


QUERY = """WITH scope AS MATERIALIZED (
 SELECT id,published_at FROM ingest.publication WHERE id=ANY(%s::uuid[])
), expected AS MATERIALIZED (
 SELECT s.publication_id,s.published_month,s.sampling_bucket,s.observed_at,s.collected_at,
        s.synthetic,s.views_count,s.reactions_count,s.comments_count,s.shares_count,
        s.source_fingerprint,s.semantic_fingerprint
 FROM scope p CROSS JOIN LATERAL (
  SELECT * FROM ingest.publication_metric_snapshot_active s
   WHERE s.publication_id=p.id AND s.published_month=date_trunc('month',p.published_at)::date
     AND s.observed_at>=now()-interval '31 days'
   ORDER BY s.observed_at DESC,s.id DESC LIMIT 24
 ) s
), actual AS MATERIALIZED (
 SELECT s.publication_id,s.published_month,s.sampling_bucket,s.observed_at,s.collected_at,
        s.synthetic,s.views_count,s.reactions_count,s.comments_count,s.shares_count,
        s.source_fingerprint,s.semantic_fingerprint
 FROM scope p JOIN ingest.collector_publication_working_set s ON s.publication_id=p.id
 WHERE s.observed_at>=now()-interval '31 days'
   AND s.published_month=date_trunc('month',p.published_at)::date
), differences AS (
 (SELECT * FROM expected EXCEPT SELECT * FROM actual)
 UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)
)
SELECT (SELECT count(*) FROM expected),(SELECT count(*) FROM actual),count(*) FROM differences
"""


def verify(connection, *, batch_size: int = 100) -> tuple[int, int]:
    if not 1<=batch_size<=200:
        raise ValueError('verification page must be between 1 and 200')
    ids=[row[0] for row in connection.execute(
        "SELECT id FROM ingest.publication WHERE published_at>=now()-interval '30 days' AND deleted_at IS NULL ORDER BY id"
    ).fetchall()]
    compared=0
    for offset in range(0,len(ids),batch_size):
        with connection.transaction():
            connection.execute('SET TRANSACTION READ ONLY')
            connection.execute("SET LOCAL statement_timeout='10s'")
            connection.execute("SET LOCAL lock_timeout='1s'")
            connection.execute("SET LOCAL work_mem='8MB'")
            expected,actual,differences=connection.execute(QUERY,(ids[offset:offset+batch_size],)).fetchone()
            if differences or expected!=actual:
                raise RuntimeError('working state mismatch: page offset=%s differences=%s'%(offset,differences))
            compared+=expected
        if offset%(batch_size*25)==0:
            print('verified publications=%s rows=%s'%(min(offset+batch_size,len(ids)),compared),flush=True)
    return len(ids),compared


if __name__=='__main__':
    with psycopg.connect(os.environ['COLLECTOR_DATABASE_URL'],autocommit=True) as connection:
        print('verification complete publications=%s rows=%s'%verify(connection))
