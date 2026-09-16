-- 0027 — метрики Analyze после удаления publisher-barrier
--
-- Live-read cutover удалил analytics.latest_fully_published_dataset_revision(),
-- но функция метрик на уже существующей production-базе сохранила старое тело.
-- В результате exporter и anomaly worker падали до обработки первого batch.
-- CREATE OR REPLACE не меняет сигнатуру и совместим со старым и новым кодом.

CREATE OR REPLACE FUNCTION analytics.anomaly_operational_metrics() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    AS $$
SELECT jsonb_build_object(
  'candidate_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate),
  'eligible_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE eligible_at<=transaction_timestamp()),
  'oldest_candidate_age_seconds',(SELECT coalesce(greatest(0,extract(epoch FROM transaction_timestamp()-min(eligible_at))),0) FROM ops_and_admin.anomaly_analysis_candidate),
  'expired_leases',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE claim_token IS NOT NULL AND leased_until<transaction_timestamp()),
  'retry_candidates',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE retry_count>0),
  'failures_last_hour',(SELECT count(*) FROM analytics.publication_analysis_attempt WHERE status='failed' AND completed_at>=transaction_timestamp()-interval '1 hour'),
  'latest_analysis_revision',(SELECT coalesce(max(id),0) FROM analytics.anomaly_analysis_revision),
  'latest_source_dataset_revision',(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state),
  'source_revision_lag',greatest(0,
      coalesce((SELECT id FROM analytics.latest_dataset_revision()),0)
      -(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state)),
  'last_success_unixtime',(SELECT coalesce(extract(epoch FROM max(completed_at)),0) FROM analytics.publication_analysis_attempt WHERE status='succeeded')
)
$$;

REVOKE ALL ON FUNCTION analytics.anomaly_operational_metrics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.anomaly_operational_metrics() TO analytics_worker, maintenance;
