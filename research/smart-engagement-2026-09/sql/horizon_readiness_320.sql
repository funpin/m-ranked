-- Exploratory M0 coverage only: fixed 80-post hash frame per platform, 05-11
-- September 2026. The 24/72h and 7/14d windows are candidate horizons, not
-- production sufficiency thresholds. Query local partitions post by post.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '90s';

WITH ranked AS (
  SELECT p.id, a.platform, p.history_completeness,
         row_number() OVER (
           PARTITION BY a.platform ORDER BY md5(p.id::text)
         ) AS sample_rank
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), selected AS (
  SELECT * FROM ranked WHERE sample_rank <= 80
), post_coverage AS (
  SELECT p.platform, p.history_completeness,
         s.real_points, s.first_real_age,
         s.first_usable_both_age,
         s.v24, s.r24, s.both24,
         s.v72, s.r72, s.both72,
         s.v7d, s.r7d, s.both7d,
         s.v14d, s.r14d, s.both14d
  FROM selected AS p
  CROSS JOIN LATERAL (
    SELECT count(*) FILTER (WHERE NOT q.synthetic) AS real_points,
           min(q.age_seconds) FILTER (WHERE NOT q.synthetic) AS first_real_age,
           min(q.age_seconds) FILTER (
             WHERE NOT q.synthetic AND NOT q.interval_uncertain
               AND q.views_count IS NOT NULL AND q.reactions_count IS NOT NULL
               AND q.views_quality IN ('exact', 'rounded')
               AND q.reactions_quality IN ('exact', 'rounded')
           ) AS first_usable_both_age,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 64800 AND 86400
             AND q.views_count IS NOT NULL AND q.views_quality IN ('exact', 'rounded')) AS v24,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 64800 AND 86400
             AND q.reactions_count IS NOT NULL AND q.reactions_quality IN ('exact', 'rounded')) AS r24,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 64800 AND 86400
             AND q.views_count IS NOT NULL AND q.reactions_count IS NOT NULL
             AND q.views_quality IN ('exact', 'rounded')
             AND q.reactions_quality IN ('exact', 'rounded')) AS both24,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 216000 AND 259200
             AND q.views_count IS NOT NULL AND q.views_quality IN ('exact', 'rounded')) AS v72,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 216000 AND 259200
             AND q.reactions_count IS NOT NULL AND q.reactions_quality IN ('exact', 'rounded')) AS r72,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 216000 AND 259200
             AND q.views_count IS NOT NULL AND q.reactions_count IS NOT NULL
             AND q.views_quality IN ('exact', 'rounded')
             AND q.reactions_quality IN ('exact', 'rounded')) AS both72,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 518400 AND 604800
             AND q.views_count IS NOT NULL AND q.views_quality IN ('exact', 'rounded')) AS v7d,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 518400 AND 604800
             AND q.reactions_count IS NOT NULL AND q.reactions_quality IN ('exact', 'rounded')) AS r7d,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 518400 AND 604800
             AND q.views_count IS NOT NULL AND q.reactions_count IS NOT NULL
             AND q.views_quality IN ('exact', 'rounded')
             AND q.reactions_quality IN ('exact', 'rounded')) AS both7d,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 1123200 AND 1209600
             AND q.views_count IS NOT NULL AND q.views_quality IN ('exact', 'rounded')) AS v14d,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 1123200 AND 1209600
             AND q.reactions_count IS NOT NULL AND q.reactions_quality IN ('exact', 'rounded')) AS r14d,
           count(*) FILTER (WHERE NOT q.synthetic AND NOT q.interval_uncertain
             AND q.age_seconds BETWEEN 1123200 AND 1209600
             AND q.views_count IS NOT NULL AND q.reactions_count IS NOT NULL
             AND q.views_quality IN ('exact', 'rounded')
             AND q.reactions_quality IN ('exact', 'rounded')) AS both14d
    FROM (
      SELECT DISTINCT ON (raw.sampling_bucket)
             raw.age_seconds, raw.synthetic, raw.interval_uncertain,
             raw.views_count, raw.reactions_count,
             raw.views_quality, raw.reactions_quality
      FROM ingest.publication_metric_snapshot AS raw
      WHERE raw.publication_id = p.id
        AND raw.published_month = DATE '2026-09-01'
        AND raw.observed_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
        AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
      ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
    ) AS q
  ) AS s
)
SELECT platform, count(*) AS sampled_posts,
       count(*) FILTER (WHERE real_points = 0) AS no_real_points,
       count(*) FILTER (WHERE first_real_age <= 21600) AS first_real_by_6h,
       count(*) FILTER (WHERE first_real_age <= 86400) AS first_real_by_24h,
       count(*) FILTER (WHERE first_usable_both_age <= 21600) AS first_usable_both_by_6h,
       count(*) FILTER (WHERE history_completeness = 'complete') AS marked_complete,
       count(*) FILTER (WHERE v24 > 0) AS v24_available,
       count(*) FILTER (WHERE r24 > 0) AS r24_available,
       count(*) FILTER (WHERE both24 > 0) AS both24_available,
       count(*) FILTER (WHERE v72 > 0) AS v72_available,
       count(*) FILTER (WHERE r72 > 0) AS r72_available,
       count(*) FILTER (WHERE both72 > 0) AS both72_available,
       count(*) FILTER (WHERE v7d > 0) AS v7d_available,
       count(*) FILTER (WHERE r7d > 0) AS r7d_available,
       count(*) FILTER (WHERE both7d > 0) AS both7d_available,
       count(*) FILTER (WHERE v14d > 0) AS v14d_available,
       count(*) FILTER (WHERE r14d > 0) AS r14d_available,
       count(*) FILTER (WHERE both14d > 0) AS both14d_available
FROM post_coverage
GROUP BY platform
ORDER BY platform;

COMMIT;
