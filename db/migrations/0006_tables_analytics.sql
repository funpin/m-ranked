-- 0006 — analytics — производные данные и анализ
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.account_latest
CREATE TABLE analytics.account_latest (
    platform_account_id uuid NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    value bigint,
    observed_at timestamp with time zone NOT NULL,
    quality ingest.observation_quality NOT NULL,
    source_snapshot_id bigint NOT NULL,
    dataset_revision_id bigint NOT NULL,
    CONSTRAINT account_latest_metric_key_check CHECK ((metric_key = 'subscribers'::analytics.metric_key)),
    CONSTRAINT account_latest_value_check CHECK (((value IS NULL) OR (value >= 0)))
);

-- analytics.anomaly_analysis_revision
CREATE TABLE analytics.anomaly_analysis_revision (
    id bigint NOT NULL,
    publication_id uuid NOT NULL,
    reason text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT anomaly_analysis_revision_reason_check CHECK ((reason = ANY (ARRAY['automatic_success'::text, 'automatic_failure'::text, 'manual_signal'::text, 'review'::text])))
);

-- analytics.anomaly_event
CREATE TABLE analytics.anomaly_event (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    platform_account_id uuid,
    publication_id uuid,
    dataset_revision_id bigint NOT NULL,
    signal_type text NOT NULL,
    severity numeric NOT NULL,
    detected_at timestamp with time zone NOT NULL,
    detector_version text NOT NULL,
    evidence jsonb NOT NULL,
    status analytics.anomaly_status DEFAULT 'unreviewed'::analytics.anomaly_status NOT NULL,
    CONSTRAINT anomaly_event_detector_version_check CHECK ((btrim(detector_version) <> ''::text)),
    CONSTRAINT anomaly_event_evidence_check CHECK ((jsonb_typeof(evidence) = 'object'::text)),
    CONSTRAINT anomaly_event_signal_type_check CHECK ((btrim(signal_type) <> ''::text))
);

-- analytics.anomaly_review
CREATE TABLE analytics.anomaly_review (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    anomaly_event_id uuid NOT NULL,
    reviewer_subject text NOT NULL,
    decision analytics.review_decision NOT NULL,
    comment text,
    reviewed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT anomaly_review_reviewer_subject_check CHECK ((btrim(reviewer_subject) <> ''::text))
);

-- analytics.anomaly_source_revision
CREATE TABLE analytics.anomaly_source_revision (
    dataset_revision_id bigint NOT NULL,
    committed_at timestamp with time zone NOT NULL,
    pinned_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL
);

-- analytics.comparison_cohort
CREATE TABLE analytics.comparison_cohort (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform catalog.platform_code NOT NULL,
    horizon_seconds integer NOT NULL,
    as_of timestamp with time zone NOT NULL,
    filter_definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    sample_size integer NOT NULL,
    dataset_revision_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT comparison_cohort_filter_definition_check CHECK ((jsonb_typeof(filter_definition) = 'object'::text)),
    CONSTRAINT comparison_cohort_horizon_seconds_check CHECK ((horizon_seconds > 0)),
    CONSTRAINT comparison_cohort_sample_size_check CHECK ((sample_size >= 0))
);

-- analytics.comparison_cohort_member
CREATE TABLE analytics.comparison_cohort_member (
    cohort_id uuid NOT NULL,
    publication_id uuid NOT NULL,
    institution_id uuid NOT NULL
);

-- analytics.dataset_revision
CREATE TABLE analytics.dataset_revision (
    id bigint NOT NULL,
    committed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    cause analytics.revision_cause NOT NULL,
    correlation_id uuid NOT NULL,
    source_run_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT dataset_revision_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text))
);

-- analytics.institution_daily_metrics
CREATE TABLE analytics.institution_daily_metrics (
    id bigint NOT NULL,
    institution_id uuid NOT NULL,
    platform analytics.platform_scope NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    metric_day date NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    value numeric,
    sample_size integer NOT NULL,
    coverage numeric NOT NULL,
    quality ingest.observation_quality NOT NULL,
    as_of timestamp with time zone NOT NULL,
    dataset_revision_id bigint NOT NULL,
    CONSTRAINT institution_daily_metrics_check CHECK ((window_end > window_start)),
    CONSTRAINT institution_daily_metrics_check1 CHECK ((as_of >= window_end)),
    CONSTRAINT institution_daily_metrics_coverage_check CHECK (((coverage >= (0)::numeric) AND (coverage <= (1)::numeric))),
    CONSTRAINT institution_daily_metrics_sample_size_check CHECK ((sample_size >= 0))
);

-- analytics.institution_metric_aggregate
CREATE TABLE analytics.institution_metric_aggregate (
    id bigint NOT NULL,
    institution_id uuid NOT NULL,
    dataset_revision_id bigint NOT NULL,
    platform catalog.platform_code,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    as_of timestamp with time zone NOT NULL,
    value numeric,
    sample_size integer NOT NULL,
    coverage numeric NOT NULL,
    quality ingest.observation_quality NOT NULL,
    CONSTRAINT institution_metric_aggregate_check CHECK ((window_end > window_start)),
    CONSTRAINT institution_metric_aggregate_check1 CHECK ((as_of >= window_end)),
    CONSTRAINT institution_metric_aggregate_coverage_check CHECK (((coverage >= (0)::numeric) AND (coverage <= (1)::numeric))),
    CONSTRAINT institution_metric_aggregate_sample_size_check CHECK ((sample_size >= 0))
);

-- analytics.institution_monthly_metrics
CREATE TABLE analytics.institution_monthly_metrics (
    id bigint NOT NULL,
    institution_id uuid NOT NULL,
    platform analytics.platform_scope NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    metric_month date NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    value numeric,
    sample_size integer NOT NULL,
    coverage numeric NOT NULL,
    quality ingest.observation_quality NOT NULL,
    as_of timestamp with time zone NOT NULL,
    dataset_revision_id bigint NOT NULL,
    CONSTRAINT institution_monthly_metrics_check CHECK ((window_end > window_start)),
    CONSTRAINT institution_monthly_metrics_check1 CHECK ((as_of >= window_end)),
    CONSTRAINT institution_monthly_metrics_coverage_check CHECK (((coverage >= (0)::numeric) AND (coverage <= (1)::numeric))),
    CONSTRAINT institution_monthly_metrics_metric_month_check CHECK ((metric_month = (date_trunc('month'::text, (metric_month)::timestamp with time zone))::date)),
    CONSTRAINT institution_monthly_metrics_sample_size_check CHECK ((sample_size >= 0))
);

-- analytics.institution_period_metrics
CREATE TABLE analytics.institution_period_metrics (
    id bigint NOT NULL,
    institution_id uuid NOT NULL,
    platform catalog.platform_code,
    period_key text NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    value numeric,
    sample_size integer NOT NULL,
    coverage numeric NOT NULL,
    quality ingest.observation_quality NOT NULL,
    as_of timestamp with time zone NOT NULL,
    dataset_revision_id bigint NOT NULL,
    refreshed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT institution_period_metrics_check CHECK ((window_end > window_start)),
    CONSTRAINT institution_period_metrics_check1 CHECK ((as_of >= window_end)),
    CONSTRAINT institution_period_metrics_coverage_check CHECK (((coverage >= (0)::numeric) AND (coverage <= (1)::numeric))),
    CONSTRAINT institution_period_metrics_period_key_check CHECK ((period_key = ANY (ARRAY['3h'::text, '1d'::text, '7d'::text, '30d'::text]))),
    CONSTRAINT institution_period_metrics_sample_size_check CHECK ((sample_size >= 0))
);

-- analytics.legacy_overview_account
CREATE TABLE analytics.legacy_overview_account (
    dataset_revision_id bigint NOT NULL,
    platform analytics.platform_scope NOT NULL,
    entity_id uuid NOT NULL,
    "position" integer NOT NULL,
    account_id uuid NOT NULL,
    legacy_id bigint,
    legacy_route text,
    account_platform catalog.platform_code NOT NULL,
    canonical_external_id text NOT NULL,
    username text,
    title text,
    url text,
    access_mode catalog.access_mode NOT NULL,
    enabled boolean NOT NULL,
    subscriber_count bigint,
    subscriber_display text,
    subscriber_observed_at timestamp with time zone,
    latest_poll_started_at timestamp with time zone,
    latest_poll_completed_at timestamp with time zone,
    latest_poll_status ingest.run_status,
    latest_error_code text,
    last_checked_at timestamp with time zone,
    CONSTRAINT legacy_overview_account_legacy_id_check CHECK (((legacy_id IS NULL) OR (legacy_id > 0))),
    CONSTRAINT legacy_overview_account_position_check CHECK (("position" > 0)),
    CONSTRAINT legacy_overview_account_subscriber_count_check CHECK (((subscriber_count IS NULL) OR (subscriber_count >= 0))),
    CONSTRAINT legacy_overview_account_web_url CHECK (((url IS NULL) OR (url ~* '^https?://'::text)))
);

-- analytics.legacy_overview_card
CREATE TABLE analytics.legacy_overview_card (
    dataset_revision_id bigint NOT NULL,
    platform analytics.platform_scope NOT NULL,
    period_key text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    legacy_id bigint NOT NULL,
    legacy_route text,
    institution_id uuid NOT NULL,
    institution_legacy_id bigint NOT NULL,
    canonical_name text NOT NULL,
    short_name text,
    sort_name text NOT NULL,
    search_text text NOT NULL,
    account_count integer NOT NULL,
    enabled_account_count integer NOT NULL,
    connected_platform_count integer NOT NULL,
    subscriber_count bigint,
    last_checked_at timestamp with time zone,
    last_error_code text,
    status_code text NOT NULL,
    rating_rank integer,
    rating_score numeric,
    rating_period text,
    rating_fetched_at timestamp with time zone,
    total_publication_count bigint,
    activity_publication_count bigint,
    new_publication_count bigint,
    total_views numeric,
    median_views numeric,
    previous_total_views numeric,
    previous_median_views numeric,
    delta_total_views numeric,
    delta_median_views numeric,
    total_reactions numeric,
    median_reactions numeric,
    previous_total_reactions numeric,
    previous_median_reactions numeric,
    delta_total_reactions numeric,
    delta_median_reactions numeric,
    total_comments numeric,
    median_comments numeric,
    previous_total_comments numeric,
    previous_median_comments numeric,
    delta_total_comments numeric,
    delta_median_comments numeric,
    total_shares numeric,
    median_shares numeric,
    previous_total_shares numeric,
    previous_median_shares numeric,
    delta_total_shares numeric,
    delta_median_shares numeric,
    as_of timestamp with time zone NOT NULL,
    refreshed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    aggregate_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT legacy_overview_card_account_count_check CHECK ((account_count >= 0)),
    CONSTRAINT legacy_overview_card_activity_publication_count_check CHECK (((activity_publication_count IS NULL) OR (activity_publication_count >= 0))),
    CONSTRAINT legacy_overview_card_aggregate_metadata_check CHECK ((jsonb_typeof(aggregate_metadata) = 'object'::text)),
    CONSTRAINT legacy_overview_card_check CHECK (((platform = 'telegram'::analytics.platform_scope) = (entity_type = 'channels'::text))),
    CONSTRAINT legacy_overview_card_check1 CHECK (((platform <> 'all'::analytics.platform_scope) OR ((total_publication_count IS NULL) AND (activity_publication_count IS NULL) AND (new_publication_count IS NULL) AND (total_views IS NULL) AND (median_views IS NULL) AND (previous_total_views IS NULL) AND (previous_median_views IS NULL) AND (delta_total_views IS NULL) AND (delta_median_views IS NULL) AND (total_reactions IS NULL) AND (median_reactions IS NULL) AND (previous_total_reactions IS NULL) AND (previous_median_reactions IS NULL) AND (delta_total_reactions IS NULL) AND (delta_median_reactions IS NULL) AND (total_comments IS NULL) AND (median_comments IS NULL) AND (previous_total_comments IS NULL) AND (previous_median_comments IS NULL) AND (delta_total_comments IS NULL) AND (delta_median_comments IS NULL) AND (total_shares IS NULL) AND (median_shares IS NULL) AND (previous_total_shares IS NULL) AND (previous_median_shares IS NULL) AND (delta_total_shares IS NULL) AND (delta_median_shares IS NULL)))),
    CONSTRAINT legacy_overview_card_connected_platform_count_check CHECK (((connected_platform_count >= 0) AND (connected_platform_count <= 4))),
    CONSTRAINT legacy_overview_card_enabled_account_count_check CHECK ((enabled_account_count >= 0)),
    CONSTRAINT legacy_overview_card_entity_type_check CHECK ((entity_type = ANY (ARRAY['channels'::text, 'institutions'::text]))),
    CONSTRAINT legacy_overview_card_institution_legacy_id_check CHECK ((institution_legacy_id > 0)),
    CONSTRAINT legacy_overview_card_legacy_id_check CHECK ((legacy_id > 0)),
    CONSTRAINT legacy_overview_card_new_publication_count_check CHECK (((new_publication_count IS NULL) OR (new_publication_count >= 0))),
    CONSTRAINT legacy_overview_card_period_key_check CHECK ((period_key = ANY (ARRAY['3h'::text, '1d'::text, '7d'::text, '30d'::text]))),
    CONSTRAINT legacy_overview_card_rating_rank_check CHECK (((rating_rank IS NULL) OR (rating_rank > 0))),
    CONSTRAINT legacy_overview_card_status_code_check CHECK ((status_code = ANY (ARRAY['no_account'::text, 'all_accounts_disabled'::text, 'last_poll_failed'::text, 'polling'::text, 'awaiting_first_poll'::text, 'connected'::text]))),
    CONSTRAINT legacy_overview_card_subscriber_count_check CHECK (((subscriber_count IS NULL) OR (subscriber_count >= 0))),
    CONSTRAINT legacy_overview_card_total_publication_count_check CHECK (((total_publication_count IS NULL) OR (total_publication_count >= 0)))
);

-- analytics.legacy_period_policy
CREATE TABLE analytics.legacy_period_policy (
    effective_from_revision bigint NOT NULL,
    first_age_limit_seconds integer NOT NULL,
    reason text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT legacy_period_policy_effective_from_revision_check CHECK ((effective_from_revision >= 0)),
    CONSTRAINT legacy_period_policy_first_age_limit_seconds_check CHECK (((first_age_limit_seconds >= 0) AND (first_age_limit_seconds <= 86400))),
    CONSTRAINT legacy_period_policy_reason_check CHECK ((btrim(reason) <> ''::text))
);

-- analytics.metric_semantic_definition
CREATE TABLE analytics.metric_semantic_definition (
    metric_key analytics.metric_key NOT NULL,
    version integer NOT NULL,
    unit text NOT NULL,
    metric_kind text NOT NULL,
    aggregation_policy jsonb NOT NULL,
    reset_policy jsonb NOT NULL,
    missing_policy jsonb NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    retired_at timestamp with time zone,
    source_hash text NOT NULL,
    CONSTRAINT metric_semantic_definition_check CHECK (((retired_at IS NULL) OR (retired_at > effective_from))),
    CONSTRAINT metric_semantic_definition_metric_kind_check CHECK ((btrim(metric_kind) <> ''::text)),
    CONSTRAINT metric_semantic_definition_source_hash_check CHECK ((source_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT metric_semantic_definition_unit_check CHECK ((btrim(unit) <> ''::text)),
    CONSTRAINT metric_semantic_definition_version_check CHECK ((version > 0))
);

-- analytics.platform_metric_capability
CREATE TABLE analytics.platform_metric_capability (
    platform catalog.platform_code NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    capability_version integer NOT NULL,
    semantic_version integer NOT NULL,
    supported boolean NOT NULL,
    notes text,
    effective_from timestamp with time zone NOT NULL,
    retired_at timestamp with time zone,
    CONSTRAINT platform_metric_capability_capability_version_check CHECK ((capability_version > 0)),
    CONSTRAINT platform_metric_capability_check CHECK (((retired_at IS NULL) OR (retired_at > effective_from))),
    CONSTRAINT platform_metric_capability_semantic_version_check CHECK ((semantic_version > 0))
);

-- analytics.publication_analysis_attempt
CREATE TABLE analytics.publication_analysis_attempt (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    publication_id uuid NOT NULL,
    attempt_key uuid NOT NULL,
    status text NOT NULL,
    claimed_generation bigint NOT NULL,
    source_dataset_revision_id bigint CONSTRAINT publication_analysis_attemp_source_dataset_revision_id_not_null NOT NULL,
    source_revision_at timestamp with time zone NOT NULL,
    input_hash text,
    detector_manifest_hash text NOT NULL,
    preprocessing_version text NOT NULL,
    aggregator_version text NOT NULL,
    metric_semantics_version integer NOT NULL,
    capability_version integer NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    error_code text,
    analysis_revision_id bigint,
    CONSTRAINT publication_analysis_attempt_aggregator_version_check CHECK ((btrim(aggregator_version) <> ''::text)),
    CONSTRAINT publication_analysis_attempt_capability_version_check CHECK ((capability_version > 0)),
    CONSTRAINT publication_analysis_attempt_check CHECK ((completed_at >= started_at)),
    CONSTRAINT publication_analysis_attempt_check1 CHECK ((((status = 'succeeded'::text) AND (input_hash IS NOT NULL) AND (error_code IS NULL)) OR ((status = 'failed'::text) AND (error_code ~ '^[a-z0-9_]{1,64}$'::text)))),
    CONSTRAINT publication_analysis_attempt_claimed_generation_check CHECK ((claimed_generation > 0)),
    CONSTRAINT publication_analysis_attempt_detector_manifest_hash_check CHECK ((detector_manifest_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT publication_analysis_attempt_input_hash_check CHECK (((input_hash IS NULL) OR (input_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT publication_analysis_attempt_metric_semantics_version_check CHECK ((metric_semantics_version > 0)),
    CONSTRAINT publication_analysis_attempt_preprocessing_version_check CHECK ((btrim(preprocessing_version) <> ''::text)),
    CONSTRAINT publication_analysis_attempt_status_check CHECK ((status = ANY (ARRAY['succeeded'::text, 'failed'::text])))
);

-- analytics.publication_analysis_state
CREATE TABLE analytics.publication_analysis_state (
    publication_id uuid NOT NULL,
    analysis_revision_id bigint,
    current_success_attempt_id uuid,
    latest_failure_attempt_id uuid,
    status text DEFAULT 'pending'::text NOT NULL,
    suspicion_score numeric,
    automatic_severity text,
    affected_metrics analytics.metric_key[] DEFAULT ARRAY[]::analytics.metric_key[] NOT NULL,
    active_automatic_finding_count integer DEFAULT 0 CONSTRAINT publication_analysis_state_active_automatic_finding_co_not_null NOT NULL,
    source_dataset_revision_id bigint,
    source_revision_at timestamp with time zone,
    analyzed_at timestamp with time zone,
    input_hash text,
    detector_manifest_hash text,
    preprocessing_version text,
    aggregator_version text,
    CONSTRAINT publication_analysis_state_active_automatic_finding_count_check CHECK ((active_automatic_finding_count >= 0)),
    CONSTRAINT publication_analysis_state_automatic_severity_check CHECK (((automatic_severity IS NULL) OR (automatic_severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))),
    CONSTRAINT publication_analysis_state_check CHECK (((current_success_attempt_id IS NULL) = (analyzed_at IS NULL))),
    CONSTRAINT publication_analysis_state_check1 CHECK (((status <> 'ready'::text) OR (current_success_attempt_id IS NOT NULL))),
    CONSTRAINT publication_analysis_state_detector_manifest_hash_check CHECK (((detector_manifest_hash IS NULL) OR (detector_manifest_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT publication_analysis_state_input_hash_check CHECK (((input_hash IS NULL) OR (input_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT publication_analysis_state_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'ready'::text, 'partial'::text, 'stale'::text, 'failed'::text]))),
    CONSTRAINT publication_analysis_state_suspicion_score_check CHECK (((suspicion_score IS NULL) OR ((suspicion_score >= (0)::numeric) AND (suspicion_score <= (1)::numeric))))
);

-- analytics.publication_anomaly_finding
CREATE TABLE analytics.publication_anomaly_finding (
    id uuid NOT NULL,
    finding_key uuid NOT NULL,
    publication_id uuid NOT NULL,
    attempt_id uuid,
    created_analysis_revision_id bigint CONSTRAINT publication_anomaly_finding_created_analysis_revision__not_null NOT NULL,
    origin text NOT NULL,
    metric analytics.metric_key NOT NULL,
    detector_id text,
    detector_version text,
    suspicion_score numeric,
    severity text NOT NULL,
    explanation_code text NOT NULL,
    suspicious_start_at timestamp with time zone NOT NULL,
    suspicious_end_at timestamp with time zone NOT NULL,
    start_snapshot_id text,
    end_snapshot_id text,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_codes text[] DEFAULT ARRAY[]::text[] NOT NULL,
    alternative_explanation_codes text[] DEFAULT ARRAY[]::text[] CONSTRAINT publication_anomaly_finding_alternative_explanation_co_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_anomaly_finding_check CHECK ((suspicious_end_at > suspicious_start_at)),
    CONSTRAINT publication_anomaly_finding_check1 CHECK (((cardinality(quality_codes) <= 16) AND (cardinality(alternative_explanation_codes) <= 16))),
    CONSTRAINT publication_anomaly_finding_check2 CHECK ((((origin = 'automatic'::text) AND (attempt_id IS NOT NULL) AND (detector_id IS NOT NULL) AND (detector_version IS NOT NULL) AND ((suspicion_score >= (0)::numeric) AND (suspicion_score <= (1)::numeric))) OR ((origin = 'manual'::text) AND (attempt_id IS NULL) AND (detector_id IS NULL) AND (detector_version IS NULL) AND (suspicion_score IS NULL)))),
    CONSTRAINT publication_anomaly_finding_evidence_check CHECK (((jsonb_typeof(evidence) = 'object'::text) AND (pg_column_size(evidence) <= 8192))),
    CONSTRAINT publication_anomaly_finding_explanation_code_check CHECK ((explanation_code ~ '^[a-z0-9_]{1,80}$'::text)),
    CONSTRAINT publication_anomaly_finding_metric_check CHECK ((metric = ANY (ARRAY['views'::analytics.metric_key, 'reactions'::analytics.metric_key, 'comments'::analytics.metric_key, 'shares'::analytics.metric_key]))),
    CONSTRAINT publication_anomaly_finding_origin_check CHECK ((origin = ANY (ARRAY['automatic'::text, 'manual'::text]))),
    CONSTRAINT publication_anomaly_finding_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))
);

-- analytics.publication_anomaly_review
CREATE TABLE analytics.publication_anomaly_review (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    publication_id uuid NOT NULL,
    finding_key uuid NOT NULL,
    finding_id uuid NOT NULL,
    analysis_revision_id bigint NOT NULL,
    reviewer_subject text NOT NULL,
    decision analytics.review_decision NOT NULL,
    private_comment text,
    reviewed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_anomaly_review_private_comment_check CHECK (((private_comment IS NULL) OR (length(private_comment) <= 2000))),
    CONSTRAINT publication_anomaly_review_reviewer_subject_check CHECK (((btrim(reviewer_subject) <> ''::text) AND (length(reviewer_subject) <= 200)))
);

-- analytics.publication_content
CREATE TABLE analytics.publication_content (
    publication_id uuid NOT NULL,
    archived_text text,
    dataset_revision_id bigint NOT NULL
);

-- analytics.publication_history
CREATE TABLE analytics.publication_history (
    publication_id uuid NOT NULL,
    snapshot_id bigint NOT NULL,
    published_month date NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    age_seconds integer NOT NULL,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    views_quality ingest.observation_quality,
    reactions_quality ingest.observation_quality,
    comments_quality ingest.observation_quality,
    shares_quality ingest.observation_quality,
    delta_views bigint,
    delta_reactions bigint,
    delta_comments bigint,
    delta_shares bigint,
    reaction_breakdown jsonb DEFAULT '{}'::jsonb NOT NULL,
    synthetic boolean NOT NULL,
    interval_uncertain boolean NOT NULL,
    quality ingest.observation_quality NOT NULL,
    lineage jsonb NOT NULL,
    dataset_revision_id bigint NOT NULL,
    reaction_entries jsonb DEFAULT '[]'::jsonb NOT NULL,
    delta_reaction_breakdown jsonb,
    delta_reaction_entries jsonb,
    CONSTRAINT history_delta_reaction_entries_array CHECK (((delta_reaction_entries IS NULL) OR (jsonb_typeof(delta_reaction_entries) = 'array'::text))),
    CONSTRAINT history_delta_reaction_object CHECK (((delta_reaction_breakdown IS NULL) OR (jsonb_typeof(delta_reaction_breakdown) = 'object'::text))),
    CONSTRAINT history_reaction_entries_array CHECK ((jsonb_typeof(reaction_entries) = 'array'::text)),
    CONSTRAINT publication_history_lineage_check CHECK ((jsonb_typeof(lineage) = 'object'::text)),
    CONSTRAINT publication_history_reaction_breakdown_check CHECK ((jsonb_typeof(reaction_breakdown) = 'object'::text))
);

-- analytics.publication_latest
CREATE TABLE analytics.publication_latest (
    publication_id uuid NOT NULL,
    institution_id uuid NOT NULL,
    platform_account_id uuid NOT NULL,
    platform catalog.platform_code NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    views_count bigint,
    views_observed_at timestamp with time zone,
    views_quality ingest.observation_quality,
    reactions_count bigint,
    reactions_observed_at timestamp with time zone,
    reactions_quality ingest.observation_quality,
    comments_count bigint,
    comments_observed_at timestamp with time zone,
    comments_quality ingest.observation_quality,
    shares_count bigint,
    shares_observed_at timestamp with time zone,
    shares_quality ingest.observation_quality,
    quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean DEFAULT false NOT NULL,
    synthetic boolean DEFAULT false NOT NULL,
    history_completeness ingest.history_completeness NOT NULL,
    source_snapshot_refs jsonb DEFAULT '{}'::jsonb NOT NULL,
    dataset_revision_id bigint NOT NULL,
    refreshed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_latest_check CHECK (((views_count IS NULL) = (views_observed_at IS NULL))),
    CONSTRAINT publication_latest_check1 CHECK (((views_count IS NULL) = (views_quality IS NULL))),
    CONSTRAINT publication_latest_check2 CHECK (((reactions_count IS NULL) = (reactions_observed_at IS NULL))),
    CONSTRAINT publication_latest_check3 CHECK (((reactions_count IS NULL) = (reactions_quality IS NULL))),
    CONSTRAINT publication_latest_check4 CHECK (((comments_count IS NULL) = (comments_observed_at IS NULL))),
    CONSTRAINT publication_latest_check5 CHECK (((comments_count IS NULL) = (comments_quality IS NULL))),
    CONSTRAINT publication_latest_check6 CHECK (((shares_count IS NULL) = (shares_observed_at IS NULL))),
    CONSTRAINT publication_latest_check7 CHECK (((shares_count IS NULL) = (shares_quality IS NULL))),
    CONSTRAINT publication_latest_comments_count_check CHECK (((comments_count IS NULL) OR (comments_count >= 0))),
    CONSTRAINT publication_latest_reactions_count_check CHECK (((reactions_count IS NULL) OR (reactions_count >= 0))),
    CONSTRAINT publication_latest_shares_count_check CHECK (((shares_count IS NULL) OR (shares_count >= 0))),
    CONSTRAINT publication_latest_source_snapshot_refs_check CHECK ((jsonb_typeof(source_snapshot_refs) = 'object'::text)),
    CONSTRAINT publication_latest_views_count_check CHECK (((views_count IS NULL) OR (views_count >= 0)))
);
