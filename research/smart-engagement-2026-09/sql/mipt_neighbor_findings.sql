-- Read-only latest finding evidence for post 11342; times are UTC.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '20s';

SELECT metric, detector_id, severity, suspicion_score,
       suspicious_start_at, suspicious_end_at, evidence,
       alternative_explanation_codes, created_analysis_revision_id
FROM analytics.publication_anomaly_finding
WHERE publication_id = '26782437-05ec-5040-8313-3cb8fbf5eaff'
ORDER BY created_analysis_revision_id DESC, suspicious_start_at
LIMIT 30;

COMMIT;
