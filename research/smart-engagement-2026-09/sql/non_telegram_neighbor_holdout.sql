-- Account-disjoint follow-up of the 26 September feasibility pilot.
-- Same calendar window and filters; deterministic hash ranks 5..16 instead of 1..4.
-- The output contains identifiers: keep it in a temporary local file only.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '120s';

WITH eligible AS (
  SELECT a.platform, p.primary_account_id, count(*) AS post_count
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE a.platform IN ('vk', 'max', 'rutube')
    AND p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND p.deleted_at IS NULL
  GROUP BY a.platform, p.primary_account_id
  HAVING count(*) BETWEEN 8 AND 40
), ranked AS (
  SELECT platform, primary_account_id,
         row_number() OVER (PARTITION BY platform ORDER BY md5(primary_account_id::text)) AS account_rank
  FROM eligible
), selected_posts AS (
  SELECT p.id AS publication_id, p.primary_account_id, r.platform,
         p.published_at,
         row_number() OVER (
           PARTITION BY p.primary_account_id ORDER BY p.published_at, p.id
         ) AS posting_order
  FROM ingest.publication AS p
  JOIN ranked AS r ON r.primary_account_id = p.primary_account_id
  WHERE r.account_rank BETWEEN 5 AND 16
    AND p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT p.platform, p.publication_id, p.primary_account_id,
       p.published_at, p.posting_order,
       s.observed_at, s.age_seconds, s.views_count,
       s.views_quality, s.interval_uncertain, s.synthetic
FROM selected_posts AS p
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.views_count,
         raw.views_quality, raw.interval_uncertain, raw.synthetic
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.publication_id
    AND raw.published_month = DATE '2026-09-01'
    AND raw.observed_at >= TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND raw.observed_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.platform, p.primary_account_id, p.posting_order, s.observed_at;

COMMIT;
