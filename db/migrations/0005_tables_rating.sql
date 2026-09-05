-- 0005 — rating — формулы и результаты
-- Порождается из каталога эталонной базы; см. db/README.md.

-- rating.formula_component
CREATE TABLE rating.formula_component (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    formula_definition_id uuid NOT NULL,
    component_code text NOT NULL,
    numerator_metric analytics.metric_key NOT NULL,
    denominator_key text,
    weight numeric NOT NULL,
    normalization text NOT NULL,
    missing_policy text NOT NULL,
    minimum_quality ingest.observation_quality NOT NULL,
    CONSTRAINT formula_component_component_code_check CHECK ((btrim(component_code) <> ''::text)),
    CONSTRAINT formula_component_missing_policy_check CHECK ((btrim(missing_policy) <> ''::text)),
    CONSTRAINT formula_component_normalization_check CHECK ((btrim(normalization) <> ''::text))
);

-- rating.formula_definition
CREATE TABLE rating.formula_definition (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    formula_key text NOT NULL,
    version integer NOT NULL,
    status rating.formula_status DEFAULT 'draft'::rating.formula_status NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    definition jsonb NOT NULL,
    source_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    published_at timestamp with time zone,
    CONSTRAINT formula_definition_check CHECK (((status = ANY (ARRAY['published'::rating.formula_status, 'retired'::rating.formula_status])) = (published_at IS NOT NULL))),
    CONSTRAINT formula_definition_definition_check CHECK ((jsonb_typeof(definition) = 'object'::text)),
    CONSTRAINT formula_definition_formula_key_check CHECK ((btrim(formula_key) <> ''::text)),
    CONSTRAINT formula_definition_source_hash_check CHECK ((source_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT formula_definition_version_check CHECK ((version > 0))
);

-- rating.official_account_rating_observation
CREATE TABLE rating.official_account_rating_observation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform_account_id uuid CONSTRAINT official_account_rating_observatio_platform_account_id_not_null NOT NULL,
    period text NOT NULL,
    rank integer,
    score numeric,
    source_url text NOT NULL,
    source_hash text NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    CONSTRAINT official_account_rating_observation_rank_check CHECK (((rank IS NULL) OR (rank > 0))),
    CONSTRAINT official_account_rating_observation_source_hash_check CHECK ((source_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT official_account_rating_observation_source_url_check CHECK ((source_url ~ '^https://'::text))
);

-- rating.official_import
CREATE TABLE rating.official_import (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor text NOT NULL,
    correlation_id uuid NOT NULL,
    period text NOT NULL,
    source_url text NOT NULL,
    source_hash text NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    evidence jsonb NOT NULL,
    evidence_sha256 text NOT NULL,
    CONSTRAINT official_import_evidence_check CHECK ((jsonb_typeof(evidence) = 'object'::text)),
    CONSTRAINT official_import_source_hash_check CHECK ((source_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT official_import_source_url_check CHECK ((source_url ~ '^https://'::text))
);

-- rating.official_rating_observation
CREATE TABLE rating.official_rating_observation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    category text NOT NULL,
    period text NOT NULL,
    rank integer,
    score numeric,
    source_url text NOT NULL,
    source_hash text NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    entity_scope text DEFAULT 'institution'::text NOT NULL,
    CONSTRAINT official_rating_observation_category_check CHECK ((btrim(category) <> ''::text)),
    CONSTRAINT official_rating_observation_entity_scope_check CHECK ((entity_scope = ANY (ARRAY['institution'::text, 'legacy_account'::text]))),
    CONSTRAINT official_rating_observation_period_check CHECK ((btrim(period) <> ''::text)),
    CONSTRAINT official_rating_observation_rank_check CHECK (((rank IS NULL) OR (rank > 0))),
    CONSTRAINT official_rating_observation_source_hash_check CHECK ((source_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT official_rating_observation_source_url_check CHECK ((source_url ~ '^https://'::text))
);

-- rating.population_observation
CREATE TABLE rating.population_observation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    population_type text NOT NULL,
    value bigint NOT NULL,
    observed_for date NOT NULL,
    source_url text NOT NULL,
    quality ingest.observation_quality NOT NULL,
    imported_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT population_observation_population_type_check CHECK ((btrim(population_type) <> ''::text)),
    CONSTRAINT population_observation_source_url_check CHECK ((source_url ~ '^https://'::text)),
    CONSTRAINT population_observation_value_check CHECK ((value >= 0))
);

-- rating.rating_component_result
CREATE TABLE rating.rating_component_result (
    id bigint NOT NULL,
    rating_result_id uuid NOT NULL,
    formula_component_id uuid NOT NULL,
    numerator numeric,
    denominator numeric,
    normalized_value numeric,
    weighted_value numeric,
    warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT rating_component_result_warnings_check CHECK ((jsonb_typeof(warnings) = 'array'::text))
);

-- rating.rating_result
CREATE TABLE rating.rating_result (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    rating_run_id uuid NOT NULL,
    institution_id uuid NOT NULL,
    score numeric,
    rank integer,
    quality ingest.observation_quality NOT NULL,
    explanation jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT rating_result_explanation_check CHECK ((jsonb_typeof(explanation) = 'object'::text)),
    CONSTRAINT rating_result_rank_check CHECK (((rank IS NULL) OR (rank > 0)))
);

-- rating.rating_run
CREATE TABLE rating.rating_run (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    formula_definition_id uuid NOT NULL,
    dataset_revision_id bigint NOT NULL,
    as_of timestamp with time zone NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    status ingest.run_status NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    input_hash text NOT NULL,
    CONSTRAINT rating_run_check CHECK ((window_end > window_start)),
    CONSTRAINT rating_run_check1 CHECK ((as_of >= window_end)),
    CONSTRAINT rating_run_check2 CHECK (((completed_at IS NULL) OR (completed_at >= started_at))),
    CONSTRAINT rating_run_input_hash_check CHECK ((input_hash ~ '^[0-9a-f]{64}$'::text))
);
