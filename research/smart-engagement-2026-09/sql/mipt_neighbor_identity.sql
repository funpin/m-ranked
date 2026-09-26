-- Read-only identity and publication chronology for the user-supplied case.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '20s';

SELECT pi.external_id, pi.public_url, p.id AS publication_id,
       p.primary_account_id, p.published_at, p.publication_type,
       p.history_completeness, a.current_title, a.current_username
FROM ingest.publication_identity AS pi
JOIN ingest.publication AS p ON p.id = pi.publication_id
JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
JOIN catalog.institution AS i ON i.id = a.institution_id
WHERE pi.external_id IN ('m:11342', 'm:11343', 'm:11346')
  AND a.platform = 'telegram'
  AND (i.short_name ILIKE '%МФТИ%'
       OR i.canonical_name ILIKE '%МФТИ%'
       OR a.current_title ILIKE '%Физтех%')
ORDER BY p.published_at, pi.external_id;

COMMIT;
