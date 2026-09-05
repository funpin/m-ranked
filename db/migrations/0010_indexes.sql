-- 0010 — индексы — объявлены на родительских партиционированных таблицах
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.account_latest_revision_idx
CREATE INDEX account_latest_revision_idx ON analytics.account_latest USING btree (dataset_revision_id, metric_key, platform_account_id) INCLUDE (value, observed_at, quality);

-- analytics.anomaly_analysis_revision_publication_idx
CREATE INDEX anomaly_analysis_revision_publication_idx ON analytics.anomaly_analysis_revision USING btree (publication_id, id DESC);

-- analytics.anomaly_event_institution_time_idx
CREATE INDEX anomaly_event_institution_time_idx ON analytics.anomaly_event USING btree (institution_id, detected_at DESC);

-- analytics.anomaly_review_event_time_idx
CREATE INDEX anomaly_review_event_time_idx ON analytics.anomaly_review USING btree (anomaly_event_id, reviewed_at DESC);

-- analytics.comparison_cohort_member_institution_idx
CREATE INDEX comparison_cohort_member_institution_idx ON analytics.comparison_cohort_member USING btree (cohort_id, institution_id, publication_id);

-- analytics.dataset_revision_collection_run_unique_idx
CREATE UNIQUE INDEX dataset_revision_collection_run_unique_idx ON analytics.dataset_revision USING btree (source_run_id) WHERE ((cause = 'ingestion'::analytics.revision_cause) AND (source_run_id IS NOT NULL) AND ((metadata ->> 'revision_scope'::text) = 'collection_run'::text));

-- analytics.dataset_revision_committed_idx
CREATE INDEX dataset_revision_committed_idx ON analytics.dataset_revision USING btree (committed_at DESC, id DESC);

-- analytics.dataset_revision_correlation_idx
CREATE INDEX dataset_revision_correlation_idx ON analytics.dataset_revision USING btree (correlation_id);

-- analytics.institution_daily_metrics_query_idx
CREATE INDEX institution_daily_metrics_query_idx ON analytics.institution_daily_metrics USING btree (institution_id, platform, metric_day DESC, metric_key, aggregation, dataset_revision_id DESC);

-- analytics.institution_metric_aggregate_query_idx
CREATE INDEX institution_metric_aggregate_query_idx ON analytics.institution_metric_aggregate USING btree (institution_id, platform, metric_key, aggregation, window_end DESC, dataset_revision_id DESC);

-- analytics.institution_monthly_metrics_query_idx
CREATE INDEX institution_monthly_metrics_query_idx ON analytics.institution_monthly_metrics USING btree (institution_id, platform, metric_month DESC, metric_key, aggregation, dataset_revision_id DESC);

-- analytics.institution_period_metrics_query_idx
CREATE INDEX institution_period_metrics_query_idx ON analytics.institution_period_metrics USING btree (platform, period_key, metric_key, aggregation, as_of DESC, dataset_revision_id DESC, institution_id);

-- analytics.legacy_native_export_publication_idx
CREATE INDEX legacy_native_export_publication_idx ON analytics.legacy_native_export_lexeme USING btree (publication_id, snapshot_id DESC);

-- analytics.legacy_overview_account_revision_entity_idx
CREATE INDEX legacy_overview_account_revision_entity_idx ON analytics.legacy_overview_account USING btree (dataset_revision_id, platform, entity_id, "position");

-- analytics.legacy_overview_card_revision_scope_activity_idx
CREATE INDEX legacy_overview_card_revision_scope_activity_idx ON analytics.legacy_overview_card USING btree (dataset_revision_id, platform, period_key, median_reactions, total_reactions, total_views, entity_id);

-- analytics.legacy_overview_card_revision_scope_name_idx
CREATE INDEX legacy_overview_card_revision_scope_name_idx ON analytics.legacy_overview_card USING btree (dataset_revision_id, platform, period_key, sort_name, entity_id);

-- analytics.legacy_overview_card_revision_scope_rating_idx
CREATE INDEX legacy_overview_card_revision_scope_rating_idx ON analytics.legacy_overview_card USING btree (dataset_revision_id, platform, period_key, rating_rank, entity_id);

-- analytics.publication_analysis_attempt_retention_idx
CREATE INDEX publication_analysis_attempt_retention_idx ON analytics.publication_analysis_attempt USING btree (publication_id, status, completed_at DESC);

-- analytics.publication_analysis_state_public_idx
CREATE INDEX publication_analysis_state_public_idx ON analytics.publication_analysis_state USING btree (analysis_revision_id DESC, publication_id);

-- analytics.publication_anomaly_finding_attempt_key_idx
CREATE UNIQUE INDEX publication_anomaly_finding_attempt_key_idx ON analytics.publication_anomaly_finding USING btree (attempt_id, finding_key) WHERE (attempt_id IS NOT NULL);

-- analytics.publication_anomaly_finding_public_idx
CREATE INDEX publication_anomaly_finding_public_idx ON analytics.publication_anomaly_finding USING btree (publication_id, created_analysis_revision_id DESC, id);

-- analytics.publication_anomaly_review_effective_idx
CREATE INDEX publication_anomaly_review_effective_idx ON analytics.publication_anomaly_review USING btree (publication_id, finding_key, reviewed_at DESC, id DESC);

-- analytics.publication_content_revision_idx
CREATE INDEX publication_content_revision_idx ON analytics.publication_content USING btree (dataset_revision_id, publication_id);

-- analytics.publication_history_page_idx
CREATE INDEX publication_history_page_idx ON analytics.publication_history USING btree (dataset_revision_id, publication_id, observed_at DESC, snapshot_id DESC);

-- analytics.publication_latest_account_idx
CREATE INDEX publication_latest_account_idx ON analytics.publication_latest USING btree (platform_account_id, observed_at DESC, publication_id);

-- analytics.publication_latest_institution_platform_idx
CREATE INDEX publication_latest_institution_platform_idx ON analytics.publication_latest USING btree (institution_id, platform, observed_at DESC, publication_id);

-- catalog.account_external_identity_current_uq
CREATE UNIQUE INDEX account_external_identity_current_uq ON catalog.account_external_identity USING btree (platform_account_id, identity_namespace) WHERE (valid_to IS NULL);

-- catalog.account_external_identity_lookup_idx
CREATE INDEX account_external_identity_lookup_idx ON catalog.account_external_identity USING btree (identity_namespace, external_id, valid_from DESC);

-- catalog.account_identity_history_account_idx
CREATE INDEX account_identity_history_account_idx ON catalog.account_identity_history USING btree (platform_account_id, valid_from DESC);

-- catalog.account_identity_history_current_uq
CREATE UNIQUE INDEX account_identity_history_current_uq ON catalog.account_identity_history USING btree (platform_account_id) WHERE (valid_to IS NULL);

-- catalog.account_verification_account_time_idx
CREATE INDEX account_verification_account_time_idx ON catalog.account_verification USING btree (platform_account_id, verified_at DESC);

-- catalog.institution_external_id_current_uq
CREATE UNIQUE INDEX institution_external_id_current_uq ON catalog.institution_external_id USING btree (namespace, external_id) WHERE (valid_to IS NULL);

-- catalog.institution_external_id_institution_idx
CREATE INDEX institution_external_id_institution_idx ON catalog.institution_external_id USING btree (institution_id, valid_from DESC);

-- catalog.institution_status_name_idx
CREATE INDEX institution_status_name_idx ON catalog.institution USING btree (status, canonical_name, id);

-- catalog.legacy_entity_alias_target_idx
CREATE INDEX legacy_entity_alias_target_idx ON catalog.legacy_entity_alias USING btree (target_uuid, entity_type);

-- catalog.platform_account_active_canonical_uq
CREATE UNIQUE INDEX platform_account_active_canonical_uq ON catalog.platform_account USING btree (platform, canonical_external_id) WHERE (deleted_at IS NULL);

-- catalog.platform_account_institution_platform_idx
CREATE INDEX platform_account_institution_platform_idx ON catalog.platform_account USING btree (institution_id, platform, enabled, id);

-- ingest.account_metric_snapshot_account_observed_idx
CREATE INDEX account_metric_snapshot_account_observed_idx ON ingest.account_metric_snapshot USING btree (platform_account_id, observed_at DESC);

-- ingest.account_metric_snapshot_collected_brin
CREATE INDEX account_metric_snapshot_collected_brin ON ingest.account_metric_snapshot USING brin (collected_at);

-- ingest.collection_account_result_account_time_idx
CREATE INDEX collection_account_result_account_time_idx ON ingest.collection_account_result USING btree (platform_account_id, started_at DESC);

-- ingest.collection_run_correlation_idx
CREATE INDEX collection_run_correlation_idx ON ingest.collection_run USING btree (correlation_id);

-- ingest.collection_run_health_completed_idx
CREATE INDEX collection_run_health_completed_idx ON ingest.collection_run USING btree (platform, completed_at DESC, id DESC) WHERE ((collector_version !~~ 'sqlite-bridge/%'::text) AND (completed_at IS NOT NULL));

-- ingest.collection_run_health_latest_idx
CREATE INDEX collection_run_health_latest_idx ON ingest.collection_run USING btree (platform, started_at DESC, id DESC) WHERE (collector_version !~~ 'sqlite-bridge/%'::text);

-- ingest.collection_run_platform_started_idx
CREATE INDEX collection_run_platform_started_idx ON ingest.collection_run USING btree (platform, started_at DESC);

-- ingest.deletion_observation_publication_time_idx
CREATE INDEX deletion_observation_publication_time_idx ON ingest.deletion_observation USING btree (publication_id, observed_at DESC);

-- ingest.publication_account_published_idx
CREATE INDEX publication_account_published_idx ON ingest.publication USING btree (primary_account_id, published_at DESC, id);

-- ingest.publication_active_tracking_idx
CREATE INDEX publication_active_tracking_idx ON ingest.publication USING btree (published_at DESC, primary_account_id) WHERE (deleted_at IS NULL);

-- ingest.publication_content_group_idx
CREATE INDEX publication_content_group_idx ON ingest.publication USING btree (content_group_id) WHERE (content_group_id IS NOT NULL);

-- ingest.publication_identity_publication_idx
CREATE INDEX publication_identity_publication_idx ON ingest.publication_identity USING btree (publication_id, role, id);

-- ingest.publication_metric_snapshot_collected_brin
CREATE INDEX publication_metric_snapshot_collected_brin ON ingest.publication_metric_snapshot USING brin (collected_at);

-- ingest.publication_metric_snapshot_observed_brin
CREATE INDEX publication_metric_snapshot_observed_brin ON ingest.publication_metric_snapshot USING brin (observed_at);

-- ingest.publication_metric_snapshot_publication_observed_idx
CREATE INDEX publication_metric_snapshot_publication_observed_idx ON ingest.publication_metric_snapshot USING btree (publication_id, observed_at DESC, id DESC);

-- ingest.raw_payload_purge_idx
CREATE INDEX raw_payload_purge_idx ON ingest.raw_payload USING btree (purge_after, id);

-- ops_and_admin.anomaly_analysis_candidate_claim_idx
CREATE INDEX anomaly_analysis_candidate_claim_idx ON ops_and_admin.anomaly_analysis_candidate USING btree (priority DESC, eligible_at, publication_id) WHERE (claim_token IS NULL);

-- ops_and_admin.anomaly_analysis_candidate_lease_idx
CREATE INDEX anomaly_analysis_candidate_lease_idx ON ops_and_admin.anomaly_analysis_candidate USING btree (leased_until) WHERE (claim_token IS NOT NULL);

-- ops_and_admin.archive_manifest_lifecycle_idx
CREATE INDEX archive_manifest_lifecycle_idx ON ops_and_admin.archive_manifest USING btree (dataset_type, status, partition_end, id);

-- ops_and_admin.audit_log_subject_time_idx
CREATE INDEX audit_log_subject_time_idx ON ops_and_admin.audit_log USING btree (subject, occurred_at DESC);

-- ops_and_admin.audit_log_target_time_idx
CREATE INDEX audit_log_target_time_idx ON ops_and_admin.audit_log USING btree (target_type, target_id, occurred_at DESC);

-- ops_and_admin.operational_checkpoint_health_idx
CREATE INDEX operational_checkpoint_health_idx ON ops_and_admin.operational_checkpoint USING btree (checkpoint_key, source_observed_at DESC, updated_at DESC) WHERE (scope_type = ANY (ARRAY['system'::text, 'platform'::text]));

-- ops_and_admin.operational_checkpoint_lookup_idx
CREATE INDEX operational_checkpoint_lookup_idx ON ops_and_admin.operational_checkpoint USING btree (scope_type, scope_id, checkpoint_key);

-- ops_and_admin.outbox_event_class_pending_idx
CREATE INDEX outbox_event_class_pending_idx ON ops_and_admin.outbox_event USING btree (event_type, available_at, id) INCLUDE (occurred_at, publish_attempts) WHERE ((published_at IS NULL) AND (terminal_at IS NULL));

-- ops_and_admin.outbox_event_pending_idx
CREATE INDEX outbox_event_pending_idx ON ops_and_admin.outbox_event USING btree (available_at, id) WHERE (published_at IS NULL);

-- rating.formula_definition_one_published_effective_idx
CREATE UNIQUE INDEX formula_definition_one_published_effective_idx ON rating.formula_definition USING btree (formula_key, effective_from) WHERE (status = 'published'::rating.formula_status);

-- rating.official_account_rating_latest_idx
CREATE INDEX official_account_rating_latest_idx ON rating.official_account_rating_observation USING btree (platform_account_id, fetched_at DESC, id DESC);

-- rating.official_rating_observation_lookup_idx
CREATE INDEX official_rating_observation_lookup_idx ON rating.official_rating_observation USING btree (institution_id, category, period, fetched_at DESC);
