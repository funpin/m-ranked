-- 0012 — представления
-- Порождается из каталога эталонной базы; см. db/README.md.

-- catalog.visible_institution
CREATE VIEW catalog.visible_institution AS
 SELECT id,
    canonical_name,
    short_name,
    status,
    created_at,
    updated_at,
    row_version,
    deleted_at
   FROM catalog.institution
  WHERE (deleted_at IS NULL);

-- catalog.visible_platform_account
CREATE VIEW catalog.visible_platform_account AS
 SELECT account.id,
    account.institution_id,
    account.platform,
    account.canonical_external_id,
    account.current_username,
    account.current_title,
    account.current_url,
    account.access_mode,
    account.enabled,
    account.created_at,
    account.updated_at,
    account.row_version,
    account.deleted_at
   FROM (catalog.platform_account account
     JOIN catalog.visible_institution institution ON ((institution.id = account.institution_id)))
  WHERE (account.deleted_at IS NULL);

-- ingest.publication_metric_snapshot_resolved
CREATE VIEW ingest.publication_metric_snapshot_resolved AS
 SELECT s.published_month,
    s.id,
    s.publication_id,
    s.collection_run_id,
    s.observed_at,
    s.age_seconds,
    s.sampling_bucket,
    s.views_count,
    s.reactions_count,
    s.comments_count,
    s.shares_count,
    s.quality,
    s.interval_uncertain,
    s.synthetic,
    s.metric_semantics_version,
    s.capability_version,
    s.source_fingerprint,
    s.created_at,
    s.collected_at,
    s.ingested_xid,
    s.correction_sequence,
    s.supersedes_snapshot_id,
    s.correction_reason,
    s.views_quality,
    s.reactions_quality,
    s.comments_quality,
    s.shares_quality,
    COALESCE(s.metric_evidence, evidence.payload) AS metric_evidence,
    s.semantic_fingerprint
   FROM (ingest.publication_metric_snapshot s
     LEFT JOIN ingest.metric_evidence_dictionary evidence ON ((evidence.id = s.metric_evidence_id)));

-- ingest.publication_metric_snapshot_active
CREATE VIEW ingest.publication_metric_snapshot_active AS
 SELECT published_month,
    id,
    publication_id,
    collection_run_id,
    observed_at,
    age_seconds,
    sampling_bucket,
    views_count,
    reactions_count,
    comments_count,
    shares_count,
    quality,
    interval_uncertain,
    synthetic,
    metric_semantics_version,
    capability_version,
    source_fingerprint,
    created_at,
    collected_at,
    ingested_xid,
    correction_sequence,
    supersedes_snapshot_id,
    correction_reason,
    views_quality,
    reactions_quality,
    comments_quality,
    shares_quality,
    metric_evidence,
    semantic_fingerprint
   FROM ingest.publication_metric_snapshot_resolved s
  WHERE (NOT (EXISTS ( SELECT 1
           FROM ingest.publication_metric_snapshot successor
          WHERE ((successor.published_month = s.published_month) AND (successor.publication_id = s.publication_id) AND (successor.sampling_bucket = s.sampling_bucket) AND (successor.correction_sequence > s.correction_sequence)))));

-- ingest.visible_publication
CREATE VIEW ingest.visible_publication AS
 SELECT publication.id,
    publication.primary_account_id,
    publication.content_group_id,
    publication.published_at,
    publication.discovered_at,
    publication.first_observation_age_seconds,
    publication.publication_type,
    publication.is_repost,
    publication.history_completeness,
    publication.synthetic_baseline_allowed,
    publication.quality_flags,
    publication.deleted_at,
    publication.created_at
   FROM (ingest.publication publication
     JOIN catalog.visible_platform_account account ON ((account.id = publication.primary_account_id)));

-- analytics.usable_publication_snapshot
CREATE VIEW analytics.usable_publication_snapshot AS
 SELECT visible.published_month,
    visible.id,
    visible.publication_id,
    visible.collection_run_id,
    visible.observed_at,
    visible.age_seconds,
    visible.sampling_bucket,
    visible.views_count,
    visible.reactions_count,
    visible.comments_count,
    visible.shares_count,
    visible.quality,
    visible.interval_uncertain,
    visible.synthetic,
    visible.metric_semantics_version,
    visible.capability_version,
    visible.source_fingerprint,
    visible.created_at,
    visible.collected_at,
    visible.correction_sequence,
    visible.supersedes_snapshot_id,
    visible.correction_reason,
    visible.views_quality,
    visible.reactions_quality,
    visible.comments_quality,
    visible.shares_quality,
    visible.metric_evidence
   FROM (( SELECT s.published_month,
            s.id,
            s.publication_id,
            s.collection_run_id,
            s.observed_at,
            s.age_seconds,
            s.sampling_bucket,
                CASE
                    WHEN (s.views_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.views_count
                END AS views_count,
                CASE
                    WHEN (s.reactions_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.reactions_count
                END AS reactions_count,
                CASE
                    WHEN (s.comments_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.comments_count
                END AS comments_count,
                CASE
                    WHEN (s.shares_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.shares_count
                END AS shares_count,
            analytics.observation_quality_from_rank((COALESCE(( SELECT max(analytics.observation_quality_rank(v.quality)) AS max
                   FROM ( VALUES (s.views_count,s.views_quality), (s.reactions_count,s.reactions_quality), (s.comments_count,s.comments_quality), (s.shares_count,s.shares_quality)) v(value, quality)
                  WHERE ((v.value IS NOT NULL) AND (v.quality <> ALL (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])))), analytics.observation_quality_rank(s.quality)))::integer) AS quality,
            s.interval_uncertain,
            s.synthetic,
            s.metric_semantics_version,
            s.capability_version,
            s.source_fingerprint,
            s.created_at,
            s.collected_at,
            s.correction_sequence,
            s.supersedes_snapshot_id,
            s.correction_reason,
            s.views_quality,
            s.reactions_quality,
            s.comments_quality,
            s.shares_quality,
            s.metric_evidence
           FROM ingest.publication_metric_snapshot_active s) visible
     JOIN ingest.visible_publication publication ON ((publication.id = visible.publication_id)));

-- analytics.publication_analysis_state_public
CREATE VIEW analytics.publication_analysis_state_public AS
 SELECT publication_id,
    analysis_revision_id,
    status,
    suspicion_score,
    automatic_severity,
    affected_metrics,
    active_automatic_finding_count,
    source_dataset_revision_id,
    source_revision_at,
    analyzed_at
   FROM analytics.publication_analysis_state;

-- analytics.publication_anomaly_finding_public
CREATE VIEW analytics.publication_anomaly_finding_public AS
 WITH effective AS (
         SELECT finding.id,
            finding.finding_key,
            finding.publication_id,
            finding.attempt_id,
            finding.created_analysis_revision_id,
            finding.origin,
            finding.metric,
            finding.detector_id,
            finding.detector_version,
            finding.suspicion_score,
            finding.severity,
            finding.explanation_code,
            finding.suspicious_start_at,
            finding.suspicious_end_at,
            finding.start_snapshot_id,
            finding.end_snapshot_id,
            finding.evidence,
            finding.quality_codes,
            finding.alternative_explanation_codes,
            finding.created_at,
            ( SELECT review.decision
                   FROM analytics.publication_anomaly_review review
                  WHERE ((review.publication_id = finding.publication_id) AND (review.finding_key = finding.finding_key))
                  ORDER BY review.reviewed_at DESC, review.id DESC
                 LIMIT 1) AS review_state
           FROM analytics.publication_anomaly_finding finding
        ), current_findings AS (
         SELECT effective.id,
            effective.finding_key,
            effective.publication_id,
            effective.attempt_id,
            effective.created_analysis_revision_id,
            effective.origin,
            effective.metric,
            effective.detector_id,
            effective.detector_version,
            effective.suspicion_score,
            effective.severity,
            effective.explanation_code,
            effective.suspicious_start_at,
            effective.suspicious_end_at,
            effective.start_snapshot_id,
            effective.end_snapshot_id,
            effective.evidence,
            effective.quality_codes,
            effective.alternative_explanation_codes,
            effective.created_at,
            effective.review_state
           FROM (effective
             LEFT JOIN analytics.publication_analysis_state state ON ((state.publication_id = effective.publication_id)))
          WHERE (((effective.origin = 'automatic'::text) AND (effective.attempt_id = state.current_success_attempt_id)) OR (effective.origin = 'manual'::text))
        )
 SELECT id,
    publication_id,
    origin,
    metric,
    detector_id,
    detector_version,
    suspicion_score,
    severity,
    explanation_code,
    suspicious_start_at,
    suspicious_end_at,
    start_snapshot_id,
    end_snapshot_id,
    evidence,
    quality_codes,
    alternative_explanation_codes,
    COALESCE((review_state)::text, 'unreviewed'::text) AS review_state,
    ((review_state IS DISTINCT FROM 'dismissed'::analytics.review_decision) AND (review_state IS DISTINCT FROM 'data_error'::analytics.review_decision)) AS active
   FROM current_findings;

-- ingest.account_metric_snapshot_active
CREATE VIEW ingest.account_metric_snapshot_active AS
 SELECT id,
    platform_account_id,
    collection_run_id,
    observed_at,
    subscriber_count,
    subscriber_display,
    quality,
    source_fingerprint,
    created_at,
    collected_at,
    correction_sequence,
    supersedes_snapshot_id,
    correction_reason,
    subscriber_quality,
    subscriber_source_field,
    subscriber_semantic_flags,
    semantic_fingerprint
   FROM ingest.account_metric_snapshot snapshot
  WHERE (NOT (EXISTS ( SELECT 1
           FROM ingest.account_metric_snapshot successor
          WHERE ((successor.platform_account_id = snapshot.platform_account_id) AND (successor.observed_at = snapshot.observed_at) AND (successor.correction_sequence > snapshot.correction_sequence)))));

-- ops_and_admin.schema_contract
CREATE VIEW ops_and_admin.schema_contract AS
 SELECT 'live-read-2026-09-13-text-fingerprint'::text AS contract_id;

-- rating.official_institution_rating_observation
CREATE VIEW rating.official_institution_rating_observation AS
 SELECT id,
    institution_id,
    category,
    period,
    rank,
    score,
    source_url,
    source_hash,
    fetched_at,
    entity_scope
   FROM rating.official_rating_observation observation
  WHERE (entity_scope = 'institution'::text);
