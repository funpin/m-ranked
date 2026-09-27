-- Read-only nearby publication sequence for the same Telegram account.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '20s';

SELECT p.id, p.published_at, p.publication_type, p.is_repost,
       min(pi.public_url) AS public_url, min(pi.external_id) AS external_id
FROM ingest.publication AS p
LEFT JOIN ingest.publication_identity AS pi ON pi.publication_id = p.id
WHERE p.primary_account_id = 'bd9c960e-1a76-5a72-a6a0-5a301e8e390a'
  AND p.published_at >= TIMESTAMPTZ '2026-09-12 00:00:00+00'
  AND p.published_at < TIMESTAMPTZ '2026-09-16 00:00:00+00'
  AND p.deleted_at IS NULL
GROUP BY p.id
ORDER BY p.published_at;

COMMIT;
