-- Bounded read-only source for 16 exploratory and 16 previously unread
-- deterministic comparison cases. The Python packaging script removes the
-- organizer's sampling arm and provisional labels from reviewer files.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';

WITH ranked AS (
  SELECT p.id AS publication_id, a.platform, p.published_at,
         p.publication_type, p.is_repost, p.history_completeness,
         p.first_observation_age_seconds, p.content_group_id,
         row_number() OVER (
           PARTITION BY a.platform ORDER BY md5(p.id::text)
         ) AS sample_rank
  FROM ingest.publication AS p
  JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
  WHERE p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
    AND p.published_at < TIMESTAMPTZ '2026-09-12 00:00:00+00'
    AND p.deleted_at IS NULL
), selected AS (
  SELECT *, CASE WHEN sample_rank IN (31, 38, 47, 54)
                 THEN 'deterministic_comparison' ELSE 'exploratory' END AS sampling_arm
  FROM ranked
  WHERE sample_rank IN (31, 38, 47, 54)
     OR publication_id IN (
       '066c4657-81cb-5f4a-b97a-7d950f3a3cf4',
       '17913f83-ef74-5279-bd41-cadb62af3040',
       '5124e3e9-0af2-5e9d-8e47-a12219d014fa',
       '918ec5a0-0d52-51e9-83d8-aa48f745317a',
       '2b3f7982-676f-5bba-88be-efdf6888464c',
       '52cc0aca-cf86-5201-b19c-882a22524833',
       '0858944f-13a3-509b-b30a-e85733a4d6e2',
       'c5527c6b-bc78-59e4-ac2f-0357f0c6a86d',
       '85d273c5-082b-541e-ab70-30fe5750a921',
       '2dff9578-a546-5cda-8223-188305812165',
       '4be67b2f-775a-5a8f-8314-9a3642da5908',
       'e4b2f3f3-5d48-579d-9efd-40e24ccea9fa',
       '63b69686-3d52-521a-a75c-b46aad77d1ba',
       'c5aa7365-838b-5535-9b23-7d09ef978f29',
       '5e6ecce3-ba99-5a1c-a746-bdcadc474b9b',
       '839b4dc7-a934-50c9-8119-7f69ed6fb681'
     )
)
SELECT p.platform, p.publication_id, p.sample_rank, p.sampling_arm,
       i.public_url, p.published_at, p.publication_type, p.is_repost,
       p.history_completeness, p.first_observation_age_seconds,
       p.content_group_id,
       s.observed_at, s.age_seconds, s.sampling_bucket,
       s.views_count, s.reactions_count, s.comments_count, s.shares_count,
       s.views_quality, s.reactions_quality, s.comments_quality,
       s.shares_quality, s.interval_uncertain, s.synthetic,
       s.correction_sequence
FROM selected AS p
LEFT JOIN LATERAL (
  SELECT min(public_url) AS public_url
  FROM ingest.publication_identity
  WHERE publication_id = p.publication_id AND public_url IS NOT NULL
) AS i ON true
LEFT JOIN LATERAL (
  SELECT DISTINCT ON (raw.sampling_bucket)
         raw.observed_at, raw.age_seconds, raw.sampling_bucket,
         raw.views_count, raw.reactions_count, raw.comments_count,
         raw.shares_count, raw.views_quality, raw.reactions_quality,
         raw.comments_quality, raw.shares_quality, raw.interval_uncertain,
         raw.synthetic, raw.correction_sequence
  FROM ingest.publication_metric_snapshot AS raw
  WHERE raw.publication_id = p.publication_id
    AND raw.published_month = DATE '2026-09-01'
    AND raw.observed_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
    AND raw.created_at < TIMESTAMPTZ '2026-09-26 00:00:00+00'
  ORDER BY raw.sampling_bucket, raw.correction_sequence DESC
) AS s ON true
ORDER BY p.platform, p.sample_rank, s.observed_at;

COMMIT;
