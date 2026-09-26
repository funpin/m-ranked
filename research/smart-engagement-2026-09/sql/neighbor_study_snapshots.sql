-- Frozen 12-account deterministic Telegram sample plus MIPT case.
-- Read-only, bounded to September 5-15 publications and September 12-15
-- observations. Keep the resulting detailed CSV only in a temporary file.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '90s';

WITH selected_accounts(account_id, arm) AS (
  VALUES
    ('125362b3-a6ac-4ff5-8c0f-395eda0ad577'::uuid, 'hash_sample'),
    ('b48a9f75-9379-56d0-bbcd-0d158ceb4a3b'::uuid, 'hash_sample'),
    ('46a0583e-95cc-57d9-9b43-461f014fd86a'::uuid, 'hash_sample'),
    ('8c7483f7-a1c9-51c2-9d47-aaf13e85fe64'::uuid, 'hash_sample'),
    ('23f12212-6b82-5de1-9cc9-0439db8558fa'::uuid, 'hash_sample'),
    ('a058b3e4-993e-444a-9be4-d1f3925f4a0e'::uuid, 'hash_sample'),
    ('9820c314-9344-588e-9c7d-49c2b82c7ce6'::uuid, 'hash_sample'),
    ('4d7d5bb7-887b-503f-9e88-66c69d03ef08'::uuid, 'hash_sample'),
    ('c4ac0a85-b825-5939-b3fa-107fdf73b832'::uuid, 'hash_sample'),
    ('7bed0c82-cf7b-523a-95b7-5b616bb8cd7b'::uuid, 'hash_sample'),
    ('513a6138-6350-5c1e-afe8-47e4253c7266'::uuid, 'hash_sample'),
    ('faca5114-087c-4a09-92d7-3565c5a509c9'::uuid, 'hash_sample'),
    ('bd9c960e-1a76-5a72-a6a0-5a301e8e390a'::uuid, 'case_mipt')
), selected_posts AS (
  SELECT p.id AS publication_id, p.primary_account_id, a.arm,
         p.published_at, p.publication_type, p.history_completeness,
         p.first_observation_age_seconds,
         row_number() OVER (
           PARTITION BY p.primary_account_id ORDER BY p.published_at, p.id
         ) AS posting_order
  FROM ingest.publication AS p
  JOIN selected_accounts AS a ON a.account_id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND p.deleted_at IS NULL
)
SELECT p.publication_id, p.primary_account_id, p.arm,
       p.published_at, p.publication_type, p.history_completeness,
       p.first_observation_age_seconds, p.posting_order,
       s.observed_at, s.age_seconds, s.sampling_bucket,
       s.views_count, s.views_quality, s.interval_uncertain,
       s.synthetic, s.correction_sequence, s.collection_run_id
FROM selected_posts AS p
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.sampling_bucket,
         raw.views_count, raw.views_quality, raw.interval_uncertain,
         raw.synthetic, raw.correction_sequence, raw.collection_run_id
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.publication_id
    AND raw.published_month = DATE '2026-09-01'
    AND raw.observed_at >= TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND raw.observed_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
    AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.primary_account_id, p.posting_order, s.observed_at;

COMMIT;
