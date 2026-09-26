-- Read-only count of neighboring Telegram publications for two previously
-- noticed late-reaction cases. This is exploratory and cannot give a p-value.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH candidates AS (
  SELECT p.primary_account_id, p.id AS candidate_id
  FROM ingest.publication AS p
  WHERE p.id IN (
    '5124e3e9-0af2-5e9d-8e47-a12219d014fa',
    '918ec5a0-0d52-51e9-83d8-aa48f745317a'
  )
)
SELECT c.candidate_id, c.primary_account_id,
       count(p.id) AS same_account_week_posts,
       count(p.id) FILTER (WHERE p.first_observation_age_seconds <= 86400)
         AS with_first_observation_under_24h
FROM candidates AS c
LEFT JOIN ingest.publication AS p
  ON p.primary_account_id = c.primary_account_id
 AND p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
 AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
 AND p.deleted_at IS NULL
GROUP BY c.candidate_id, c.primary_account_id
ORDER BY c.candidate_id;

COMMIT;
