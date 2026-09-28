BEGIN READ ONLY;
SET LOCAL statement_timeout='20s';
SET LOCAL lock_timeout='1s';
WITH recent AS MATERIALIZED (
 SELECT publication_id, observed_at, views_count, reactions_count,
        views_quality, reactions_quality, interval_uncertain, snapshot_written
 FROM ingest.publication_poll_receipt
 WHERE observed_at >= now()-interval '7 days'
 ORDER BY observed_at DESC LIMIT 100001
), pairs AS (
 SELECT r.*,p.primary_account_id,p.published_at,a.platform,
        lag(views_count) OVER w AS previous_v,
        lag(reactions_count) OVER w AS previous_r,
        lag(observed_at) OVER w AS previous_time
 FROM recent r JOIN ingest.publication p ON p.id=r.publication_id
 JOIN catalog.platform_account a ON a.id=p.primary_account_id
 WINDOW w AS (PARTITION BY publication_id ORDER BY observed_at)
)
SELECT jsonb_build_object(
 'bounded_to_last_7_days_and_100001_rows',true,
 'row_cap_reached',(SELECT count(*)>100000 FROM recent),
 'heap_bytes',pg_relation_size('ingest.publication_poll_receipt'),
 'index_bytes',pg_indexes_size('ingest.publication_poll_receipt'),
 'total_bytes',pg_total_relation_size('ingest.publication_poll_receipt'),
 'rows',(SELECT count(*) FROM recent),
 'by_platform',(SELECT jsonb_agg(to_jsonb(s)) FROM (
   SELECT platform,count(*) AS receipts,count(DISTINCT publication_id) AS posts,
    count(DISTINCT primary_account_id) AS accounts,min(observed_at) AS first_read,
    max(observed_at) AS last_read,
    count(*) FILTER(WHERE NOT snapshot_written) AS no_new_metric_snapshot,
    count(*) FILTER(WHERE previous_time IS NOT NULL AND views_count=previous_v AND reactions_count=previous_r) AS consecutive_equal_v_and_r,
    count(*) FILTER(WHERE observed_at-published_at>=interval '4 days') AS age_ge_4d,
    count(*) FILTER(WHERE observed_at-published_at>=interval '7 days') AS age_ge_7d,
    count(*) FILTER(WHERE views_quality='exact' AND reactions_quality='exact' AND NOT interval_uncertain) AS exact_vr
   FROM pairs GROUP BY platform ORDER BY platform
 ) s));
COMMIT;
