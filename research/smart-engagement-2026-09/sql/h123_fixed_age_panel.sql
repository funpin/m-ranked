-- Exploratory per-post panel for H1-H3, not a training or validation set.
-- 12 deterministic accounts/platform from h123_account_frame.sql; all their
-- posts in two mature weeks. Detailed output stays temporary, only aggregates
-- are committed to the research folder.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '90s';

WITH account_counts AS (
  SELECT a.platform, p.primary_account_id, count(*) AS post_count
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-08-29 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
  GROUP BY a.platform, p.primary_account_id
  HAVING count(*) BETWEEN 8 AND 80
), selected_accounts AS (
  SELECT platform, primary_account_id,
         row_number() OVER (
           PARTITION BY platform ORDER BY md5(primary_account_id::text)
         ) AS account_rank
  FROM account_counts
), selected_posts AS (
  SELECT p.id, p.primary_account_id, a.institution_id, a.platform,
         p.published_at, p.publication_type, p.is_repost,
         p.history_completeness, s.account_rank
  FROM ingest.publication AS p
  JOIN selected_accounts AS s ON s.primary_account_id = p.primary_account_id
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE s.account_rank <= 12
    AND p.published_at >= TIMESTAMPTZ '2026-08-29 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT p.platform, p.account_rank, p.primary_account_id, p.institution_id,
       p.id AS publication_id, p.published_at, p.publication_type,
       p.is_repost, p.history_completeness,
       early.age_seconds AS age_24h, early.views_count AS v24,
       early.reactions_count AS r24,
       early.views_quality AS vq24,
       early.reactions_quality AS rq24,
       early.interval_uncertain AS uncertain24,
       late.age_seconds AS age_14d, late.views_count AS v14,
       late.reactions_count AS r14,
       late.views_quality AS vq14,
       late.reactions_quality AS rq14,
       late.interval_uncertain AS uncertain14
FROM selected_posts AS p
LEFT JOIN LATERAL (
  SELECT q.* FROM (
    SELECT DISTINCT ON (raw.sampling_bucket)
           raw.observed_at, raw.age_seconds, raw.views_count,
           raw.reactions_count, raw.views_quality,
           raw.reactions_quality, raw.interval_uncertain
    FROM ingest.publication_metric_snapshot AS raw
    WHERE raw.publication_id = p.id
      AND raw.published_month = date_trunc('month', p.published_at)::date
      AND raw.age_seconds BETWEEN 64800 AND 86400
      AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
      AND NOT raw.synthetic
    ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
  ) AS q
  ORDER BY q.observed_at DESC
  LIMIT 1
) AS early ON true
LEFT JOIN LATERAL (
  SELECT q.* FROM (
    SELECT DISTINCT ON (raw.sampling_bucket)
           raw.observed_at, raw.age_seconds, raw.views_count,
           raw.reactions_count, raw.views_quality,
           raw.reactions_quality, raw.interval_uncertain
    FROM ingest.publication_metric_snapshot AS raw
    WHERE raw.publication_id = p.id
      AND raw.published_month = date_trunc('month', p.published_at)::date
      AND raw.age_seconds BETWEEN 1123200 AND 1209600
      AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
      AND NOT raw.synthetic
    ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
  ) AS q
  ORDER BY q.observed_at DESC
  LIMIT 1
) AS late ON true
ORDER BY p.platform, p.account_rank, p.published_at, p.id;

COMMIT;
