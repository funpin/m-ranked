-- 0007 — ops_and_admin — эксплуатация и аудит
-- Порождается из каталога эталонной базы; см. db/README.md.

-- ops_and_admin.anomaly_analysis_candidate
CREATE TABLE ops_and_admin.anomaly_analysis_candidate (
    publication_id uuid NOT NULL,
    dirty_generation bigint DEFAULT 1 NOT NULL,
    eligible_at timestamp with time zone NOT NULL,
    priority smallint DEFAULT 100 NOT NULL,
    config_backfill boolean DEFAULT false NOT NULL,
    claim_token uuid,
    claimed_generation bigint,
    leased_until timestamp with time zone,
    retry_count integer DEFAULT 0 NOT NULL,
    last_error_code text,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT anomaly_analysis_candidate_check CHECK ((((claim_token IS NULL) AND (claimed_generation IS NULL) AND (leased_until IS NULL)) OR ((claim_token IS NOT NULL) AND (claimed_generation IS NOT NULL) AND (leased_until IS NOT NULL)))),
    CONSTRAINT anomaly_analysis_candidate_dirty_generation_check CHECK ((dirty_generation > 0)),
    CONSTRAINT anomaly_analysis_candidate_last_error_code_check CHECK (((last_error_code IS NULL) OR (last_error_code ~ '^[a-z0-9_]{1,64}$'::text))),
    CONSTRAINT anomaly_analysis_candidate_retry_count_check CHECK (((retry_count >= 0) AND (retry_count <= 20)))
);

-- ops_and_admin.anomaly_command_receipt
CREATE TABLE ops_and_admin.anomaly_command_receipt (
    subject text NOT NULL,
    command_type text NOT NULL,
    idempotency_key uuid NOT NULL,
    request_digest text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT anomaly_command_receipt_command_type_check CHECK ((command_type = ANY (ARRAY['manual_signal'::text, 'review'::text]))),
    CONSTRAINT anomaly_command_receipt_request_digest_check CHECK ((request_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT anomaly_command_receipt_result_check CHECK (((jsonb_typeof(result) = 'object'::text) AND (pg_column_size(result) <= 4096)))
);

-- ops_and_admin.archive_manifest
CREATE TABLE ops_and_admin.archive_manifest (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_type text NOT NULL,
    schema_version integer NOT NULL,
    partition_start timestamp with time zone NOT NULL,
    partition_end timestamp with time zone NOT NULL,
    object_uri text NOT NULL,
    archive_format text DEFAULT 'parquet'::text NOT NULL,
    compression text DEFAULT 'zstandard'::text NOT NULL,
    sha256 text NOT NULL,
    row_count bigint NOT NULL,
    min_observed_at timestamp with time zone,
    max_observed_at timestamp with time zone,
    status ops_and_admin.archive_status DEFAULT 'staging'::ops_and_admin.archive_status NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    verified_at timestamp with time zone,
    hot_dropped_at timestamp with time zone,
    purge_after timestamp with time zone,
    verification_details jsonb DEFAULT '{}'::jsonb NOT NULL,
    canonical_sha256 text,
    CONSTRAINT archive_manifest_archive_format_check CHECK ((archive_format = 'parquet'::text)),
    CONSTRAINT archive_manifest_canonical_sha256_check CHECK ((canonical_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT archive_manifest_check CHECK ((partition_end > partition_start)),
    CONSTRAINT archive_manifest_check1 CHECK (((max_observed_at IS NULL) OR (min_observed_at IS NULL) OR (max_observed_at >= min_observed_at))),
    CONSTRAINT archive_manifest_check2 CHECK (((verified_at IS NULL) OR (verified_at >= created_at))),
    CONSTRAINT archive_manifest_check3 CHECK (((hot_dropped_at IS NULL) OR (verified_at IS NOT NULL))),
    CONSTRAINT archive_manifest_compression_check CHECK ((compression = 'zstandard'::text)),
    CONSTRAINT archive_manifest_dataset_type_check CHECK ((btrim(dataset_type) <> ''::text)),
    CONSTRAINT archive_manifest_object_uri_check CHECK ((btrim(object_uri) <> ''::text)),
    CONSTRAINT archive_manifest_row_count_check CHECK ((row_count >= 0)),
    CONSTRAINT archive_manifest_schema_version_check CHECK ((schema_version > 0)),
    CONSTRAINT archive_manifest_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT archive_manifest_verification_details_check CHECK ((jsonb_typeof(verification_details) = 'object'::text))
);

-- ops_and_admin.archive_object_attestation
CREATE TABLE ops_and_admin.archive_object_attestation (
    manifest_id uuid NOT NULL,
    object_uri text NOT NULL,
    object_version text NOT NULL,
    sha256 text NOT NULL,
    canonical_sha256 text NOT NULL,
    row_count bigint NOT NULL,
    failure_domain text NOT NULL,
    immutable_until timestamp with time zone NOT NULL,
    verified_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    verifier_subject text NOT NULL,
    CONSTRAINT archive_object_attestation_canonical_sha256_check CHECK ((canonical_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT archive_object_attestation_check CHECK ((immutable_until > verified_at)),
    CONSTRAINT archive_object_attestation_failure_domain_check CHECK (((btrim(failure_domain) <> ''::text) AND (failure_domain <> 'primary'::text))),
    CONSTRAINT archive_object_attestation_object_uri_check CHECK ((object_uri ~ '^(s3|gs|https)://'::text)),
    CONSTRAINT archive_object_attestation_object_version_check CHECK ((btrim(object_version) <> ''::text)),
    CONSTRAINT archive_object_attestation_row_count_check CHECK ((row_count >= 0)),
    CONSTRAINT archive_object_attestation_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT archive_object_attestation_verifier_subject_check CHECK ((btrim(verifier_subject) <> ''::text))
);

-- ops_and_admin.audit_log
CREATE TABLE ops_and_admin.audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    occurred_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    subject text NOT NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id uuid,
    correlation_id uuid NOT NULL,
    before_state jsonb,
    after_state jsonb,
    outcome text NOT NULL,
    CONSTRAINT audit_log_action_check CHECK ((btrim(action) <> ''::text)),
    CONSTRAINT audit_log_after_state_check CHECK (((after_state IS NULL) OR (jsonb_typeof(after_state) = 'object'::text))),
    CONSTRAINT audit_log_before_state_check CHECK (((before_state IS NULL) OR (jsonb_typeof(before_state) = 'object'::text))),
    CONSTRAINT audit_log_outcome_check CHECK ((btrim(outcome) <> ''::text)),
    CONSTRAINT audit_log_subject_check CHECK ((btrim(subject) <> ''::text)),
    CONSTRAINT audit_log_target_type_check CHECK ((btrim(target_type) <> ''::text))
);

-- ops_and_admin.catalog_command_receipt
CREATE TABLE ops_and_admin.catalog_command_receipt (
    actor text NOT NULL,
    correlation_id uuid NOT NULL,
    request_digest text NOT NULL,
    response jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT catalog_command_receipt_request_digest_check CHECK ((request_digest ~ '^[0-9a-f]{64}$'::text))
);

-- ops_and_admin.operational_checkpoint
CREATE TABLE ops_and_admin.operational_checkpoint (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    checkpoint_key text NOT NULL,
    scope_type text NOT NULL,
    scope_id uuid,
    platform catalog.platform_code,
    value jsonb NOT NULL,
    source_observed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    correlation_id uuid,
    CONSTRAINT operational_checkpoint_check CHECK ((((scope_type = 'system'::text) AND (scope_id IS NULL)) OR ((scope_type <> 'system'::text) AND (scope_id IS NOT NULL)))),
    CONSTRAINT operational_checkpoint_check1 CHECK ((((scope_type = 'platform'::text) AND (platform IS NOT NULL)) OR (scope_type <> 'platform'::text))),
    CONSTRAINT operational_checkpoint_checkpoint_key_check CHECK ((btrim(checkpoint_key) <> ''::text)),
    CONSTRAINT operational_checkpoint_scope_type_check CHECK ((scope_type = ANY (ARRAY['system'::text, 'platform'::text, 'account'::text]))),
    CONSTRAINT operational_checkpoint_value_check CHECK ((jsonb_typeof(value) = ANY (ARRAY['object'::text, 'array'::text, 'string'::text, 'number'::text, 'boolean'::text, 'null'::text])))
);

-- ops_and_admin.outbox_event
CREATE TABLE ops_and_admin.outbox_event (
    id bigint NOT NULL,
    dataset_revision_id bigint NOT NULL,
    event_type text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    affected_tags text[] DEFAULT ARRAY[]::text[] NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    available_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    published_at timestamp with time zone,
    publish_attempts integer DEFAULT 0 NOT NULL,
    last_error_code text,
    terminal_at timestamp with time zone,
    terminal_reason text,
    CONSTRAINT outbox_event_aggregate_id_check CHECK ((btrim(aggregate_id) <> ''::text)),
    CONSTRAINT outbox_event_aggregate_type_check CHECK ((btrim(aggregate_type) <> ''::text)),
    CONSTRAINT outbox_event_event_type_check CHECK ((btrim(event_type) <> ''::text)),
    CONSTRAINT outbox_event_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT outbox_event_publish_attempts_check CHECK ((publish_attempts >= 0)),
    CONSTRAINT outbox_terminal_state_complete CHECK ((((terminal_at IS NULL) AND (terminal_reason IS NULL)) OR ((terminal_at IS NOT NULL) AND (btrim(terminal_reason) <> ''::text))))
);

-- ops_and_admin.publication_partition_fence
CREATE TABLE ops_and_admin.publication_partition_fence (
    published_month date NOT NULL,
    state text DEFAULT 'active'::text NOT NULL,
    changed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    manifest_id uuid,
    CONSTRAINT publication_partition_fence_published_month_check CHECK ((published_month = (date_trunc('month'::text, (published_month)::timestamp with time zone))::date)),
    CONSTRAINT publication_partition_fence_state_check CHECK ((state = ANY (ARRAY['active'::text, 'archiving'::text, 'archived'::text])))
);

-- ops_and_admin.recovery_policy
CREATE TABLE ops_and_admin.recovery_policy (
    policy_name text NOT NULL,
    target_rpo interval NOT NULL,
    target_rto interval NOT NULL,
    daily_base_backup_points integer NOT NULL,
    weekly_backup_points integer NOT NULL,
    monthly_backup_points integer NOT NULL,
    automated_verification_interval interval NOT NULL,
    full_restore_drill_interval interval NOT NULL,
    encrypted_off_primary_copy_required boolean NOT NULL,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT recovery_policy_automated_verification_interval_check CHECK ((automated_verification_interval > '00:00:00'::interval)),
    CONSTRAINT recovery_policy_daily_base_backup_points_check CHECK ((daily_base_backup_points > 0)),
    CONSTRAINT recovery_policy_full_restore_drill_interval_check CHECK ((full_restore_drill_interval > '00:00:00'::interval)),
    CONSTRAINT recovery_policy_monthly_backup_points_check CHECK ((monthly_backup_points > 0)),
    CONSTRAINT recovery_policy_target_rpo_check CHECK ((target_rpo > '00:00:00'::interval)),
    CONSTRAINT recovery_policy_target_rto_check CHECK ((target_rto > '00:00:00'::interval)),
    CONSTRAINT recovery_policy_weekly_backup_points_check CHECK ((weekly_backup_points > 0))
);

-- ops_and_admin.retention_policy
CREATE TABLE ops_and_admin.retention_policy (
    data_class text NOT NULL,
    hot_days integer,
    retention_months integer,
    archive_required boolean NOT NULL,
    notes text NOT NULL,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT retention_policy_hot_days_check CHECK (((hot_days IS NULL) OR (hot_days >= 0))),
    CONSTRAINT retention_policy_retention_months_check CHECK (((retention_months IS NULL) OR (retention_months >= 0)))
);

-- ops_and_admin.storage_observation
CREATE TABLE ops_and_admin.storage_observation (
    observed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    database_size_bytes bigint NOT NULL,
    temporary_bytes bigint NOT NULL,
    wal_bytes numeric NOT NULL,
    largest_relations jsonb NOT NULL,
    row_estimates jsonb NOT NULL,
    CONSTRAINT storage_observation_database_size_bytes_check CHECK ((database_size_bytes >= 0)),
    CONSTRAINT storage_observation_largest_relations_check CHECK ((jsonb_typeof(largest_relations) = 'array'::text)),
    CONSTRAINT storage_observation_row_estimates_check CHECK ((jsonb_typeof(row_estimates) = 'object'::text)),
    CONSTRAINT storage_observation_temporary_bytes_check CHECK ((temporary_bytes >= 0)),
    CONSTRAINT storage_observation_wal_bytes_check CHECK ((wal_bytes >= (0)::numeric))
);
