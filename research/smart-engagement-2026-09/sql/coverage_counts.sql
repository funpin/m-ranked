-- Reference read-only audit. The second query scans a large partitioned table:
-- run on a replica or in a planned low-load window, not repeatedly in a UI.
-- These totals are time-dependent and will exceed the 2026-09-26 report later.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '120s';

SELECT a.platform, count(*) AS publications,
       min(p.published_at) AS oldest_published_at,
       max(p.published_at) AS newest_published_at
FROM ingest.publication AS p
JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
GROUP BY a.platform
ORDER BY a.platform;

SELECT a.platform, count(*) AS raw_snapshot_rows,
       count(*) FILTER (WHERE s.correction_sequence > 0) AS correction_rows,
       min(s.observed_at) AS first_observed_at,
       max(s.observed_at) AS last_observed_at
FROM ingest.publication_metric_snapshot AS s
JOIN ingest.publication AS p ON p.id = s.publication_id
JOIN catalog.platform_account AS a ON a.id = p.primary_account_id
GROUP BY a.platform
ORDER BY a.platform;

COMMIT;
