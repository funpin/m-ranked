-- Deterministic read-only Telegram channel frame for exploratory neighbor-post
-- event study. MIPT is excluded from the sample and added as a case separately.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH eligible AS (
  SELECT p.primary_account_id, count(*) AS posts_in_week
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE a.platform = 'telegram'
    AND p.primary_account_id <> 'bd9c960e-1a76-5a72-a6a0-5a301e8e390a'
    AND p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND p.deleted_at IS NULL
  GROUP BY p.primary_account_id
  HAVING count(*) BETWEEN 8 AND 40
), ranked AS (
  SELECT primary_account_id, posts_in_week,
         row_number() OVER (ORDER BY md5(primary_account_id::text)) AS hash_rank,
         count(*) OVER () AS eligible_accounts
  FROM eligible
)
SELECT primary_account_id, posts_in_week, hash_rank, eligible_accounts
FROM ranked
WHERE hash_rank <= 12
ORDER BY hash_rank;

COMMIT;
