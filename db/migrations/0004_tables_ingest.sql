-- 0004 — ingest — сырые наблюдения и партиции
-- Порождается из каталога эталонной базы; см. db/README.md.

-- ingest.metric_evidence_dictionary
CREATE TABLE ingest.metric_evidence_dictionary (
    id integer NOT NULL,
    payload jsonb NOT NULL,
    payload_sha256 bytea NOT NULL,
    CONSTRAINT metric_evidence_dictionary_check CHECK ((payload_sha256 = sha256(convert_to((payload)::text, 'UTF8'::name)))),
    CONSTRAINT metric_evidence_dictionary_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text))
);

-- ingest.publication
CREATE TABLE ingest.publication (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    primary_account_id uuid NOT NULL,
    content_group_id uuid,
    published_at timestamp with time zone NOT NULL,
    discovered_at timestamp with time zone NOT NULL,
    first_observation_age_seconds integer,
    publication_type text NOT NULL,
    is_repost boolean DEFAULT false NOT NULL,
    history_completeness ingest.history_completeness NOT NULL,
    synthetic_baseline_allowed boolean DEFAULT false NOT NULL,
    quality_flags jsonb DEFAULT '{}'::jsonb NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_baseline_history_check CHECK (((NOT synthetic_baseline_allowed) OR (history_completeness = ANY (ARRAY['complete'::ingest.history_completeness, 'forced_incomplete'::ingest.history_completeness])))),
    CONSTRAINT publication_check CHECK (((deleted_at IS NULL) OR (deleted_at >= published_at))),
    CONSTRAINT publication_first_observation_age_seconds_check CHECK (((first_observation_age_seconds IS NULL) OR (first_observation_age_seconds >= 0))),
    CONSTRAINT publication_publication_type_check CHECK ((btrim(publication_type) <> ''::text)),
    CONSTRAINT publication_quality_flags_check CHECK ((jsonb_typeof(quality_flags) = 'object'::text))
);

-- ingest.publication_metric_snapshot
CREATE TABLE ingest.publication_metric_snapshot (
    published_month date NOT NULL,
    id bigint NOT NULL,
    publication_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    age_seconds integer NOT NULL,
    sampling_bucket bigint NOT NULL,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean DEFAULT false NOT NULL,
    synthetic boolean DEFAULT false NOT NULL,
    metric_semantics_version integer DEFAULT 1 NOT NULL,
    capability_version integer DEFAULT 1 NOT NULL,
    source_fingerprint text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    collected_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    ingested_xid xid8,
    correction_sequence bigint DEFAULT 0 NOT NULL,
    supersedes_snapshot_id bigint,
    correction_reason text,
    views_quality ingest.observation_quality NOT NULL,
    reactions_quality ingest.observation_quality NOT NULL,
    comments_quality ingest.observation_quality NOT NULL,
    shares_quality ingest.observation_quality NOT NULL,
    metric_evidence jsonb DEFAULT '{}'::jsonb,
    semantic_fingerprint bytea,
    metric_evidence_id integer,
    CONSTRAINT publication_metric_snapshot_age_seconds_check CHECK ((age_seconds >= 0)),
    CONSTRAINT publication_metric_snapshot_capability_version_check CHECK ((capability_version > 0)),
    CONSTRAINT publication_metric_snapshot_check CHECK (((sampling_bucket >= 0) OR synthetic)),
    CONSTRAINT publication_metric_snapshot_check1 CHECK (((NOT synthetic) OR (age_seconds = 0))),
    CONSTRAINT publication_metric_snapshot_collection_order_ck CHECK ((collected_at >= observed_at)),
    CONSTRAINT publication_metric_snapshot_comments_count_check CHECK (((comments_count IS NULL) OR (comments_count >= 0))),
    CONSTRAINT publication_metric_snapshot_correction_sequence_check CHECK ((correction_sequence >= 0)),
    CONSTRAINT publication_metric_snapshot_metric_evidence_check CHECK ((jsonb_typeof(metric_evidence) = 'object'::text)),
    CONSTRAINT publication_metric_snapshot_metric_semantics_version_check CHECK ((metric_semantics_version > 0)),
    CONSTRAINT publication_metric_snapshot_published_month_check CHECK ((published_month = (date_trunc('month'::text, (published_month)::timestamp with time zone))::date)),
    CONSTRAINT publication_metric_snapshot_reactions_count_check CHECK (((reactions_count IS NULL) OR (reactions_count >= 0))),
    CONSTRAINT publication_metric_snapshot_semantic_fingerprint_check CHECK (((semantic_fingerprint IS NULL) OR (octet_length(semantic_fingerprint) = 32))),
    CONSTRAINT publication_metric_snapshot_shares_count_check CHECK (((shares_count IS NULL) OR (shares_count >= 0))),
    CONSTRAINT publication_metric_snapshot_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text)),
    CONSTRAINT publication_metric_snapshot_views_count_check CHECK (((views_count IS NULL) OR (views_count >= 0))),
    CONSTRAINT publication_snapshot_correction_lineage CHECK ((((correction_sequence = 0) AND (supersedes_snapshot_id IS NULL) AND (correction_reason IS NULL)) OR ((correction_sequence > 0) AND (supersedes_snapshot_id IS NOT NULL) AND (btrim(correction_reason) <> ''::text))))
)
PARTITION BY RANGE (published_month);

-- ingest.account_metric_snapshot
CREATE TABLE ingest.account_metric_snapshot (
    id bigint NOT NULL,
    platform_account_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    subscriber_count bigint,
    subscriber_display text,
    quality ingest.observation_quality NOT NULL,
    source_fingerprint text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    collected_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    correction_sequence bigint DEFAULT 0 NOT NULL,
    supersedes_snapshot_id bigint,
    correction_reason text,
    subscriber_quality ingest.observation_quality NOT NULL,
    subscriber_source_field text DEFAULT 'subscriber_count'::text NOT NULL,
    subscriber_semantic_flags jsonb DEFAULT '{}'::jsonb NOT NULL,
    semantic_fingerprint bytea,
    CONSTRAINT account_metric_snapshot_collection_order_ck CHECK ((collected_at >= observed_at)),
    CONSTRAINT account_metric_snapshot_correction_sequence_check CHECK ((correction_sequence >= 0)),
    CONSTRAINT account_metric_snapshot_semantic_fingerprint_check CHECK (((semantic_fingerprint IS NULL) OR (octet_length(semantic_fingerprint) = 32))),
    CONSTRAINT account_metric_snapshot_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text)),
    CONSTRAINT account_metric_snapshot_subscriber_count_check CHECK (((subscriber_count IS NULL) OR (subscriber_count >= 0))),
    CONSTRAINT account_metric_snapshot_subscriber_semantic_flags_check CHECK ((jsonb_typeof(subscriber_semantic_flags) = 'object'::text)),
    CONSTRAINT account_snapshot_correction_lineage CHECK ((((correction_sequence = 0) AND (supersedes_snapshot_id IS NULL) AND (correction_reason IS NULL)) OR ((correction_sequence > 0) AND (supersedes_snapshot_id IS NOT NULL) AND (btrim(correction_reason) <> ''::text))))
);

-- ingest.collection_account_result
CREATE TABLE ingest.collection_account_result (
    id bigint NOT NULL,
    collection_run_id uuid NOT NULL,
    platform_account_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    status ingest.run_status NOT NULL,
    discovered_count integer DEFAULT 0 NOT NULL,
    snapshot_count integer DEFAULT 0 NOT NULL,
    sanitized_error_code text,
    semantic_changed boolean DEFAULT false NOT NULL,
    identity_source_receipt text,
    CONSTRAINT collection_account_result_check CHECK (((completed_at IS NULL) OR (completed_at >= started_at))),
    CONSTRAINT collection_account_result_discovered_count_check CHECK ((discovered_count >= 0)),
    CONSTRAINT collection_account_result_identity_source_receipt_check CHECK (((identity_source_receipt IS NULL) OR (identity_source_receipt ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT collection_account_result_snapshot_count_check CHECK ((snapshot_count >= 0))
);

-- ingest.collection_run
CREATE TABLE ingest.collection_run (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform catalog.platform_code NOT NULL,
    partition_key text NOT NULL,
    collector_version text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    status ingest.run_status NOT NULL,
    account_count integer DEFAULT 0 NOT NULL,
    error_count integer DEFAULT 0 NOT NULL,
    correlation_id uuid NOT NULL,
    scheduled_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT collection_run_account_count_check CHECK ((account_count >= 0)),
    CONSTRAINT collection_run_check CHECK (((completed_at IS NULL) OR (completed_at >= started_at))),
    CONSTRAINT collection_run_collector_version_check CHECK ((btrim(collector_version) <> ''::text)),
    CONSTRAINT collection_run_error_count_check CHECK ((error_count >= 0)),
    CONSTRAINT collection_run_partition_key_check CHECK ((btrim(partition_key) <> ''::text))
);

-- ingest.content_group
CREATE TABLE ingest.content_group (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    group_type text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT content_group_group_type_check CHECK ((btrim(group_type) <> ''::text))
);

-- ingest.deletion_observation
CREATE TABLE ingest.deletion_observation (
    id bigint NOT NULL,
    publication_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    outcome ingest.deletion_probe_outcome NOT NULL,
    reason_code text NOT NULL,
    consecutive_missing integer NOT NULL,
    CONSTRAINT deletion_observation_consecutive_missing_check CHECK ((consecutive_missing >= 0)),
    CONSTRAINT deletion_observation_reason_code_check CHECK ((btrim(reason_code) <> ''::text))
);

-- ingest.evidence_quarantine
CREATE TABLE ingest.evidence_quarantine (
    raw_payload_id uuid NOT NULL,
    reason_code text NOT NULL,
    quarantined_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT evidence_quarantine_reason_code_check CHECK ((reason_code ~ '^[A-Za-z][A-Za-z0-9_.:-]{0,159}$'::text))
);

-- ingest.publication_availability_event
CREATE TABLE ingest.publication_availability_event (
    publication_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    old_status ingest.deletion_probe_outcome,
    new_status ingest.deletion_probe_outcome NOT NULL,
    probe_outcome ingest.deletion_probe_outcome NOT NULL,
    reason_code text NOT NULL,
    consecutive_missing integer NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_availability_event_consecutive_missing_check CHECK ((consecutive_missing >= 0)),
    CONSTRAINT publication_availability_event_new_status_check CHECK ((new_status = ANY (ARRAY['present'::ingest.deletion_probe_outcome, 'missing'::ingest.deletion_probe_outcome, 'confirmed_deleted'::ingest.deletion_probe_outcome]))),
    CONSTRAINT publication_availability_event_old_status_check CHECK (((old_status IS NULL) OR (old_status = ANY (ARRAY['present'::ingest.deletion_probe_outcome, 'missing'::ingest.deletion_probe_outcome, 'confirmed_deleted'::ingest.deletion_probe_outcome])))),
    CONSTRAINT publication_availability_event_reason_code_check CHECK ((btrim(reason_code) <> ''::text))
);

-- ingest.publication_availability_state
CREATE TABLE ingest.publication_availability_state (
    publication_id uuid NOT NULL,
    status ingest.deletion_probe_outcome NOT NULL,
    last_probe_outcome ingest.deletion_probe_outcome NOT NULL,
    last_checked_at timestamp with time zone NOT NULL,
    last_present_at timestamp with time zone,
    first_missing_at timestamp with time zone,
    consecutive_missing integer NOT NULL,
    reason_code text NOT NULL,
    last_collection_run_id uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_availability_state_check CHECK ((((status = 'present'::ingest.deletion_probe_outcome) AND (consecutive_missing = 0) AND (first_missing_at IS NULL)) OR ((status = ANY (ARRAY['missing'::ingest.deletion_probe_outcome, 'confirmed_deleted'::ingest.deletion_probe_outcome])) AND (consecutive_missing > 0) AND (first_missing_at IS NOT NULL)))),
    CONSTRAINT publication_availability_state_check1 CHECK (((last_present_at IS NULL) OR (last_present_at <= last_checked_at))),
    CONSTRAINT publication_availability_state_check2 CHECK (((first_missing_at IS NULL) OR (first_missing_at <= last_checked_at))),
    CONSTRAINT publication_availability_state_consecutive_missing_check CHECK ((consecutive_missing >= 0)),
    CONSTRAINT publication_availability_state_reason_code_check CHECK ((btrim(reason_code) <> ''::text)),
    CONSTRAINT publication_availability_state_status_check CHECK ((status = ANY (ARRAY['present'::ingest.deletion_probe_outcome, 'missing'::ingest.deletion_probe_outcome, 'confirmed_deleted'::ingest.deletion_probe_outcome])))
)
WITH (fillfactor='80');

-- ingest.publication_identity
CREATE TABLE ingest.publication_identity (
    id bigint NOT NULL,
    publication_id uuid NOT NULL,
    platform_account_id uuid NOT NULL,
    external_id text NOT NULL,
    source_external_id text,
    role ingest.publication_account_role NOT NULL,
    public_url text,
    CONSTRAINT publication_identity_external_id_check CHECK ((btrim(external_id) <> ''::text)),
    CONSTRAINT publication_identity_public_url_check CHECK (((public_url IS NULL) OR (public_url ~ '^https://'::text)))
);

-- ingest.raw_payload
CREATE TABLE ingest.raw_payload (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    collection_run_id uuid NOT NULL,
    owner_type ingest.raw_owner_type NOT NULL,
    owner_id uuid NOT NULL,
    collected_at timestamp with time zone NOT NULL,
    sha256 text NOT NULL,
    content_encoding text NOT NULL,
    payload bytea,
    external_ref text,
    encryption_key_ref text,
    purge_after timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    legacy_evidence_unavailable boolean DEFAULT false NOT NULL,
    CONSTRAINT raw_payload_check CHECK (((payload IS NOT NULL) OR (external_ref IS NOT NULL))),
    CONSTRAINT raw_payload_check1 CHECK (((payload IS NULL) OR (encryption_key_ref IS NOT NULL))),
    CONSTRAINT raw_payload_check2 CHECK ((purge_after > collected_at)),
    CONSTRAINT raw_payload_content_encoding_check CHECK ((btrim(content_encoding) <> ''::text)),
    CONSTRAINT raw_payload_retrievable CHECK ((legacy_evidence_unavailable OR (payload IS NOT NULL) OR (external_ref ~ '^(file|s3|gs|https)://'::text))),
    CONSTRAINT raw_payload_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))
);

-- ingest.reaction_breakdown
CREATE TABLE ingest.reaction_breakdown (
    snapshot_published_month date NOT NULL,
    snapshot_id bigint NOT NULL,
    reaction_key text NOT NULL,
    reaction_count bigint NOT NULL,
    CONSTRAINT reaction_breakdown_reaction_count_check CHECK ((reaction_count >= 0)),
    CONSTRAINT reaction_breakdown_reaction_key_check CHECK ((btrim(reaction_key) <> ''::text))
)
PARTITION BY RANGE (snapshot_published_month);

-- ingest.default partitions
-- Страховочные партиции: ловят строки вне объявленных диапазонов,
-- чтобы вставка падала на проверке месяца, а не на отсутствии партиции.
CREATE TABLE ingest.publication_metric_snapshot_default
    PARTITION OF ingest.publication_metric_snapshot DEFAULT;

CREATE TABLE ingest.reaction_breakdown_default
    PARTITION OF ingest.reaction_breakdown DEFAULT;
