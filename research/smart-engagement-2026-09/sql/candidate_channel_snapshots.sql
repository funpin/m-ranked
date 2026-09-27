-- Read-only exploratory comparison of every post in the same publication week
-- for the two Telegram candidate accounts. Aggregate locally; do not save
-- these raw case-neighbor rows in the research repository.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';

WITH candidate_accounts AS (
  SELECT DISTINCT primary_account_id
  FROM ingest.publication
  WHERE id IN (
    '5124e3e9-0af2-5e9d-8e47-a12219d014fa',
    '918ec5a0-0d52-51e9-83d8-aa48f745317a'
  )
), selected AS (
  SELECT p.id, p.primary_account_id, p.published_at,
         p.first_observation_age_seconds, p.history_completeness
  FROM ingest.publication AS p
  JOIN candidate_accounts AS c USING (primary_account_id)
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT p.id AS publication_id, p.primary_account_id, p.published_at,
       p.first_observation_age_seconds, p.history_completeness,
       s.observed_at, s.age_seconds, s.sampling_bucket,
       s.views_count, s.reactions_count, s.views_quality,
       s.reactions_quality, s.synthetic, s.correction_sequence
FROM selected AS p
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.sampling_bucket,
         raw.views_count, raw.reactions_count, raw.views_quality,
         raw.reactions_quality, raw.synthetic, raw.correction_sequence
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.id
    AND raw.published_month = DATE '2026-09-01'
    AND raw.observed_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
    AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.primary_account_id, p.published_at, s.observed_at;

COMMIT;
