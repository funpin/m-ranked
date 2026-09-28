-- Read-only, fixed before outcome inspection; retrospective convenience panel.
-- No labels or production anomaly state are used in selection.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '120s';
SET LOCAL TIME ZONE 'UTC';
COPY (
WITH account_frame AS (
 SELECT a.platform::text AS platform, p.primary_account_id AS account_id, count(*) AS n,
        row_number() OVER (PARTITION BY a.platform ORDER BY md5(p.primary_account_id::text)) AS rank
 FROM ingest.publication p JOIN catalog.platform_account a ON a.id=p.primary_account_id
 WHERE p.published_at >= '2026-08-24'::timestamptz AND p.published_at < '2026-09-20'::timestamptz
 AND p.deleted_at IS NULL AND NOT p.is_repost
 GROUP BY a.platform,p.primary_account_id HAVING count(*) BETWEEN 10 AND 250
), posts AS (
 SELECT p.id,p.primary_account_id,p.published_at,p.publication_type,p.history_completeness,
        a.platform,a.rank
 FROM ingest.publication p JOIN account_frame a ON a.account_id=p.primary_account_id
 WHERE a.rank<=24 AND p.published_at >= '2026-08-24'::timestamptz
 AND p.published_at < '2026-09-25'::timestamptz AND p.deleted_at IS NULL AND NOT p.is_repost
)
SELECT to_jsonb(x) FROM (
 SELECT p.*,length(c.archived_text) AS text_length,
  (SELECT json_agg(z ORDER BY z.age_seconds) FROM (
    SELECT DISTINCT ON (s.sampling_bucket) s.observed_at,s.age_seconds,
     s.views_count AS v,s.reactions_count AS r,s.comments_count AS c,s.shares_count AS s,
     s.views_quality::text AS vq,s.reactions_quality::text AS rq,s.interval_uncertain AS uncertain
    FROM ingest.publication_metric_snapshot s
    WHERE s.publication_id=p.id AND s.published_month=date_trunc('month',p.published_at)::date
    AND s.age_seconds BETWEEN 0 AND 604800 AND NOT s.synthetic
    AND s.created_at < '2026-09-27 17:00:00+00'::timestamptz
    ORDER BY s.sampling_bucket,s.correction_sequence DESC
   ) z) AS points
 FROM posts p LEFT JOIN analytics.publication_content c ON c.publication_id=p.id
) x
) TO STDOUT;
COMMIT;
