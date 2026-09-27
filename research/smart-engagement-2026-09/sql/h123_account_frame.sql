-- Frozen candidate frame for within-account H1-H3 exploration. Two mature
-- publication weeks, account-level deterministic sampling, no clean labels.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH counts AS (
  SELECT a.platform, p.primary_account_id,
         count(*) AS post_count,
         count(*) FILTER (WHERE p.published_at < TIMESTAMPTZ '2026-09-05 00:00:00+00') AS week_a,
         count(*) FILTER (WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00') AS week_b
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-08-29 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
  GROUP BY a.platform, p.primary_account_id
  HAVING count(*) BETWEEN 8 AND 80
), ranked AS (
  SELECT *, row_number() OVER (
    PARTITION BY platform ORDER BY md5(primary_account_id::text)
  ) AS hash_rank,
  count(*) OVER (PARTITION BY platform) AS eligible_accounts
  FROM counts
)
SELECT platform, primary_account_id, post_count, week_a, week_b,
       hash_rank, eligible_accounts
FROM ranked
WHERE hash_rank <= 12
ORDER BY platform, hash_rank;

COMMIT;
