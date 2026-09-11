"""Публичный анализ аномалий и две append-only команды."""
from __future__ import annotations


RESOLVE = """
SELECT publication.id
  FROM ingest.publication publication
 WHERE publication.id=%(entity_uuid)s::uuid
UNION ALL
SELECT alias.target_uuid
  FROM catalog.legacy_entity_alias alias
 WHERE %(entity_uuid)s::uuid IS NULL AND alias.entity_type=%(legacy_type)s
   AND alias.legacy_id=%(legacy_id)s
LIMIT 1
"""

REVISION = """
SELECT coalesce(state.analysis_revision_id,0) AS analysis_revision
  FROM ingest.publication publication
  LEFT JOIN analytics.publication_analysis_state_public state
    ON state.publication_id=publication.id
 WHERE publication.id=%(publication)s
"""

LOAD = """
WITH page AS (
    SELECT finding.*
      FROM analytics.publication_anomaly_finding_public finding
     WHERE finding.publication_id=%(publication)s AND finding.active
       AND (%(after)s::uuid IS NULL OR finding.id>%(after)s::uuid)
     ORDER BY finding.id LIMIT %(fetch_limit)s
), bounded AS (
    SELECT * FROM page ORDER BY id LIMIT %(limit)s
), aggregate AS (
    SELECT count(*)::integer AS active_count,
           bool_or(origin='manual') AS manual_present,
           max(suspicion_score) FILTER(WHERE origin='automatic') AS automatic_score,
           array_agg(DISTINCT metric::text ORDER BY metric::text) AS affected_metrics,
           (array_agg(severity ORDER BY CASE severity WHEN 'high' THEN 3
             WHEN 'medium' THEN 2 ELSE 1 END DESC))[1] AS overall_severity
      FROM analytics.publication_anomaly_finding_public
     WHERE publication_id=%(publication)s AND active
)
SELECT publication.id AS publication_id,coalesce(state.analysis_revision_id,0) AS analysis_revision,
       state.source_dataset_revision_id,state.analyzed_at,coalesce(state.status,'pending') AS status,
       state.source_revision_at,
       CASE WHEN state.suspicion_score IS NULL THEN NULL
            ELSE coalesce(aggregate.automatic_score,0) END AS suspicion_score,
       aggregate.overall_severity,coalesce(aggregate.manual_present,false) AS manual_present,
       coalesce(aggregate.affected_metrics,ARRAY[]::text[]) AS affected_metrics,
       coalesce(aggregate.active_count,0) AS active_count,
       coalesce((SELECT jsonb_agg(jsonb_build_object(
         'id',id,'origin',origin,'metric',metric,'detectorId',detector_id,
         'detectorVersion',detector_version,'suspicionScore',suspicion_score,
         'severity',severity,'explanationCode',explanation_code,
         'suspiciousStartAt',suspicious_start_at,'suspiciousEndAt',suspicious_end_at,
         'startSnapshotId',start_snapshot_id,'endSnapshotId',end_snapshot_id,
         'evidence',evidence,'qualityCodes',quality_codes,
         'alternativeExplanationCodes',alternative_explanation_codes,
         'reviewState',review_state) ORDER BY id) FROM bounded),'[]'::jsonb) AS findings,
       CASE WHEN (SELECT count(*) FROM page)>%(limit)s
            THEN (SELECT id FROM bounded ORDER BY id DESC LIMIT 1) END AS continuation_id
  FROM ingest.publication publication
  LEFT JOIN analytics.publication_analysis_state_public state ON state.publication_id=publication.id
 CROSS JOIN aggregate
 WHERE publication.id=%(publication)s
"""

CREATE_MANUAL = """
SELECT analytics.create_manual_anomaly_signal(
  %(publication)s,%(metric)s,%(severity)s,%(explanation)s,%(start_at)s,%(end_at)s,
  %(evidence)s::jsonb,%(actor)s,%(correlation)s,%(idempotency)s,%(digest)s) AS result
"""

APPEND_REVIEW = """
SELECT analytics.append_anomaly_review(
  %(finding)s,%(decision)s,%(comment)s,%(actor)s,%(correlation)s,%(idempotency)s,%(digest)s) AS result
"""
