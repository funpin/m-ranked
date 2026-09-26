-- Read-only, deterministic pilot frame. The dates fix a 14-day follow-up
-- window within the snapshot history available on 2026-09-26. Completeness
-- is retained as a stratum, not used to select away data-quality failures.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH ranked AS (
  SELECT p.id AS publication_id,
         a.platform,
         p.primary_account_id,
         p.published_at,
         p.publication_type,
         p.is_repost,
         p.history_completeness,
         row_number() OVER (
           PARTITION BY a.platform ORDER BY md5(p.id::text)
         ) AS sample_rank
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT platform, publication_id, primary_account_id, published_at,
       publication_type, is_repost, history_completeness, sample_rank
FROM ranked
WHERE sample_rank <= 80
ORDER BY platform, sample_rank;

COMMIT;
