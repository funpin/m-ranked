-- 0009 — ключи, уникальность, CHECK
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.account_latest account_latest_pkey
ALTER TABLE analytics.account_latest
    ADD CONSTRAINT account_latest_pkey PRIMARY KEY (platform_account_id, metric_key);

-- analytics.anomaly_analysis_revision anomaly_analysis_revision_pkey
ALTER TABLE analytics.anomaly_analysis_revision
    ADD CONSTRAINT anomaly_analysis_revision_pkey PRIMARY KEY (id);

-- analytics.anomaly_event anomaly_event_pkey
ALTER TABLE analytics.anomaly_event
    ADD CONSTRAINT anomaly_event_pkey PRIMARY KEY (id);

-- analytics.anomaly_review anomaly_review_pkey
ALTER TABLE analytics.anomaly_review
    ADD CONSTRAINT anomaly_review_pkey PRIMARY KEY (id);

-- analytics.anomaly_source_revision anomaly_source_revision_pkey
ALTER TABLE analytics.anomaly_source_revision
    ADD CONSTRAINT anomaly_source_revision_pkey PRIMARY KEY (dataset_revision_id);

-- analytics.comparison_cohort_member comparison_cohort_member_pkey
ALTER TABLE analytics.comparison_cohort_member
    ADD CONSTRAINT comparison_cohort_member_pkey PRIMARY KEY (cohort_id, publication_id);

-- analytics.comparison_cohort comparison_cohort_pkey
ALTER TABLE analytics.comparison_cohort
    ADD CONSTRAINT comparison_cohort_pkey PRIMARY KEY (id);

-- analytics.comparison_cohort comparison_cohort_platform_horizon_seconds_as_of_filter_def_key
ALTER TABLE analytics.comparison_cohort
    ADD CONSTRAINT comparison_cohort_platform_horizon_seconds_as_of_filter_def_key UNIQUE (platform, horizon_seconds, as_of, filter_definition, dataset_revision_id);

-- analytics.dataset_revision dataset_revision_pkey
ALTER TABLE analytics.dataset_revision
    ADD CONSTRAINT dataset_revision_pkey PRIMARY KEY (id);

-- analytics.institution_daily_metrics institution_daily_metrics_institution_id_platform_metric_ke_key
ALTER TABLE analytics.institution_daily_metrics
    ADD CONSTRAINT institution_daily_metrics_institution_id_platform_metric_ke_key UNIQUE (institution_id, platform, metric_key, aggregation, metric_day, dataset_revision_id);

-- analytics.institution_daily_metrics institution_daily_metrics_pkey
ALTER TABLE analytics.institution_daily_metrics
    ADD CONSTRAINT institution_daily_metrics_pkey PRIMARY KEY (id);

-- analytics.institution_metric_aggregate institution_metric_aggregate_institution_id_dataset_revisio_key
ALTER TABLE analytics.institution_metric_aggregate
    ADD CONSTRAINT institution_metric_aggregate_institution_id_dataset_revisio_key UNIQUE NULLS NOT DISTINCT (institution_id, dataset_revision_id, platform, metric_key, aggregation, window_start, window_end, as_of);

-- analytics.institution_metric_aggregate institution_metric_aggregate_pkey
ALTER TABLE analytics.institution_metric_aggregate
    ADD CONSTRAINT institution_metric_aggregate_pkey PRIMARY KEY (id);

-- analytics.institution_monthly_metrics institution_monthly_metrics_institution_id_platform_metric__key
ALTER TABLE analytics.institution_monthly_metrics
    ADD CONSTRAINT institution_monthly_metrics_institution_id_platform_metric__key UNIQUE (institution_id, platform, metric_key, aggregation, metric_month, dataset_revision_id);

-- analytics.institution_monthly_metrics institution_monthly_metrics_pkey
ALTER TABLE analytics.institution_monthly_metrics
    ADD CONSTRAINT institution_monthly_metrics_pkey PRIMARY KEY (id);

-- analytics.institution_period_metrics institution_period_metrics_institution_id_platform_period_k_key
ALTER TABLE analytics.institution_period_metrics
    ADD CONSTRAINT institution_period_metrics_institution_id_platform_period_k_key UNIQUE NULLS NOT DISTINCT (institution_id, platform, period_key, metric_key, aggregation, as_of, dataset_revision_id);

-- analytics.institution_period_metrics institution_period_metrics_pkey
ALTER TABLE analytics.institution_period_metrics
    ADD CONSTRAINT institution_period_metrics_pkey PRIMARY KEY (id);

-- analytics.legacy_native_export_lexeme legacy_native_export_lexeme_pkey
ALTER TABLE analytics.legacy_native_export_lexeme
    ADD CONSTRAINT legacy_native_export_lexeme_pkey PRIMARY KEY (published_month, snapshot_id);

-- analytics.legacy_overview_account legacy_overview_account_pkey
ALTER TABLE analytics.legacy_overview_account
    ADD CONSTRAINT legacy_overview_account_pkey PRIMARY KEY (platform, entity_id, account_id);

-- analytics.legacy_overview_account legacy_overview_account_platform_entity_id_position_key
ALTER TABLE analytics.legacy_overview_account
    ADD CONSTRAINT legacy_overview_account_platform_entity_id_position_key UNIQUE (platform, entity_id, "position");

-- analytics.legacy_overview_card legacy_overview_card_pkey
ALTER TABLE analytics.legacy_overview_card
    ADD CONSTRAINT legacy_overview_card_pkey PRIMARY KEY (platform, period_key, entity_id);

-- analytics.legacy_period_policy legacy_period_policy_pkey
ALTER TABLE analytics.legacy_period_policy
    ADD CONSTRAINT legacy_period_policy_pkey PRIMARY KEY (effective_from_revision);

-- analytics.metric_semantic_definition metric_semantic_definition_pkey
ALTER TABLE analytics.metric_semantic_definition
    ADD CONSTRAINT metric_semantic_definition_pkey PRIMARY KEY (metric_key, version);

-- analytics.platform_metric_capability platform_metric_capability_pkey
ALTER TABLE analytics.platform_metric_capability
    ADD CONSTRAINT platform_metric_capability_pkey PRIMARY KEY (platform, metric_key, capability_version);

-- analytics.publication_analysis_attempt publication_analysis_attempt_analysis_revision_id_key
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_analysis_revision_id_key UNIQUE (analysis_revision_id);

-- analytics.publication_analysis_attempt publication_analysis_attempt_pkey
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_pkey PRIMARY KEY (id);

-- analytics.publication_analysis_attempt publication_analysis_attempt_publication_id_attempt_key_key
ALTER TABLE analytics.publication_analysis_attempt
    ADD CONSTRAINT publication_analysis_attempt_publication_id_attempt_key_key UNIQUE (publication_id, attempt_key);

-- analytics.publication_analysis_state publication_analysis_state_current_success_attempt_id_key
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_current_success_attempt_id_key UNIQUE (current_success_attempt_id);

-- analytics.publication_analysis_state publication_analysis_state_latest_failure_attempt_id_key
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_latest_failure_attempt_id_key UNIQUE (latest_failure_attempt_id);

-- analytics.publication_analysis_state publication_analysis_state_pkey
ALTER TABLE analytics.publication_analysis_state
    ADD CONSTRAINT publication_analysis_state_pkey PRIMARY KEY (publication_id);

-- analytics.publication_anomaly_finding publication_anomaly_finding_pkey
ALTER TABLE analytics.publication_anomaly_finding
    ADD CONSTRAINT publication_anomaly_finding_pkey PRIMARY KEY (id);

-- analytics.publication_anomaly_review publication_anomaly_review_pkey
ALTER TABLE analytics.publication_anomaly_review
    ADD CONSTRAINT publication_anomaly_review_pkey PRIMARY KEY (id);

-- analytics.publication_content publication_content_pkey
ALTER TABLE analytics.publication_content
    ADD CONSTRAINT publication_content_pkey PRIMARY KEY (publication_id);

-- analytics.publication_history publication_history_pkey
ALTER TABLE analytics.publication_history
    ADD CONSTRAINT publication_history_pkey PRIMARY KEY (publication_id, published_month, snapshot_id);

-- analytics.publication_latest publication_latest_pkey
ALTER TABLE analytics.publication_latest
    ADD CONSTRAINT publication_latest_pkey PRIMARY KEY (publication_id);

-- catalog.account_external_identity account_external_identity_pkey
ALTER TABLE catalog.account_external_identity
    ADD CONSTRAINT account_external_identity_pkey PRIMARY KEY (id);

-- catalog.account_external_identity account_external_identity_platform_account_id_identity_name_key
ALTER TABLE catalog.account_external_identity
    ADD CONSTRAINT account_external_identity_platform_account_id_identity_name_key UNIQUE (platform_account_id, identity_namespace, external_id, valid_from);

-- catalog.account_identity_history account_identity_history_pkey
ALTER TABLE catalog.account_identity_history
    ADD CONSTRAINT account_identity_history_pkey PRIMARY KEY (id);

-- catalog.account_verification account_verification_pkey
ALTER TABLE catalog.account_verification
    ADD CONSTRAINT account_verification_pkey PRIMARY KEY (id);

-- catalog.institution_external_id institution_external_id_namespace_external_id_valid_from_key
ALTER TABLE catalog.institution_external_id
    ADD CONSTRAINT institution_external_id_namespace_external_id_valid_from_key UNIQUE (namespace, external_id, valid_from);

-- catalog.institution_external_id institution_external_id_pkey
ALTER TABLE catalog.institution_external_id
    ADD CONSTRAINT institution_external_id_pkey PRIMARY KEY (id);

-- catalog.institution institution_pkey
ALTER TABLE catalog.institution
    ADD CONSTRAINT institution_pkey PRIMARY KEY (id);

-- catalog.legacy_entity_alias legacy_entity_alias_entity_type_target_uuid_key
ALTER TABLE catalog.legacy_entity_alias
    ADD CONSTRAINT legacy_entity_alias_entity_type_target_uuid_key UNIQUE (entity_type, target_uuid);

-- catalog.legacy_entity_alias legacy_entity_alias_pkey
ALTER TABLE catalog.legacy_entity_alias
    ADD CONSTRAINT legacy_entity_alias_pkey PRIMARY KEY (entity_type, legacy_id);

-- catalog.platform_account platform_account_pkey
ALTER TABLE catalog.platform_account
    ADD CONSTRAINT platform_account_pkey PRIMARY KEY (id);

-- ingest.account_metric_snapshot account_metric_snapshot_pkey
ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_metric_snapshot_pkey PRIMARY KEY (id);

-- ingest.account_metric_snapshot account_metric_snapshot_platform_account_id_observed_at_sou_key
ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_metric_snapshot_platform_account_id_observed_at_sou_key UNIQUE (platform_account_id, observed_at, source_fingerprint);

-- ingest.account_metric_snapshot account_snapshot_correction_sequence
ALTER TABLE ingest.account_metric_snapshot
    ADD CONSTRAINT account_snapshot_correction_sequence UNIQUE (platform_account_id, observed_at, correction_sequence);

-- ingest.collection_account_result collection_account_result_collection_run_id_platform_accoun_key
ALTER TABLE ingest.collection_account_result
    ADD CONSTRAINT collection_account_result_collection_run_id_platform_accoun_key UNIQUE (collection_run_id, platform_account_id);

-- ingest.collection_account_result collection_account_result_pkey
ALTER TABLE ingest.collection_account_result
    ADD CONSTRAINT collection_account_result_pkey PRIMARY KEY (id);

-- ingest.collection_run collection_run_pkey
ALTER TABLE ingest.collection_run
    ADD CONSTRAINT collection_run_pkey PRIMARY KEY (id);

-- ingest.content_group content_group_pkey
ALTER TABLE ingest.content_group
    ADD CONSTRAINT content_group_pkey PRIMARY KEY (id);

-- ingest.deletion_observation deletion_observation_pkey
ALTER TABLE ingest.deletion_observation
    ADD CONSTRAINT deletion_observation_pkey PRIMARY KEY (id);

-- ingest.deletion_observation deletion_observation_publication_id_collection_run_id_obser_key
ALTER TABLE ingest.deletion_observation
    ADD CONSTRAINT deletion_observation_publication_id_collection_run_id_obser_key UNIQUE (publication_id, collection_run_id, observed_at);

-- ingest.evidence_quarantine evidence_quarantine_pkey
ALTER TABLE ingest.evidence_quarantine
    ADD CONSTRAINT evidence_quarantine_pkey PRIMARY KEY (raw_payload_id);

-- ingest.metric_evidence_dictionary metric_evidence_dictionary_payload_sha256_key
ALTER TABLE ingest.metric_evidence_dictionary
    ADD CONSTRAINT metric_evidence_dictionary_payload_sha256_key UNIQUE (payload_sha256);

-- ingest.metric_evidence_dictionary metric_evidence_dictionary_pkey
ALTER TABLE ingest.metric_evidence_dictionary
    ADD CONSTRAINT metric_evidence_dictionary_pkey PRIMARY KEY (id);

-- ingest.publication_availability_event publication_availability_event_pkey
ALTER TABLE ingest.publication_availability_event
    ADD CONSTRAINT publication_availability_event_pkey PRIMARY KEY (publication_id, collection_run_id, observed_at);

-- ingest.publication_availability_state publication_availability_state_pkey
ALTER TABLE ingest.publication_availability_state
    ADD CONSTRAINT publication_availability_state_pkey PRIMARY KEY (publication_id);

-- ingest.publication_identity publication_identity_pkey
ALTER TABLE ingest.publication_identity
    ADD CONSTRAINT publication_identity_pkey PRIMARY KEY (id);

-- ingest.publication_identity publication_identity_platform_account_id_external_id_key
ALTER TABLE ingest.publication_identity
    ADD CONSTRAINT publication_identity_platform_account_id_external_id_key UNIQUE (platform_account_id, external_id);

-- ingest.publication_metric_snapshot publication_metric_snapshot_pkey
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_metric_snapshot_pkey PRIMARY KEY (published_month, id);

-- ingest.publication_metric_snapshot publication_snapshot_exact_replay
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_snapshot_exact_replay UNIQUE (published_month, publication_id, sampling_bucket, source_fingerprint);

-- ingest.publication_metric_snapshot publication_snapshot_correction_sequence
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT publication_snapshot_correction_sequence UNIQUE (published_month, publication_id, sampling_bucket, correction_sequence);

-- ingest.publication publication_pkey
ALTER TABLE ingest.publication
    ADD CONSTRAINT publication_pkey PRIMARY KEY (id);

-- ingest.raw_payload raw_payload_collection_run_id_owner_type_owner_id_sha256_key
ALTER TABLE ingest.raw_payload
    ADD CONSTRAINT raw_payload_collection_run_id_owner_type_owner_id_sha256_key UNIQUE (collection_run_id, owner_type, owner_id, sha256);

-- ingest.raw_payload raw_payload_pkey
ALTER TABLE ingest.raw_payload
    ADD CONSTRAINT raw_payload_pkey PRIMARY KEY (id);

-- ingest.reaction_breakdown reaction_breakdown_pkey
ALTER TABLE ingest.reaction_breakdown
    ADD CONSTRAINT reaction_breakdown_pkey PRIMARY KEY (snapshot_published_month, snapshot_id, reaction_key);

-- ingest.publication_metric_snapshot snapshot_evidence_representation
ALTER TABLE ingest.publication_metric_snapshot
    ADD CONSTRAINT snapshot_evidence_representation CHECK ((((metric_evidence IS NOT NULL) AND (metric_evidence_id IS NULL)) OR ((metric_evidence IS NULL) AND (metric_evidence_id IS NOT NULL)))) NOT VALID;

-- ops_and_admin.anomaly_analysis_candidate anomaly_analysis_candidate_pkey
ALTER TABLE ops_and_admin.anomaly_analysis_candidate
    ADD CONSTRAINT anomaly_analysis_candidate_pkey PRIMARY KEY (publication_id);

-- ops_and_admin.anomaly_command_receipt anomaly_command_receipt_pkey
ALTER TABLE ops_and_admin.anomaly_command_receipt
    ADD CONSTRAINT anomaly_command_receipt_pkey PRIMARY KEY (subject, command_type, idempotency_key);

-- ops_and_admin.archive_manifest archive_manifest_dataset_type_partition_start_partition_end_key
ALTER TABLE ops_and_admin.archive_manifest
    ADD CONSTRAINT archive_manifest_dataset_type_partition_start_partition_end_key UNIQUE (dataset_type, partition_start, partition_end, sha256);

-- ops_and_admin.archive_manifest archive_manifest_pkey
ALTER TABLE ops_and_admin.archive_manifest
    ADD CONSTRAINT archive_manifest_pkey PRIMARY KEY (id);

-- ops_and_admin.archive_object_attestation archive_object_attestation_pkey
ALTER TABLE ops_and_admin.archive_object_attestation
    ADD CONSTRAINT archive_object_attestation_pkey PRIMARY KEY (manifest_id);

-- ops_and_admin.audit_log audit_log_pkey
ALTER TABLE ops_and_admin.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

-- ops_and_admin.catalog_command_receipt catalog_command_receipt_pkey
ALTER TABLE ops_and_admin.catalog_command_receipt
    ADD CONSTRAINT catalog_command_receipt_pkey PRIMARY KEY (actor, correlation_id);

-- ops_and_admin.operational_checkpoint operational_checkpoint_checkpoint_key_scope_type_scope_id_p_key
ALTER TABLE ops_and_admin.operational_checkpoint
    ADD CONSTRAINT operational_checkpoint_checkpoint_key_scope_type_scope_id_p_key UNIQUE NULLS NOT DISTINCT (checkpoint_key, scope_type, scope_id, platform);

-- ops_and_admin.operational_checkpoint operational_checkpoint_pkey
ALTER TABLE ops_and_admin.operational_checkpoint
    ADD CONSTRAINT operational_checkpoint_pkey PRIMARY KEY (id);

-- ops_and_admin.outbox_event outbox_event_dataset_revision_id_event_type_aggregate_type__key
ALTER TABLE ops_and_admin.outbox_event
    ADD CONSTRAINT outbox_event_dataset_revision_id_event_type_aggregate_type__key UNIQUE (dataset_revision_id, event_type, aggregate_type, aggregate_id);

-- ops_and_admin.outbox_event outbox_event_pkey
ALTER TABLE ops_and_admin.outbox_event
    ADD CONSTRAINT outbox_event_pkey PRIMARY KEY (id);

-- ops_and_admin.publication_partition_fence publication_partition_fence_pkey
ALTER TABLE ops_and_admin.publication_partition_fence
    ADD CONSTRAINT publication_partition_fence_pkey PRIMARY KEY (published_month);

-- ops_and_admin.recovery_policy recovery_policy_pkey
ALTER TABLE ops_and_admin.recovery_policy
    ADD CONSTRAINT recovery_policy_pkey PRIMARY KEY (policy_name);

-- ops_and_admin.retention_policy retention_policy_pkey
ALTER TABLE ops_and_admin.retention_policy
    ADD CONSTRAINT retention_policy_pkey PRIMARY KEY (data_class);

-- ops_and_admin.storage_observation storage_observation_pkey
ALTER TABLE ops_and_admin.storage_observation
    ADD CONSTRAINT storage_observation_pkey PRIMARY KEY (observed_at);

-- rating.formula_component formula_component_formula_definition_id_component_code_key
ALTER TABLE rating.formula_component
    ADD CONSTRAINT formula_component_formula_definition_id_component_code_key UNIQUE (formula_definition_id, component_code);

-- rating.formula_component formula_component_pkey
ALTER TABLE rating.formula_component
    ADD CONSTRAINT formula_component_pkey PRIMARY KEY (id);

-- rating.formula_definition formula_definition_formula_key_version_key
ALTER TABLE rating.formula_definition
    ADD CONSTRAINT formula_definition_formula_key_version_key UNIQUE (formula_key, version);

-- rating.formula_definition formula_definition_pkey
ALTER TABLE rating.formula_definition
    ADD CONSTRAINT formula_definition_pkey PRIMARY KEY (id);

-- rating.official_account_rating_observation official_account_rating_obser_platform_account_id_period_so_key
ALTER TABLE rating.official_account_rating_observation
    ADD CONSTRAINT official_account_rating_obser_platform_account_id_period_so_key UNIQUE (platform_account_id, period, source_hash);

-- rating.official_account_rating_observation official_account_rating_observation_pkey
ALTER TABLE rating.official_account_rating_observation
    ADD CONSTRAINT official_account_rating_observation_pkey PRIMARY KEY (id);

-- rating.official_import official_import_actor_correlation_id_key
ALTER TABLE rating.official_import
    ADD CONSTRAINT official_import_actor_correlation_id_key UNIQUE (actor, correlation_id);

-- rating.official_import official_import_pkey
ALTER TABLE rating.official_import
    ADD CONSTRAINT official_import_pkey PRIMARY KEY (id);

-- rating.official_rating_observation official_rating_observation_institution_id_category_period__key
ALTER TABLE rating.official_rating_observation
    ADD CONSTRAINT official_rating_observation_institution_id_category_period__key UNIQUE (institution_id, category, period, source_hash);

-- rating.official_rating_observation official_rating_observation_pkey
ALTER TABLE rating.official_rating_observation
    ADD CONSTRAINT official_rating_observation_pkey PRIMARY KEY (id);

-- rating.population_observation population_observation_institution_id_population_type_obser_key
ALTER TABLE rating.population_observation
    ADD CONSTRAINT population_observation_institution_id_population_type_obser_key UNIQUE (institution_id, population_type, observed_for, source_url);

-- rating.population_observation population_observation_pkey
ALTER TABLE rating.population_observation
    ADD CONSTRAINT population_observation_pkey PRIMARY KEY (id);

-- rating.rating_component_result rating_component_result_pkey
ALTER TABLE rating.rating_component_result
    ADD CONSTRAINT rating_component_result_pkey PRIMARY KEY (id);

-- rating.rating_component_result rating_component_result_rating_result_id_formula_component__key
ALTER TABLE rating.rating_component_result
    ADD CONSTRAINT rating_component_result_rating_result_id_formula_component__key UNIQUE (rating_result_id, formula_component_id);

-- rating.rating_result rating_result_pkey
ALTER TABLE rating.rating_result
    ADD CONSTRAINT rating_result_pkey PRIMARY KEY (id);

-- rating.rating_result rating_result_rating_run_id_institution_id_key
ALTER TABLE rating.rating_result
    ADD CONSTRAINT rating_result_rating_run_id_institution_id_key UNIQUE (rating_run_id, institution_id);

-- rating.rating_run rating_run_formula_definition_id_dataset_revision_id_as_of__key
ALTER TABLE rating.rating_run
    ADD CONSTRAINT rating_run_formula_definition_id_dataset_revision_id_as_of__key UNIQUE (formula_definition_id, dataset_revision_id, as_of, input_hash);

-- rating.rating_run rating_run_pkey
ALTER TABLE rating.rating_run
    ADD CONSTRAINT rating_run_pkey PRIMARY KEY (id);
