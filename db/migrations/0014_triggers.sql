-- 0014 — триггеры
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.legacy_native_export_lexeme legacy_native_export_immutable
CREATE TRIGGER legacy_native_export_immutable BEFORE DELETE OR UPDATE ON analytics.legacy_native_export_lexeme FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- analytics.legacy_native_export_lexeme legacy_native_export_no_truncate
CREATE TRIGGER legacy_native_export_no_truncate BEFORE TRUNCATE ON analytics.legacy_native_export_lexeme FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();

-- analytics.legacy_period_policy legacy_period_policy_immutable
CREATE TRIGGER legacy_period_policy_immutable BEFORE DELETE OR UPDATE ON analytics.legacy_period_policy FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- analytics.legacy_period_policy legacy_period_policy_no_truncate
CREATE TRIGGER legacy_period_policy_no_truncate BEFORE TRUNCATE ON analytics.legacy_period_policy FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();

-- analytics.legacy_period_policy legacy_period_policy_revision_guard
CREATE TRIGGER legacy_period_policy_revision_guard BEFORE INSERT ON analytics.legacy_period_policy FOR EACH ROW EXECUTE FUNCTION analytics.guard_legacy_period_policy();

-- catalog.account_external_identity account_external_identity_immutable
CREATE TRIGGER account_external_identity_immutable BEFORE DELETE OR UPDATE ON catalog.account_external_identity FOR EACH ROW EXECUTE FUNCTION catalog.guard_account_identity_history();

-- catalog.account_identity_history account_identity_history_immutable
CREATE TRIGGER account_identity_history_immutable BEFORE DELETE OR UPDATE ON catalog.account_identity_history FOR EACH ROW EXECUTE FUNCTION catalog.guard_account_identity_history();

-- catalog.platform_account platform_account_canonical_identity_immutable
CREATE TRIGGER platform_account_canonical_identity_immutable BEFORE UPDATE ON catalog.platform_account FOR EACH ROW EXECUTE FUNCTION catalog.guard_canonical_account_identity();

-- ingest.publication_metric_snapshot anomaly_candidate_after_effective_snapshot
CREATE TRIGGER anomaly_candidate_after_effective_snapshot AFTER INSERT ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ops_and_admin.mark_anomaly_candidate();

-- ingest.publication_availability_event availability_event_immutable
CREATE TRIGGER availability_event_immutable BEFORE DELETE OR UPDATE ON ingest.publication_availability_event FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- ingest.metric_evidence_dictionary evidence_dictionary_immutable
CREATE TRIGGER evidence_dictionary_immutable BEFORE DELETE OR UPDATE ON ingest.metric_evidence_dictionary FOR EACH ROW EXECUTE FUNCTION ingest.reject_evidence_dictionary_mutation();

-- ingest.account_metric_snapshot observation_immutable
CREATE TRIGGER observation_immutable BEFORE DELETE OR UPDATE ON ingest.account_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- ingest.publication_metric_snapshot observation_immutable
CREATE TRIGGER observation_immutable BEFORE DELETE OR UPDATE ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- ingest.reaction_breakdown observation_immutable
CREATE TRIGGER observation_immutable BEFORE DELETE OR UPDATE ON ingest.reaction_breakdown FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- ingest.account_metric_snapshot observation_prepare
CREATE TRIGGER observation_prepare BEFORE INSERT ON ingest.account_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.prepare_immutable_account_snapshot();

-- ingest.publication_metric_snapshot observation_prepare
CREATE TRIGGER observation_prepare BEFORE INSERT ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.prepare_immutable_publication_snapshot();

-- ingest.publication_metric_snapshot publication_snapshot_month_guard
CREATE TRIGGER publication_snapshot_month_guard BEFORE INSERT OR UPDATE OF published_month, publication_id ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.assert_publication_snapshot_month();

-- ingest.raw_payload raw_payload_available
CREATE TRIGGER raw_payload_available BEFORE INSERT ON ingest.raw_payload FOR EACH ROW EXECUTE FUNCTION ingest.reject_new_unavailable_evidence();

-- ingest.reaction_breakdown reaction_fence
CREATE TRIGGER reaction_fence BEFORE INSERT ON ingest.reaction_breakdown FOR EACH ROW EXECUTE FUNCTION ingest.fence_reaction_insert();

-- ops_and_admin.archive_object_attestation attestation_immutable
CREATE TRIGGER attestation_immutable BEFORE DELETE OR UPDATE ON ops_and_admin.archive_object_attestation FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- ops_and_admin.audit_log audit_append_only
CREATE TRIGGER audit_append_only BEFORE DELETE OR UPDATE ON ops_and_admin.audit_log FOR EACH ROW EXECUTE FUNCTION ops_and_admin.reject_audit_mutation();

-- ops_and_admin.audit_log audit_no_truncate
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON ops_and_admin.audit_log FOR EACH STATEMENT EXECUTE FUNCTION ops_and_admin.reject_audit_mutation();

-- ops_and_admin.catalog_command_receipt catalog_command_receipt_immutable
CREATE TRIGGER catalog_command_receipt_immutable BEFORE DELETE OR UPDATE ON ops_and_admin.catalog_command_receipt FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- rating.formula_component formula_component_immutable
CREATE TRIGGER formula_component_immutable BEFORE INSERT OR DELETE OR UPDATE ON rating.formula_component FOR EACH ROW EXECUTE FUNCTION rating.reject_published_component_mutation();

-- rating.formula_definition formula_definition_immutable
CREATE TRIGGER formula_definition_immutable BEFORE DELETE OR UPDATE ON rating.formula_definition FOR EACH ROW EXECUTE FUNCTION rating.reject_published_formula_mutation();

-- rating.official_account_rating_observation official_account_rating_immutable
CREATE TRIGGER official_account_rating_immutable BEFORE DELETE OR UPDATE ON rating.official_account_rating_observation FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- rating.official_import official_import_immutable
CREATE TRIGGER official_import_immutable BEFORE DELETE OR UPDATE ON rating.official_import FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
