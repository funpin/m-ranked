-- 0015 — внешние ключи
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.account_latest account_latest_dataset_revision_id_fkey
ALTER TABLE analytics.account_latest
    ADD CONSTRAINT account_latest_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.account_latest account_latest_platform_account_id_fkey
ALTER TABLE analytics.account_latest
    ADD CONSTRAINT account_latest_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- analytics.anomaly_analysis_revision anomaly_analysis_revision_publication_id_fkey
ALTER TABLE analytics.anomaly_analysis_revision
    ADD CONSTRAINT anomaly_analysis_revision_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.anomaly_event anomaly_event_dataset_revision_id_fkey
ALTER TABLE analytics.anomaly_event
    ADD CONSTRAINT anomaly_event_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.anomaly_event anomaly_event_institution_id_fkey
ALTER TABLE analytics.anomaly_event
    ADD CONSTRAINT anomaly_event_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.anomaly_event anomaly_event_platform_account_id_fkey
ALTER TABLE analytics.anomaly_event
    ADD CONSTRAINT anomaly_event_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- analytics.anomaly_event anomaly_event_publication_id_fkey
ALTER TABLE analytics.anomaly_event
    ADD CONSTRAINT anomaly_event_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.anomaly_review anomaly_review_anomaly_event_id_fkey
ALTER TABLE analytics.anomaly_review
    ADD CONSTRAINT anomaly_review_anomaly_event_id_fkey FOREIGN KEY (anomaly_event_id) REFERENCES analytics.anomaly_event(id);

-- analytics.anomaly_source_revision anomaly_source_revision_dataset_revision_id_fkey
ALTER TABLE analytics.anomaly_source_revision
    ADD CONSTRAINT anomaly_source_revision_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.comparison_cohort comparison_cohort_dataset_revision_id_fkey
ALTER TABLE analytics.comparison_cohort
    ADD CONSTRAINT comparison_cohort_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.comparison_cohort_member comparison_cohort_member_cohort_id_fkey
ALTER TABLE analytics.comparison_cohort_member
    ADD CONSTRAINT comparison_cohort_member_cohort_id_fkey FOREIGN KEY (cohort_id) REFERENCES analytics.comparison_cohort(id) ON DELETE CASCADE;

-- analytics.comparison_cohort_member comparison_cohort_member_institution_id_fkey
ALTER TABLE analytics.comparison_cohort_member
    ADD CONSTRAINT comparison_cohort_member_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.comparison_cohort_member comparison_cohort_member_publication_id_fkey
ALTER TABLE analytics.comparison_cohort_member
    ADD CONSTRAINT comparison_cohort_member_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.dataset_revision dataset_revision_source_run_id_fkey
ALTER TABLE analytics.dataset_revision
    ADD CONSTRAINT dataset_revision_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES ingest.collection_run(id);

-- analytics.institution_daily_metrics institution_daily_metrics_dataset_revision_id_fkey
ALTER TABLE analytics.institution_daily_metrics
    ADD CONSTRAINT institution_daily_metrics_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.institution_daily_metrics institution_daily_metrics_institution_id_fkey
ALTER TABLE analytics.institution_daily_metrics
    ADD CONSTRAINT institution_daily_metrics_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.institution_metric_aggregate institution_metric_aggregate_dataset_revision_id_fkey
ALTER TABLE analytics.institution_metric_aggregate
    ADD CONSTRAINT institution_metric_aggregate_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.institution_metric_aggregate institution_metric_aggregate_institution_id_fkey
ALTER TABLE analytics.institution_metric_aggregate
    ADD CONSTRAINT institution_metric_aggregate_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.institution_monthly_metrics institution_monthly_metrics_dataset_revision_id_fkey
ALTER TABLE analytics.institution_monthly_metrics
    ADD CONSTRAINT institution_monthly_metrics_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.institution_monthly_metrics institution_monthly_metrics_institution_id_fkey
ALTER TABLE analytics.institution_monthly_metrics
    ADD CONSTRAINT institution_monthly_metrics_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.institution_period_metrics institution_period_metrics_dataset_revision_id_fkey
ALTER TABLE analytics.institution_period_metrics
    ADD CONSTRAINT institution_period_metrics_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.institution_period_metrics institution_period_metrics_institution_id_fkey
ALTER TABLE analytics.institution_period_metrics
    ADD CONSTRAINT institution_period_metrics_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.legacy_native_export_lexeme legacy_native_export_lexeme_publication_id_fkey
ALTER TABLE analytics.legacy_native_export_lexeme
    ADD CONSTRAINT legacy_native_export_lexeme_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.legacy_overview_account legacy_overview_account_account_id_fkey
ALTER TABLE analytics.legacy_overview_account
    ADD CONSTRAINT legacy_overview_account_account_id_fkey FOREIGN KEY (account_id) REFERENCES catalog.platform_account(id);

-- analytics.legacy_overview_account legacy_overview_account_dataset_revision_id_fkey
ALTER TABLE analytics.legacy_overview_account
    ADD CONSTRAINT legacy_overview_account_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.legacy_overview_card legacy_overview_card_dataset_revision_id_fkey
ALTER TABLE analytics.legacy_overview_card
    ADD CONSTRAINT legacy_overview_card_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.legacy_overview_card legacy_overview_card_institution_id_fkey
ALTER TABLE analytics.legacy_overview_card
    ADD CONSTRAINT legacy_overview_card_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.platform_metric_capability platform_metric_capability_metric_key_semantic_version_fkey
ALTER TABLE analytics.platform_metric_capability
    ADD CONSTRAINT platform_metric_capability_metric_key_semantic_version_fkey FOREIGN KEY (metric_key, semantic_version) REFERENCES analytics.metric_semantic_definition(metric_key, version);

-- analytics.publication_analysis_attempt publication_analysis_attempt_analysis_revision_id_fkey
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_analysis_revision_id_fkey FOREIGN KEY (analysis_revision_id) REFERENCES analytics.anomaly_analysis_revision(id);

-- analytics.publication_analysis_attempt publication_analysis_attempt_publication_id_fkey
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.publication_analysis_attempt publication_analysis_attempt_source_dataset_revision_id_fkey
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_source_dataset_revision_id_fkey FOREIGN KEY (source_dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.publication_analysis_state publication_analysis_state_analysis_revision_id_fkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_analysis_revision_id_fkey FOREIGN KEY (analysis_revision_id) REFERENCES analytics.anomaly_analysis_revision(id);

-- analytics.publication_analysis_state publication_analysis_state_current_success_attempt_id_fkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_current_success_attempt_id_fkey FOREIGN KEY (current_success_attempt_id) REFERENCES analytics.publication_analysis_attempt(id);

-- analytics.publication_analysis_state publication_analysis_state_latest_failure_attempt_id_fkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_latest_failure_attempt_id_fkey FOREIGN KEY (latest_failure_attempt_id) REFERENCES analytics.publication_analysis_attempt(id);

-- analytics.publication_analysis_state publication_analysis_state_publication_id_fkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.publication_analysis_state publication_analysis_state_source_dataset_revision_id_fkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_source_dataset_revision_id_fkey FOREIGN KEY (source_dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.publication_anomaly_finding publication_anomaly_finding_attempt_id_fkey
ALTER TABLE analytics.publication_anomaly_finding
    ADD CONSTRAINT publication_anomaly_finding_attempt_id_fkey FOREIGN KEY (attempt_id) REFERENCES analytics.publication_analysis_attempt(id) ON DELETE CASCADE;

-- analytics.publication_anomaly_finding publication_anomaly_finding_created_analysis_revision_id_fkey
ALTER TABLE analytics.publication_anomaly_finding
    ADD CONSTRAINT publication_anomaly_finding_created_analysis_revision_id_fkey FOREIGN KEY (created_analysis_revision_id) REFERENCES analytics.anomaly_analysis_revision(id);

-- analytics.publication_anomaly_finding publication_anomaly_finding_publication_id_fkey
ALTER TABLE analytics.publication_anomaly_finding
    ADD CONSTRAINT publication_anomaly_finding_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.publication_anomaly_review publication_anomaly_review_analysis_revision_id_fkey
ALTER TABLE analytics.publication_anomaly_review
    ADD CONSTRAINT publication_anomaly_review_analysis_revision_id_fkey FOREIGN KEY (analysis_revision_id) REFERENCES analytics.anomaly_analysis_revision(id);

-- analytics.publication_anomaly_review publication_anomaly_review_publication_id_fkey
ALTER TABLE analytics.publication_anomaly_review
    ADD CONSTRAINT publication_anomaly_review_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- analytics.publication_content publication_content_dataset_revision_id_fkey
ALTER TABLE analytics.publication_content
    ADD CONSTRAINT publication_content_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.publication_content publication_content_publication_id_fkey
ALTER TABLE analytics.publication_content
    ADD CONSTRAINT publication_content_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- analytics.publication_history publication_history_dataset_revision_id_fkey
ALTER TABLE analytics.publication_history
    ADD CONSTRAINT publication_history_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.publication_history publication_history_publication_id_fkey
ALTER TABLE analytics.publication_history
    ADD CONSTRAINT publication_history_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- analytics.publication_latest publication_latest_dataset_revision_id_fkey
ALTER TABLE analytics.publication_latest
    ADD CONSTRAINT publication_latest_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- analytics.publication_latest publication_latest_institution_id_fkey
ALTER TABLE analytics.publication_latest
    ADD CONSTRAINT publication_latest_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- analytics.publication_latest publication_latest_platform_account_id_fkey
ALTER TABLE analytics.publication_latest
    ADD CONSTRAINT publication_latest_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- analytics.publication_latest publication_latest_publication_id_fkey
ALTER TABLE analytics.publication_latest
    ADD CONSTRAINT publication_latest_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- catalog.account_external_identity account_external_identity_platform_account_id_fkey
ALTER TABLE catalog.account_external_identity
    ADD CONSTRAINT account_external_identity_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- catalog.account_external_identity account_external_identity_source_run_fk
ALTER TABLE catalog.account_external_identity
    ADD CONSTRAINT account_external_identity_source_run_fk FOREIGN KEY (source_run_id) REFERENCES ingest.collection_run(id);

-- catalog.account_identity_history account_identity_history_platform_account_id_fkey
ALTER TABLE catalog.account_identity_history
    ADD CONSTRAINT account_identity_history_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- catalog.account_identity_history account_identity_history_source_run_fk
ALTER TABLE catalog.account_identity_history
    ADD CONSTRAINT account_identity_history_source_run_fk FOREIGN KEY (source_run_id) REFERENCES ingest.collection_run(id);

-- catalog.account_verification account_verification_platform_account_id_fkey
ALTER TABLE catalog.account_verification
    ADD CONSTRAINT account_verification_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- catalog.institution_external_id institution_external_id_institution_id_fkey
ALTER TABLE catalog.institution_external_id
    ADD CONSTRAINT institution_external_id_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- catalog.platform_account platform_account_institution_id_fkey
ALTER TABLE catalog.platform_account
    ADD CONSTRAINT platform_account_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- ingest.account_metric_snapshot account_metric_snapshot_collection_run_id_fkey
ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_metric_snapshot_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.account_metric_snapshot account_metric_snapshot_platform_account_id_fkey
ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_metric_snapshot_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- ingest.collection_account_result collection_account_result_collection_run_id_fkey
ALTER TABLE ingest.collection_account_result
    ADD CONSTRAINT collection_account_result_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id) ON DELETE CASCADE;

-- ingest.collection_account_result collection_account_result_platform_account_id_fkey
ALTER TABLE ingest.collection_account_result
    ADD CONSTRAINT collection_account_result_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- ingest.deletion_observation deletion_observation_collection_run_id_fkey
ALTER TABLE ingest.deletion_observation
    ADD CONSTRAINT deletion_observation_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.deletion_observation deletion_observation_publication_id_fkey
ALTER TABLE ingest.deletion_observation
    ADD CONSTRAINT deletion_observation_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- ingest.evidence_quarantine evidence_quarantine_raw_payload_id_fkey
ALTER TABLE ingest.evidence_quarantine
    ADD CONSTRAINT evidence_quarantine_raw_payload_id_fkey FOREIGN KEY (raw_payload_id) REFERENCES ingest.raw_payload(id) ON DELETE CASCADE;

-- ingest.publication_availability_event publication_availability_event_collection_run_id_fkey
ALTER TABLE ingest.publication_availability_event
    ADD CONSTRAINT publication_availability_event_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.publication_availability_event publication_availability_event_publication_id_fkey
ALTER TABLE ingest.publication_availability_event
    ADD CONSTRAINT publication_availability_event_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- ingest.publication_availability_state publication_availability_state_last_collection_run_id_fkey
ALTER TABLE ingest.publication_availability_state
    ADD CONSTRAINT publication_availability_state_last_collection_run_id_fkey FOREIGN KEY (last_collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.publication_availability_state publication_availability_state_publication_id_fkey
ALTER TABLE ingest.publication_availability_state
    ADD CONSTRAINT publication_availability_state_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- ingest.publication publication_content_group_id_fkey
ALTER TABLE ingest.publication
    ADD CONSTRAINT publication_content_group_id_fkey FOREIGN KEY (content_group_id) REFERENCES ingest.content_group(id);

-- ingest.publication_identity publication_identity_platform_account_id_fkey
ALTER TABLE ingest.publication_identity
    ADD CONSTRAINT publication_identity_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- ingest.publication_identity publication_identity_publication_id_fkey
ALTER TABLE ingest.publication_identity
    ADD CONSTRAINT publication_identity_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id) ON DELETE CASCADE;

-- ingest.publication_metric_snapshot publication_metric_snapshot_collection_run_id_fkey
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_metric_snapshot_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.publication_metric_snapshot publication_metric_snapshot_publication_id_fkey
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_metric_snapshot_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- ingest.publication publication_primary_account_id_fkey
ALTER TABLE ingest.publication
    ADD CONSTRAINT publication_primary_account_id_fkey FOREIGN KEY (primary_account_id) REFERENCES catalog.platform_account(id);

-- ingest.raw_payload raw_payload_collection_run_id_fkey
ALTER TABLE ingest.raw_payload
    ADD CONSTRAINT raw_payload_collection_run_id_fkey FOREIGN KEY (collection_run_id) REFERENCES ingest.collection_run(id);

-- ingest.reaction_breakdown reaction_breakdown_snapshot_published_month_snapshot_id_fkey
ALTER TABLE ingest.reaction_breakdown
    ADD CONSTRAINT reaction_breakdown_snapshot_published_month_snapshot_id_fkey FOREIGN KEY (snapshot_published_month, snapshot_id) REFERENCES ingest.publication_metric_snapshot(published_month, id) ON DELETE CASCADE;

-- ingest.publication_metric_snapshot snapshot_evidence_dictionary_fk
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT snapshot_evidence_dictionary_fk FOREIGN KEY (metric_evidence_id) REFERENCES ingest.metric_evidence_dictionary(id) NOT VALID;

-- ops_and_admin.anomaly_analysis_candidate anomaly_analysis_candidate_publication_id_fkey
ALTER TABLE ops_and_admin.anomaly_analysis_candidate
    ADD CONSTRAINT anomaly_analysis_candidate_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES ingest.publication(id);

-- ops_and_admin.archive_object_attestation archive_object_attestation_manifest_id_fkey
ALTER TABLE ops_and_admin.archive_object_attestation
    ADD CONSTRAINT archive_object_attestation_manifest_id_fkey FOREIGN KEY (manifest_id) REFERENCES ops_and_admin.archive_manifest(id);

-- ops_and_admin.outbox_event outbox_event_dataset_revision_id_fkey
ALTER TABLE ops_and_admin.outbox_event
    ADD CONSTRAINT outbox_event_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- ops_and_admin.publication_partition_fence publication_partition_fence_manifest_id_fkey
ALTER TABLE ops_and_admin.publication_partition_fence
    ADD CONSTRAINT publication_partition_fence_manifest_id_fkey FOREIGN KEY (manifest_id) REFERENCES ops_and_admin.archive_manifest(id);

-- rating.formula_component formula_component_formula_definition_id_fkey
ALTER TABLE rating.formula_component
    ADD CONSTRAINT formula_component_formula_definition_id_fkey FOREIGN KEY (formula_definition_id) REFERENCES rating.formula_definition(id) ON DELETE CASCADE;

-- rating.official_account_rating_observation official_account_rating_observation_platform_account_id_fkey
ALTER TABLE rating.official_account_rating_observation
    ADD CONSTRAINT official_account_rating_observation_platform_account_id_fkey FOREIGN KEY (platform_account_id) REFERENCES catalog.platform_account(id);

-- rating.official_rating_observation official_rating_observation_institution_id_fkey
ALTER TABLE rating.official_rating_observation
    ADD CONSTRAINT official_rating_observation_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- rating.population_observation population_observation_institution_id_fkey
ALTER TABLE rating.population_observation
    ADD CONSTRAINT population_observation_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- rating.rating_component_result rating_component_result_formula_component_id_fkey
ALTER TABLE rating.rating_component_result
    ADD CONSTRAINT rating_component_result_formula_component_id_fkey FOREIGN KEY (formula_component_id) REFERENCES rating.formula_component(id);

-- rating.rating_component_result rating_component_result_rating_result_id_fkey
ALTER TABLE rating.rating_component_result
    ADD CONSTRAINT rating_component_result_rating_result_id_fkey FOREIGN KEY (rating_result_id) REFERENCES rating.rating_result(id) ON DELETE CASCADE;

-- rating.rating_result rating_result_institution_id_fkey
ALTER TABLE rating.rating_result
    ADD CONSTRAINT rating_result_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES catalog.institution(id);

-- rating.rating_result rating_result_rating_run_id_fkey
ALTER TABLE rating.rating_result
    ADD CONSTRAINT rating_result_rating_run_id_fkey FOREIGN KEY (rating_run_id) REFERENCES rating.rating_run(id) ON DELETE CASCADE;

-- rating.rating_run rating_run_dataset_revision_id_fkey
ALTER TABLE rating.rating_run
    ADD CONSTRAINT rating_run_dataset_revision_id_fkey FOREIGN KEY (dataset_revision_id) REFERENCES analytics.dataset_revision(id);

-- rating.rating_run rating_run_formula_definition_id_fkey
ALTER TABLE rating.rating_run
    ADD CONSTRAINT rating_run_formula_definition_id_fkey FOREIGN KEY (formula_definition_id) REFERENCES rating.formula_definition(id);
