-- Read-only check whether this production DB has persisted anomaly results.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '20s';

SELECT (SELECT count(*) FROM analytics.publication_anomaly_finding)
         AS finding_count,
       (SELECT count(*) FROM analytics.publication_analysis_state)
         AS state_count;

COMMIT;
