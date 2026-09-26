-- Read-only, bounded active-snapshot extraction for the first 20 pilot-frame
-- publications per platform. DISTINCT ON is scoped to each publication so
-- corrected rows do not enter the time series twice.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '45s';

WITH ranked AS (
  SELECT p.id AS publication_id,
         a.platform,
         p.primary_account_id,
         p.published_at,
         p.publication_type,
         p.is_repost,
         p.history_completeness,
         p.first_observation_age_seconds,
         row_number() OVER (
           PARTITION BY a.platform ORDER BY md5(p.id::text)
         ) AS sample_rank
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), selected AS (
  SELECT * FROM ranked WHERE sample_rank <= 20
)
SELECT p.platform, p.publication_id, p.primary_account_id, p.published_at,
       p.publication_type, p.is_repost, p.history_completeness,
       p.first_observation_age_seconds, p.sample_rank,
       s.observed_at, s.age_seconds, s.sampling_bucket,
       s.views_count, s.reactions_count, s.comments_count, s.shares_count,
       s.quality, s.views_quality, s.reactions_quality,
       s.comments_quality, s.shares_quality,
       s.interval_uncertain, s.synthetic, s.correction_sequence
FROM selected AS p
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.sampling_bucket,
         raw.views_count, raw.reactions_count,
         raw.comments_count, raw.shares_count,
         raw.quality, raw.views_quality, raw.reactions_quality,
         raw.comments_quality, raw.shares_quality,
         raw.interval_uncertain, raw.synthetic, raw.correction_sequence
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.publication_id
    AND raw.published_month = DATE '2026-09-01'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.platform, p.sample_rank, s.observed_at;

COMMIT;
