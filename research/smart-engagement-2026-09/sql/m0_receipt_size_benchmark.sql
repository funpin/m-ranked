-- Local offline PostgreSQL only. Temporary table, 256 posts x 40 reads.
-- Measures heap + both indexes; excludes WAL, vacuum churn, FK checks and transfer.
BEGIN;
SET LOCAL statement_timeout = '20s';
CREATE TEMP TABLE receipt_size_bench
  (LIKE ingest.publication_poll_receipt INCLUDING ALL) ON COMMIT DROP;

INSERT INTO receipt_size_bench (
    publication_id, cadence_seconds, observed_bucket, observed_at,
    collection_run_id, views_count, reactions_count, comments_count,
    shares_count, views_quality, reactions_quality, comments_quality,
    shares_quality, interval_uncertain, snapshot_written
)
SELECT publication.id, 900, tick.n,
       TIMESTAMPTZ '2026-09-01 00:00:00+00' + tick.n * INTERVAL '15 minutes',
       run.id, 1000 + tick.n, 12 + tick.n / 100, NULL, NULL,
       'exact'::ingest.observation_quality,
       'exact'::ingest.observation_quality,
       'unknown'::ingest.observation_quality,
       'unknown'::ingest.observation_quality,
       false, false
FROM (SELECT id FROM ingest.publication ORDER BY id LIMIT 256) AS publication
CROSS JOIN (SELECT id FROM ingest.collection_run LIMIT 1) AS run
CROSS JOIN generate_series(0, 39) AS tick(n);

SELECT count(*) AS rows,
       pg_relation_size('receipt_size_bench'::regclass) AS heap_bytes,
       pg_indexes_size('receipt_size_bench'::regclass) AS index_bytes,
       pg_total_relation_size('receipt_size_bench'::regclass) AS total_bytes,
       round(pg_total_relation_size('receipt_size_bench'::regclass)::numeric
             / nullif(count(*), 0), 1) AS allocated_bytes_per_row
FROM receipt_size_bench;

ROLLBACK;
