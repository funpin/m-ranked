-- Read-only feasibility of within-university, cross-platform comparisons.
-- A near-time pair is only a candidate; it is not a verified same event.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH per_institution AS (
  SELECT institution_id, count(DISTINCT platform) AS platform_count
  FROM catalog.platform_account
  WHERE enabled AND deleted_at IS NULL
  GROUP BY institution_id
)
SELECT 'enabled_account_overlap' AS section,
       platform_count::text AS stratum,
       count(*)::text AS n
FROM per_institution
GROUP BY platform_count
ORDER BY platform_count;

WITH posts AS (
  SELECT p.id, a.institution_id, a.platform, p.published_at
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), coverage AS (
  SELECT institution_id, count(DISTINCT platform) AS active_post_platforms
  FROM posts GROUP BY institution_id
)
SELECT 'week_post_overlap' AS section,
       active_post_platforms::text AS stratum,
       count(*)::text AS n
FROM coverage GROUP BY active_post_platforms
ORDER BY active_post_platforms;

WITH posts AS (
  SELECT p.id, a.institution_id, a.platform, p.published_at
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), pairs AS (
  SELECT least(x.platform::text, y.platform::text) AS platform_a,
         greatest(x.platform::text, y.platform::text) AS platform_b,
         x.institution_id
  FROM posts AS x
  JOIN posts AS y ON y.institution_id = x.institution_id
                 AND y.platform <> x.platform
                 AND y.published_at BETWEEN x.published_at - INTERVAL '3 hours'
                                        AND x.published_at + INTERVAL '3 hours'
                 AND x.id < y.id
)
SELECT 'near_time_3h' AS section,
       platform_a || '+' || platform_b AS stratum,
       count(*)::text || ' pairs; ' || count(DISTINCT institution_id)::text || ' institutions' AS n
FROM pairs GROUP BY platform_a, platform_b ORDER BY platform_a, platform_b;

SELECT 'archived_content' AS section, 'all' AS stratum,
       count(*)::text || ' rows; ' ||
       count(*) FILTER (WHERE archived_text IS NOT NULL AND btrim(archived_text) <> '')::text ||
       ' nonempty text' AS n
FROM analytics.publication_content;

COMMIT;
