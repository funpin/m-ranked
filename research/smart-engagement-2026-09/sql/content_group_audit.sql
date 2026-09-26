-- Week-bounded read-only feasibility check for cross-platform H9.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH base AS (
  SELECT p.id, p.content_group_id, a.platform
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), group_sizes AS (
  SELECT content_group_id, count(*) AS publications,
         count(DISTINCT platform) AS platform_count
  FROM base
  WHERE content_group_id IS NOT NULL
  GROUP BY content_group_id
)
SELECT b.platform, count(*) AS publications,
       count(*) FILTER (WHERE b.content_group_id IS NOT NULL) AS with_group,
       count(*) FILTER (WHERE g.platform_count > 1) AS in_cross_platform_group,
       count(*) FILTER (WHERE g.publications > 1) AS in_multi_publication_group
FROM base AS b
LEFT JOIN group_sizes AS g ON g.content_group_id = b.content_group_id
GROUP BY b.platform
ORDER BY b.platform;

COMMIT;
