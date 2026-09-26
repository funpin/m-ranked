-- Bounded effective observations for the MIPT 11342-11349 neighborhood.
-- Export only to a temporary local file; save aggregates/case evidence in MD.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '45s';

WITH selected AS (
  SELECT p.id, p.published_at,
         (SELECT min(pi.external_id)
          FROM ingest.publication_identity AS pi
          WHERE pi.publication_id = p.id) AS external_id
  FROM ingest.publication AS p
  WHERE p.primary_account_id = 'bd9c960e-1a76-5a72-a6a0-5a301e8e390a'
    AND p.published_at >= TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT p.id, p.external_id, p.published_at,
       s.observed_at, s.age_seconds, s.sampling_bucket,
       s.views_count, s.reactions_count,
       s.views_quality, s.reactions_quality,
       s.interval_uncertain, s.synthetic, s.correction_sequence,
       s.collection_run_id
FROM selected AS p
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.sampling_bucket,
         raw.views_count, raw.reactions_count,
         raw.views_quality, raw.reactions_quality,
         raw.interval_uncertain, raw.synthetic,
         raw.correction_sequence, raw.collection_run_id
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.id
    AND raw.published_month = DATE '2026-09-01'
    AND raw.observed_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.published_at, s.observed_at;

COMMIT;
