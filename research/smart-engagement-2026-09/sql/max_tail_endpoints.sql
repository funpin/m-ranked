-- psql parameter: -v account_id=<preselected UUID>. JSONL output with -qAt.
-- One preselected MAX account per query; never a full raw-history export.
BEGIN READ ONLY;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='2s';
SET LOCAL TIME ZONE 'UTC';
WITH posts AS (
 SELECT p.id,p.primary_account_id,p.published_at,p.publication_type,p.is_repost,
        p.history_completeness::text,
        (SELECT external_id FROM ingest.publication_identity i WHERE i.publication_id=p.id AND i.role='primary' ORDER BY id LIMIT 1) AS external_id
 FROM ingest.publication p
 WHERE p.primary_account_id=:'account_id'::uuid AND p.deleted_at IS NULL
   AND p.published_at>='2026-08-30 21:00+00' AND p.published_at<'2026-09-27 21:00+00'
)
SELECT jsonb_build_object('post',to_jsonb(p),'daily',d.points,'early24',e.point)
FROM posts p
LEFT JOIN LATERAL (
 SELECT jsonb_agg(to_jsonb(s) ORDER BY day) AS points FROM (
  SELECT DISTINCT ON ((s.observed_at AT TIME ZONE 'Europe/Moscow')::date)
   (s.observed_at AT TIME ZONE 'Europe/Moscow')::date AS day,
   s.observed_at,s.age_seconds,s.views_count AS v,s.reactions_count AS r,
   s.views_quality::text AS vq,s.reactions_quality::text AS rq,
   s.interval_uncertain AS uncertain,s.correction_sequence
  FROM ingest.publication_metric_snapshot s
  WHERE s.publication_id=p.id AND s.published_month=date_trunc('month',p.published_at)::date
    AND s.observed_at>='2026-09-12 21:00+00' AND s.observed_at<'2026-09-27 21:00+00'
    AND s.created_at<'2026-09-28 00:00+00' AND NOT s.synthetic
    AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot newer
      WHERE newer.published_month=s.published_month AND newer.publication_id=s.publication_id
        AND newer.sampling_bucket=s.sampling_bucket AND newer.correction_sequence>s.correction_sequence
        AND newer.created_at<'2026-09-28 00:00+00')
    AND s.age_seconds<=15*86400
  ORDER BY (s.observed_at AT TIME ZONE 'Europe/Moscow')::date,s.observed_at DESC,s.correction_sequence DESC,s.id DESC
 ) s
) d ON true
LEFT JOIN LATERAL (
 SELECT to_jsonb(s) AS point FROM (
  SELECT s.observed_at,s.age_seconds,s.views_count AS v,s.reactions_count AS r,
   s.views_quality::text AS vq,s.reactions_quality::text AS rq,
   s.interval_uncertain AS uncertain
  FROM ingest.publication_metric_snapshot s
  WHERE s.publication_id=p.id AND s.published_month=date_trunc('month',p.published_at)::date
    AND s.age_seconds BETWEEN 21*3600 AND 24*3600
    AND s.created_at<'2026-09-28 00:00+00' AND NOT s.synthetic
    AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot newer
      WHERE newer.published_month=s.published_month AND newer.publication_id=s.publication_id
        AND newer.sampling_bucket=s.sampling_bucket AND newer.correction_sequence>s.correction_sequence
        AND newer.created_at<'2026-09-28 00:00+00')
  ORDER BY s.observed_at DESC,s.correction_sequence DESC,s.id DESC LIMIT 1
 ) s
) e ON true
ORDER BY p.id;
COMMIT;
