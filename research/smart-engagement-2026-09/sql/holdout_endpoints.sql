-- Supply a JSON array of preselected UUIDs as the psql variable ids.
-- Bounded, read-only endpoint refresh: no full history, no production writes.
BEGIN READ ONLY;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='2s';
SET LOCAL TIME ZONE 'UTC';
WITH selected AS (
 SELECT p.id,p.published_at FROM ingest.publication p
 WHERE p.id IN (SELECT value::uuid FROM jsonb_array_elements_text(:'ids'::jsonb))
), rows AS (
 SELECT p.id, h.hours, s.*
 FROM selected p CROSS JOIN (VALUES(24,3),(72,6),(168,12)) h(hours,slack)
 LEFT JOIN LATERAL (
  SELECT observed_at,age_seconds,views_count AS v,reactions_count AS r,
   comments_count AS c,shares_count AS s,views_quality::text AS vq,
   reactions_quality::text AS rq,interval_uncertain AS uncertain
  FROM ingest.publication_metric_snapshot raw
  WHERE raw.publication_id=p.id AND raw.published_month=date_trunc('month',p.published_at)::date
   AND raw.age_seconds BETWEEN (h.hours-h.slack)*3600 AND h.hours*3600
   AND NOT raw.synthetic
  ORDER BY raw.observed_at DESC,raw.correction_sequence DESC LIMIT 1
 ) s ON true
)
SELECT jsonb_build_object('id',id,'points',jsonb_agg(to_jsonb(rows)-'id'-'hours')
       FILTER(WHERE observed_at IS NOT NULL)) FROM rows GROUP BY id;
COMMIT;
