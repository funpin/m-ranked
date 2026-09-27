-- Execute on a local/test DB after an opt-in collection period.
-- No receipt outside the cohort, and no receipt in a failed read, is a zero.
-- The opt-in eligible-post denominator is not yet persisted. These are counts
-- of observed reads and pairs, NOT percentages of collection coverage.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';

SELECT pg_size_pretty(pg_relation_size('ingest.publication_poll_receipt')) AS heap,
       pg_size_pretty(pg_indexes_size('ingest.publication_poll_receipt')) AS indexes,
       pg_size_pretty(pg_total_relation_size('ingest.publication_poll_receipt')) AS total,
       count(*) AS receipts,
       min(observed_at) AS first_read,
       max(observed_at) AS last_read
FROM ingest.publication_poll_receipt;

WITH platforms(platform) AS (
    VALUES ('telegram'), ('vk'), ('max'), ('rutube')
), reads AS (
    SELECT account.platform::text AS platform,
           publication.primary_account_id,
           receipt.publication_id,
           receipt.observed_at,
           receipt.views_count,
           receipt.views_quality,
           receipt.interval_uncertain,
           receipt.snapshot_written,
           lag(receipt.observed_at) OVER position AS prior_at,
           lag(receipt.views_count) OVER position AS prior_views,
           lag(receipt.views_quality) OVER position AS prior_quality,
           lag(receipt.interval_uncertain) OVER position AS prior_uncertain
    FROM ingest.publication_poll_receipt AS receipt
    JOIN ingest.publication AS publication ON publication.id = receipt.publication_id
    JOIN catalog.platform_account AS account ON account.id = publication.primary_account_id
    WINDOW position AS (
        PARTITION BY receipt.publication_id ORDER BY receipt.observed_at, receipt.observed_bucket
    )
), counted AS (
SELECT platform,
       count(*) AS successful_reads,
       count(DISTINCT primary_account_id) AS accounts,
       count(DISTINCT publication_id) AS posts,
       count(*) FILTER (WHERE NOT snapshot_written) AS unchanged_reads_not_in_snapshot_stream,
       count(*) FILTER (WHERE prior_at IS NOT NULL) AS successive_read_pairs,
       count(*) FILTER (
           WHERE prior_at IS NOT NULL
             AND views_quality = 'exact'
             AND prior_quality = 'exact'
             AND NOT interval_uncertain AND NOT prior_uncertain
             AND views_count = prior_views
       ) AS exact_zero_net_counter_pairs
FROM reads
GROUP BY platform
)
SELECT p.platform,
       coalesce(c.successful_reads, 0) AS successful_reads,
       coalesce(c.accounts, 0) AS accounts,
       coalesce(c.posts, 0) AS posts,
       coalesce(c.unchanged_reads_not_in_snapshot_stream, 0) AS unchanged_reads_not_in_snapshot_stream,
       coalesce(c.successive_read_pairs, 0) AS successive_read_pairs,
       coalesce(c.exact_zero_net_counter_pairs, 0) AS exact_zero_net_counter_pairs
FROM platforms AS p
LEFT JOIN counted AS c USING (platform)
ORDER BY p.platform;

ROLLBACK;
