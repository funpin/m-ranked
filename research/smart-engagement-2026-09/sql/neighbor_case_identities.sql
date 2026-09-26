-- Public identities for the two non-MIPT channels with candidates in the
-- deterministic September Telegram sample. Run only in a read-only session.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';

SELECT p.id AS publication_id, p.primary_account_id, p.published_at,
       i.short_name AS institution, a.current_username,
       pi.external_id, pi.public_url
FROM ingest.publication AS p
JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
JOIN catalog.institution AS i ON i.id = a.institution_id
LEFT JOIN LATERAL (
  SELECT external_id, public_url
  FROM ingest.publication_identity
  WHERE publication_id = p.id AND platform_account_id = a.id
  ORDER BY id
  LIMIT 1
) AS pi ON true
WHERE p.primary_account_id IN (
  '513a6138-6350-5c1e-afe8-47e4253c7266'::uuid,
  '7bed0c82-cf7b-523a-95b7-5b616bb8cd7b'::uuid
)
  AND p.published_at >= TIMESTAMPTZ '2026-09-05 00:00:00+00'
  AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
  AND p.deleted_at IS NULL
ORDER BY p.primary_account_id, p.published_at;

COMMIT;
