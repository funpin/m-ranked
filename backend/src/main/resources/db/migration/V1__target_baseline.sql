-- M-Ranked target PostgreSQL baseline.
--
-- Flyway must connect as migration_owner (or a bootstrap role allowed to SET ROLE).
-- Runtime roles are provisioned outside Flyway by infra/postgres/init/001-create-roles.sh.

DO $guard$
DECLARE
    missing_roles text[];
BEGIN
    SELECT array_agg(required.role_name ORDER BY required.role_name)
      INTO missing_roles
      FROM unnest(ARRAY[
          'migration_owner', 'api_read', 'api_write_admin', 'collector_ingest',
          'backup', 'migration_bridge', 'maintenance'
      ]::text[]) AS required(role_name)
     WHERE NOT EXISTS (
         SELECT 1 FROM pg_roles WHERE rolname = required.role_name
     );
    IF missing_roles IS NOT NULL THEN
        RAISE EXCEPTION 'database roles must be provisioned before Flyway runs: %', missing_roles;
    END IF;
END
$guard$;

SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '5min';
SET client_min_messages = warning;

CREATE SCHEMA catalog AUTHORIZATION migration_owner;
CREATE SCHEMA ingest AUTHORIZATION migration_owner;
CREATE SCHEMA analytics AUTHORIZATION migration_owner;
CREATE SCHEMA rating AUTHORIZATION migration_owner;
CREATE SCHEMA ops_and_admin AUTHORIZATION migration_owner;
CREATE SCHEMA migration AUTHORIZATION migration_owner;

REVOKE ALL ON SCHEMA catalog, ingest, analytics, rating, ops_and_admin, migration FROM PUBLIC;

CREATE TYPE catalog.institution_status AS ENUM ('active', 'inactive', 'merged');
CREATE TYPE catalog.platform_code AS ENUM ('telegram', 'vk', 'max', 'rutube');
CREATE TYPE catalog.access_mode AS ENUM (
    'public_web',
    'telegram_web',
    'mtproto',
    'official_api',
    'public_api',
    'user_session',
    'disabled'
);
CREATE TYPE catalog.verification_status AS ENUM (
    'unverified', 'pending', 'verified', 'rejected', 'expired'
);

CREATE TYPE ingest.run_status AS ENUM (
    'pending', 'running', 'succeeded', 'partial', 'failed', 'skipped', 'cancelled'
);
CREATE TYPE ingest.observation_quality AS ENUM (
    'unknown', 'rounded', 'estimated', 'exact', 'degraded', 'suspected_reset', 'invalid'
);
CREATE TYPE ingest.history_completeness AS ENUM ('complete', 'incomplete', 'forced_incomplete');
CREATE TYPE ingest.publication_account_role AS ENUM (
    'primary', 'album_member', 'joint_author', 'source', 'repost_source'
);
CREATE TYPE ingest.deletion_probe_outcome AS ENUM (
    'present', 'missing', 'transient_error', 'confirmed_deleted', 'unsupported'
);
CREATE TYPE ingest.raw_owner_type AS ENUM ('account', 'publication', 'snapshot', 'run', 'migration');

CREATE TYPE analytics.revision_cause AS ENUM (
    'ingestion', 'correction', 'configuration', 'analytics', 'migration', 'retention'
);
CREATE TYPE analytics.metric_key AS ENUM (
    'views', 'reactions', 'comments', 'shares', 'subscribers', 'interactions'
);
CREATE TYPE analytics.aggregation_code AS ENUM (
    'sum', 'median', 'mean', 'minimum', 'maximum', 'count', 'rate', 'percentile'
);
CREATE TYPE analytics.platform_scope AS ENUM ('all', 'telegram', 'vk', 'max', 'rutube');
CREATE TYPE analytics.anomaly_status AS ENUM (
    'unreviewed', 'explained', 'unresolved', 'data_error', 'dismissed', 'superseded'
);
CREATE TYPE analytics.review_decision AS ENUM ('explained', 'unresolved', 'data_error', 'dismissed');
CREATE TYPE analytics.projection_status AS ENUM ('ready', 'rebuilding', 'failed');

CREATE TYPE rating.formula_status AS ENUM ('draft', 'in_review', 'published', 'retired');

CREATE TYPE ops_and_admin.archive_status AS ENUM (
    'staging', 'verified', 'hot_dropped', 'expired', 'failed'
);

CREATE TYPE migration.batch_status AS ENUM (
    'pending', 'running', 'succeeded', 'failed', 'cancelled', 'dry_run'
);
CREATE TYPE migration.reconciliation_status AS ENUM ('pass', 'warning', 'fail');

-- ---------------------------------------------------------------------------
-- Catalog
-- ---------------------------------------------------------------------------

CREATE TABLE catalog.institution (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name text NOT NULL CHECK (btrim(canonical_name) <> ''),
    short_name text CHECK (short_name IS NULL OR btrim(short_name) <> ''),
    status catalog.institution_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    row_version bigint NOT NULL DEFAULT 0 CHECK (row_version >= 0),
    CHECK (updated_at >= created_at)
);

CREATE INDEX institution_status_name_idx
    ON catalog.institution (status, canonical_name, id);

CREATE TABLE catalog.institution_external_id (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    namespace text NOT NULL CHECK (btrim(namespace) <> ''),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    verified_at timestamptz,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (namespace, external_id, valid_from)
);

CREATE UNIQUE INDEX institution_external_id_current_uq
    ON catalog.institution_external_id (namespace, external_id)
    WHERE valid_to IS NULL;
CREATE INDEX institution_external_id_institution_idx
    ON catalog.institution_external_id (institution_id, valid_from DESC);

CREATE TABLE catalog.platform_account (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform catalog.platform_code NOT NULL,
    canonical_external_id text NOT NULL CHECK (btrim(canonical_external_id) <> ''),
    current_username text,
    current_title text,
    current_url text,
    access_mode catalog.access_mode NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    row_version bigint NOT NULL DEFAULT 0 CHECK (row_version >= 0),
    CHECK (current_url IS NULL OR current_url ~ '^https://'),
    CHECK (updated_at >= created_at),
    UNIQUE (platform, canonical_external_id)
);

CREATE INDEX platform_account_institution_platform_idx
    ON catalog.platform_account (institution_id, platform, enabled, id);

CREATE TABLE catalog.account_identity_history (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    username text,
    title text,
    url text,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    source_run_id uuid,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (url IS NULL OR url ~ '^https://')
);

CREATE INDEX account_identity_history_account_idx
    ON catalog.account_identity_history (platform_account_id, valid_from DESC);
CREATE UNIQUE INDEX account_identity_history_current_uq
    ON catalog.account_identity_history (platform_account_id)
    WHERE valid_to IS NULL;

-- Native/platform identifiers have their own validity history.  Usernames and
-- presentation metadata belong to account_identity_history and must not be
-- mistaken for durable native IDs during migration.
CREATE TABLE catalog.account_external_identity (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    identity_namespace text NOT NULL CHECK (btrim(identity_namespace) <> ''),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    verified_at timestamptz,
    source_run_id uuid,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (platform_account_id, identity_namespace, external_id, valid_from)
);

CREATE UNIQUE INDEX account_external_identity_current_uq
    ON catalog.account_external_identity (platform_account_id, identity_namespace)
    WHERE valid_to IS NULL;
CREATE INDEX account_external_identity_lookup_idx
    ON catalog.account_external_identity (identity_namespace, external_id, valid_from DESC);

CREATE TABLE catalog.account_verification (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    status catalog.verification_status NOT NULL,
    method text NOT NULL CHECK (btrim(method) <> ''),
    evidence_url text,
    verified_by_subject text,
    verified_at timestamptz NOT NULL,
    expires_at timestamptz,
    CHECK (evidence_url IS NULL OR evidence_url ~ '^https://'),
    CHECK (expires_at IS NULL OR expires_at > verified_at)
);

CREATE INDEX account_verification_account_time_idx
    ON catalog.account_verification (platform_account_id, verified_at DESC);

-- Stable compatibility mapping for public integer URL contracts.  target_uuid is
-- deliberately polymorphic; entity_type is validated and route resolution must
-- additionally verify the target table.
CREATE TABLE catalog.legacy_entity_alias (
    entity_type text NOT NULL CHECK (
        entity_type IN ('institutions', 'channels', 'platform_accounts', 'posts', 'platform_posts')
    ),
    legacy_id bigint NOT NULL CHECK (legacy_id > 0),
    target_uuid uuid NOT NULL,
    legacy_route text,
    source_hash text CHECK (source_hash IS NULL OR source_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (entity_type, legacy_id),
    UNIQUE (entity_type, target_uuid)
);

CREATE INDEX legacy_entity_alias_target_idx
    ON catalog.legacy_entity_alias (target_uuid, entity_type);

-- ---------------------------------------------------------------------------
-- Ingestion source of truth
-- ---------------------------------------------------------------------------

CREATE TABLE ingest.collection_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform catalog.platform_code NOT NULL,
    partition_key text NOT NULL CHECK (btrim(partition_key) <> ''),
    collector_version text NOT NULL CHECK (btrim(collector_version) <> ''),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status ingest.run_status NOT NULL,
    account_count integer NOT NULL DEFAULT 0 CHECK (account_count >= 0),
    error_count integer NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    correlation_id uuid NOT NULL,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX collection_run_platform_started_idx
    ON ingest.collection_run (platform, started_at DESC);
CREATE INDEX collection_run_correlation_idx
    ON ingest.collection_run (correlation_id);

ALTER TABLE catalog.account_identity_history
    ADD CONSTRAINT account_identity_history_source_run_fk
    FOREIGN KEY (source_run_id) REFERENCES ingest.collection_run(id);

ALTER TABLE catalog.account_external_identity
    ADD CONSTRAINT account_external_identity_source_run_fk
    FOREIGN KEY (source_run_id) REFERENCES ingest.collection_run(id);

CREATE TABLE ingest.collection_account_result (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id) ON DELETE CASCADE,
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status ingest.run_status NOT NULL,
    discovered_count integer NOT NULL DEFAULT 0 CHECK (discovered_count >= 0),
    snapshot_count integer NOT NULL DEFAULT 0 CHECK (snapshot_count >= 0),
    sanitized_error_code text,
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    UNIQUE (collection_run_id, platform_account_id)
);

CREATE INDEX collection_account_result_account_time_idx
    ON ingest.collection_account_result (platform_account_id, started_at DESC);

CREATE TABLE ingest.account_metric_snapshot (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id),
    observed_at timestamptz NOT NULL,
    subscriber_count bigint CHECK (subscriber_count IS NULL OR subscriber_count >= 0),
    subscriber_display text,
    quality ingest.observation_quality NOT NULL,
    source_fingerprint text NOT NULL CHECK (btrim(source_fingerprint) <> ''),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (platform_account_id, observed_at, source_fingerprint)
);

CREATE INDEX account_metric_snapshot_account_observed_idx
    ON ingest.account_metric_snapshot (platform_account_id, observed_at DESC);

CREATE TABLE ingest.content_group (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_type text NOT NULL CHECK (btrim(group_type) <> ''),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE ingest.publication (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    content_group_id uuid REFERENCES ingest.content_group(id),
    published_at timestamptz NOT NULL,
    discovered_at timestamptz NOT NULL,
    first_observation_age_seconds integer CHECK (
        first_observation_age_seconds IS NULL OR first_observation_age_seconds >= 0
    ),
    publication_type text NOT NULL CHECK (btrim(publication_type) <> ''),
    is_repost boolean NOT NULL DEFAULT false,
    history_completeness ingest.history_completeness NOT NULL,
    synthetic_baseline_allowed boolean NOT NULL DEFAULT false,
    quality_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (deleted_at IS NULL OR deleted_at >= published_at),
    CHECK (jsonb_typeof(quality_flags) = 'object'),
    CHECK (NOT synthetic_baseline_allowed OR history_completeness = 'complete')
);

CREATE INDEX publication_account_published_idx
    ON ingest.publication (primary_account_id, published_at DESC, id);
CREATE INDEX publication_active_tracking_idx
    ON ingest.publication (published_at DESC, primary_account_id)
    WHERE deleted_at IS NULL;
CREATE INDEX publication_content_group_idx
    ON ingest.publication (content_group_id)
    WHERE content_group_id IS NOT NULL;

CREATE TABLE ingest.publication_identity (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    source_external_id text,
    role ingest.publication_account_role NOT NULL,
    public_url text,
    CHECK (public_url IS NULL OR public_url ~ '^https://'),
    UNIQUE (platform_account_id, external_id)
);

CREATE INDEX publication_identity_publication_idx
    ON ingest.publication_identity (publication_id, role, id);

CREATE TABLE ingest.publication_metric_snapshot (
    published_month date NOT NULL,
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id),
    observed_at timestamptz NOT NULL,
    age_seconds integer NOT NULL CHECK (age_seconds >= 0),
    sampling_bucket bigint NOT NULL,
    views_count bigint CHECK (views_count IS NULL OR views_count >= 0),
    reactions_count bigint CHECK (reactions_count IS NULL OR reactions_count >= 0),
    comments_count bigint CHECK (comments_count IS NULL OR comments_count >= 0),
    shares_count bigint CHECK (shares_count IS NULL OR shares_count >= 0),
    quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean NOT NULL DEFAULT false,
    synthetic boolean NOT NULL DEFAULT false,
    metric_semantics_version integer NOT NULL DEFAULT 1 CHECK (metric_semantics_version > 0),
    capability_version integer NOT NULL DEFAULT 1 CHECK (capability_version > 0),
    source_fingerprint text NOT NULL CHECK (btrim(source_fingerprint) <> ''),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (published_month, id),
    UNIQUE (published_month, publication_id, sampling_bucket),
    CHECK (published_month = date_trunc('month', published_month)::date),
    CHECK (sampling_bucket >= 0 OR synthetic),
    CHECK (NOT synthetic OR age_seconds = 0)
) PARTITION BY RANGE (published_month);

-- Fail-open storage for legacy months not pre-created by the importer.  The
-- importer should still call ensure_publication_metric_partition() first so
-- normal rows land in bounded monthly partitions.
CREATE TABLE ingest.publication_metric_snapshot_default
    PARTITION OF ingest.publication_metric_snapshot DEFAULT;

COMMENT ON COLUMN ingest.publication_metric_snapshot.comments_count IS
    'Nullable platform observation. MAX comments are stored when exposed; unsupported or unavailable remains NULL.';

CREATE INDEX publication_metric_snapshot_publication_observed_idx
    ON ingest.publication_metric_snapshot (publication_id, observed_at DESC, id DESC);
CREATE INDEX publication_metric_snapshot_run_idx
    ON ingest.publication_metric_snapshot (collection_run_id, publication_id);
CREATE INDEX publication_metric_snapshot_observed_brin
    ON ingest.publication_metric_snapshot USING brin (observed_at);

CREATE TABLE ingest.reaction_breakdown (
    snapshot_published_month date NOT NULL,
    snapshot_id bigint NOT NULL,
    reaction_key text NOT NULL CHECK (btrim(reaction_key) <> ''),
    reaction_count bigint NOT NULL CHECK (reaction_count >= 0),
    PRIMARY KEY (snapshot_published_month, snapshot_id, reaction_key),
    FOREIGN KEY (snapshot_published_month, snapshot_id)
        REFERENCES ingest.publication_metric_snapshot (published_month, id)
        ON DELETE CASCADE
) PARTITION BY RANGE (snapshot_published_month);

CREATE TABLE ingest.reaction_breakdown_default
    PARTITION OF ingest.reaction_breakdown DEFAULT;

CREATE TABLE ingest.deletion_observation (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id),
    observed_at timestamptz NOT NULL,
    outcome ingest.deletion_probe_outcome NOT NULL,
    reason_code text NOT NULL CHECK (btrim(reason_code) <> ''),
    consecutive_missing integer NOT NULL CHECK (consecutive_missing >= 0),
    UNIQUE (publication_id, collection_run_id, observed_at)
);

CREATE INDEX deletion_observation_publication_time_idx
    ON ingest.deletion_observation (publication_id, observed_at DESC);

CREATE TABLE ingest.raw_payload (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id),
    owner_type ingest.raw_owner_type NOT NULL,
    owner_id uuid NOT NULL,
    collected_at timestamptz NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    content_encoding text NOT NULL CHECK (btrim(content_encoding) <> ''),
    payload bytea,
    external_ref text,
    encryption_key_ref text,
    purge_after timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (payload IS NOT NULL OR external_ref IS NOT NULL),
    CHECK (payload IS NULL OR encryption_key_ref IS NOT NULL),
    CHECK (purge_after > collected_at),
    UNIQUE (collection_run_id, owner_type, owner_id, sha256)
);

CREATE INDEX raw_payload_purge_idx ON ingest.raw_payload (purge_after, id);

-- ---------------------------------------------------------------------------
-- Analytics, revisions and rebuildable read models
-- ---------------------------------------------------------------------------

CREATE TABLE analytics.dataset_revision (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    committed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    cause analytics.revision_cause NOT NULL,
    correlation_id uuid NOT NULL,
    source_run_id uuid REFERENCES ingest.collection_run(id),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX dataset_revision_committed_idx
    ON analytics.dataset_revision (committed_at DESC, id DESC);
CREATE INDEX dataset_revision_correlation_idx
    ON analytics.dataset_revision (correlation_id);

CREATE TABLE analytics.metric_semantic_definition (
    metric_key analytics.metric_key NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    unit text NOT NULL CHECK (btrim(unit) <> ''),
    metric_kind text NOT NULL CHECK (btrim(metric_kind) <> ''),
    aggregation_policy jsonb NOT NULL,
    reset_policy jsonb NOT NULL,
    missing_policy jsonb NOT NULL,
    effective_from timestamptz NOT NULL,
    retired_at timestamptz,
    source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (metric_key, version),
    CHECK (retired_at IS NULL OR retired_at > effective_from)
);

CREATE TABLE analytics.platform_metric_capability (
    platform catalog.platform_code NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    capability_version integer NOT NULL CHECK (capability_version > 0),
    semantic_version integer NOT NULL CHECK (semantic_version > 0),
    supported boolean NOT NULL,
    notes text,
    effective_from timestamptz NOT NULL,
    retired_at timestamptz,
    PRIMARY KEY (platform, metric_key, capability_version),
    FOREIGN KEY (metric_key, semantic_version)
        REFERENCES analytics.metric_semantic_definition(metric_key, version),
    CHECK (retired_at IS NULL OR retired_at > effective_from)
);

CREATE TABLE analytics.institution_metric_aggregate (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    platform catalog.platform_code,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    as_of timestamptz NOT NULL,
    value numeric,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    coverage numeric NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    quality ingest.observation_quality NOT NULL,
    CHECK (window_end > window_start),
    CHECK (as_of >= window_end),
    UNIQUE NULLS NOT DISTINCT (
        institution_id, dataset_revision_id, platform, metric_key, aggregation,
        window_start, window_end, as_of
    )
);

CREATE INDEX institution_metric_aggregate_query_idx
    ON analytics.institution_metric_aggregate
    (institution_id, platform, metric_key, aggregation, window_end DESC, dataset_revision_id DESC);

CREATE TABLE analytics.anomaly_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform_account_id uuid REFERENCES catalog.platform_account(id),
    publication_id uuid REFERENCES ingest.publication(id),
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    signal_type text NOT NULL CHECK (btrim(signal_type) <> ''),
    severity numeric NOT NULL,
    detected_at timestamptz NOT NULL,
    detector_version text NOT NULL CHECK (btrim(detector_version) <> ''),
    evidence jsonb NOT NULL,
    status analytics.anomaly_status NOT NULL DEFAULT 'unreviewed',
    CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX anomaly_event_institution_time_idx
    ON analytics.anomaly_event (institution_id, detected_at DESC);

CREATE TABLE analytics.anomaly_review (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_event_id uuid NOT NULL REFERENCES analytics.anomaly_event(id),
    reviewer_subject text NOT NULL CHECK (btrim(reviewer_subject) <> ''),
    decision analytics.review_decision NOT NULL,
    comment text,
    reviewed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE INDEX anomaly_review_event_time_idx
    ON analytics.anomaly_review (anomaly_event_id, reviewed_at DESC);

CREATE TABLE analytics.projection_state (
    projection_name text PRIMARY KEY CHECK (btrim(projection_name) <> ''),
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    status analytics.projection_status NOT NULL,
    refreshed_at timestamptz NOT NULL,
    row_count bigint NOT NULL CHECK (row_count >= 0),
    error_code text,
    CHECK ((status = 'failed') OR error_code IS NULL)
);

-- Wide latest projection expected by the Spring query layer.  Metric-specific
-- timestamps/quality allow an independently unavailable comments call (notably
-- MAX/Rutube) to retain the last usable value without inventing zero.
CREATE TABLE analytics.publication_latest (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id) ON DELETE CASCADE,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    platform catalog.platform_code NOT NULL,
    observed_at timestamptz NOT NULL,
    views_count bigint CHECK (views_count IS NULL OR views_count >= 0),
    views_observed_at timestamptz,
    views_quality ingest.observation_quality,
    reactions_count bigint CHECK (reactions_count IS NULL OR reactions_count >= 0),
    reactions_observed_at timestamptz,
    reactions_quality ingest.observation_quality,
    comments_count bigint CHECK (comments_count IS NULL OR comments_count >= 0),
    comments_observed_at timestamptz,
    comments_quality ingest.observation_quality,
    shares_count bigint CHECK (shares_count IS NULL OR shares_count >= 0),
    shares_observed_at timestamptz,
    shares_quality ingest.observation_quality,
    quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean NOT NULL DEFAULT false,
    synthetic boolean NOT NULL DEFAULT false,
    history_completeness ingest.history_completeness NOT NULL,
    source_snapshot_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    refreshed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK ((views_count IS NULL) = (views_observed_at IS NULL)),
    CHECK ((views_count IS NULL) = (views_quality IS NULL)),
    CHECK ((reactions_count IS NULL) = (reactions_observed_at IS NULL)),
    CHECK ((reactions_count IS NULL) = (reactions_quality IS NULL)),
    CHECK ((comments_count IS NULL) = (comments_observed_at IS NULL)),
    CHECK ((comments_count IS NULL) = (comments_quality IS NULL)),
    CHECK ((shares_count IS NULL) = (shares_observed_at IS NULL)),
    CHECK ((shares_count IS NULL) = (shares_quality IS NULL)),
    CHECK (jsonb_typeof(source_snapshot_refs) = 'object')
);

CREATE INDEX publication_latest_institution_platform_idx
    ON analytics.publication_latest (institution_id, platform, observed_at DESC, publication_id);
CREATE INDEX publication_latest_account_idx
    ON analytics.publication_latest (platform_account_id, observed_at DESC, publication_id);

CREATE TABLE analytics.publication_hourly (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    hour_offset integer NOT NULL CHECK (hour_offset >= 0),
    hour timestamptz NOT NULL,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    platform catalog.platform_code NOT NULL,
    observed_at timestamptz NOT NULL,
    views_count bigint CHECK (views_count IS NULL OR views_count >= 0),
    reactions_count bigint CHECK (reactions_count IS NULL OR reactions_count >= 0),
    comments_count bigint CHECK (comments_count IS NULL OR comments_count >= 0),
    shares_count bigint CHECK (shares_count IS NULL OR shares_count >= 0),
    quality ingest.observation_quality NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    history_completeness ingest.history_completeness NOT NULL,
    interval_uncertain boolean NOT NULL DEFAULT false,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    PRIMARY KEY (publication_id, hour_offset, dataset_revision_id),
    UNIQUE (publication_id, hour, dataset_revision_id),
    CHECK (observed_at <= hour)
);

CREATE INDEX publication_hourly_query_idx
    ON analytics.publication_hourly
    (institution_id, platform, hour_offset, dataset_revision_id, publication_id);

CREATE TABLE analytics.institution_daily_metrics (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform analytics.platform_scope NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    metric_day date NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    value numeric,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    coverage numeric NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    quality ingest.observation_quality NOT NULL,
    as_of timestamptz NOT NULL,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    CHECK (window_end > window_start),
    CHECK (as_of >= window_end),
    UNIQUE (institution_id, platform, metric_key, aggregation, metric_day, dataset_revision_id)
);

CREATE INDEX institution_daily_metrics_query_idx
    ON analytics.institution_daily_metrics
    (institution_id, platform, metric_day DESC, metric_key, aggregation, dataset_revision_id DESC);

CREATE TABLE analytics.institution_monthly_metrics (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform analytics.platform_scope NOT NULL,
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    metric_month date NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    value numeric,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    coverage numeric NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    quality ingest.observation_quality NOT NULL,
    as_of timestamptz NOT NULL,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    CHECK (metric_month = date_trunc('month', metric_month)::date),
    CHECK (window_end > window_start),
    CHECK (as_of >= window_end),
    UNIQUE (institution_id, platform, metric_key, aggregation, metric_month, dataset_revision_id)
);

CREATE INDEX institution_monthly_metrics_query_idx
    ON analytics.institution_monthly_metrics
    (institution_id, platform, metric_month DESC, metric_key, aggregation, dataset_revision_id DESC);

CREATE TABLE analytics.institution_period_metrics (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    platform catalog.platform_code,
    period_key text NOT NULL CHECK (period_key IN ('3h', '1d', '7d', '30d')),
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    value numeric,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    coverage numeric NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    quality ingest.observation_quality NOT NULL,
    as_of timestamptz NOT NULL,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    refreshed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (window_end > window_start),
    CHECK (as_of >= window_end),
    UNIQUE NULLS NOT DISTINCT (
        institution_id, platform, period_key, metric_key, aggregation,
        as_of, dataset_revision_id
    )
);

CREATE INDEX institution_period_metrics_query_idx
    ON analytics.institution_period_metrics
    (platform, period_key, metric_key, aggregation, as_of DESC, dataset_revision_id DESC, institution_id);

CREATE TABLE analytics.comparison_cohort (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform catalog.platform_code NOT NULL,
    horizon_seconds integer NOT NULL CHECK (horizon_seconds > 0),
    as_of timestamptz NOT NULL,
    filter_definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (jsonb_typeof(filter_definition) = 'object'),
    UNIQUE (platform, horizon_seconds, as_of, filter_definition, dataset_revision_id)
);

CREATE TABLE analytics.comparison_cohort_member (
    cohort_id uuid NOT NULL REFERENCES analytics.comparison_cohort(id) ON DELETE CASCADE,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    PRIMARY KEY (cohort_id, publication_id)
);

CREATE INDEX comparison_cohort_member_institution_idx
    ON analytics.comparison_cohort_member (cohort_id, institution_id, publication_id);

CREATE TABLE analytics.comparison_metric_point (
    cohort_id uuid NOT NULL REFERENCES analytics.comparison_cohort(id) ON DELETE CASCADE,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    metric_key analytics.metric_key NOT NULL,
    aggregation analytics.aggregation_code NOT NULL,
    hour_offset integer NOT NULL CHECK (hour_offset >= 0),
    value numeric,
    sample_size integer NOT NULL CHECK (sample_size >= 0),
    coverage numeric NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    quality ingest.observation_quality NOT NULL,
    PRIMARY KEY (cohort_id, institution_id, metric_key, aggregation, hour_offset)
);

-- ---------------------------------------------------------------------------
-- Versioned rating model
-- ---------------------------------------------------------------------------

CREATE TABLE rating.population_observation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    population_type text NOT NULL CHECK (btrim(population_type) <> ''),
    value bigint NOT NULL CHECK (value >= 0),
    observed_for date NOT NULL,
    source_url text NOT NULL CHECK (source_url ~ '^https://'),
    quality ingest.observation_quality NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE (institution_id, population_type, observed_for, source_url)
);

CREATE TABLE rating.formula_definition (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    formula_key text NOT NULL CHECK (btrim(formula_key) <> ''),
    version integer NOT NULL CHECK (version > 0),
    status rating.formula_status NOT NULL DEFAULT 'draft',
    effective_from timestamptz NOT NULL,
    definition jsonb NOT NULL,
    source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    published_at timestamptz,
    CHECK (jsonb_typeof(definition) = 'object'),
    CHECK ((status IN ('published', 'retired')) = (published_at IS NOT NULL)),
    UNIQUE (formula_key, version)
);

CREATE UNIQUE INDEX formula_definition_one_published_effective_idx
    ON rating.formula_definition (formula_key, effective_from)
    WHERE status = 'published';

CREATE TABLE rating.formula_component (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    formula_definition_id uuid NOT NULL REFERENCES rating.formula_definition(id) ON DELETE CASCADE,
    component_code text NOT NULL CHECK (btrim(component_code) <> ''),
    numerator_metric analytics.metric_key NOT NULL,
    denominator_key text,
    weight numeric NOT NULL,
    normalization text NOT NULL CHECK (btrim(normalization) <> ''),
    missing_policy text NOT NULL CHECK (btrim(missing_policy) <> ''),
    minimum_quality ingest.observation_quality NOT NULL,
    UNIQUE (formula_definition_id, component_code)
);

CREATE TABLE rating.rating_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    formula_definition_id uuid NOT NULL REFERENCES rating.formula_definition(id),
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    as_of timestamptz NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    status ingest.run_status NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    CHECK (window_end > window_start),
    CHECK (as_of >= window_end),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    UNIQUE (formula_definition_id, dataset_revision_id, as_of, input_hash)
);

CREATE TABLE rating.rating_result (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rating_run_id uuid NOT NULL REFERENCES rating.rating_run(id) ON DELETE CASCADE,
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    score numeric,
    rank integer CHECK (rank IS NULL OR rank > 0),
    quality ingest.observation_quality NOT NULL,
    explanation jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(explanation) = 'object'),
    UNIQUE (rating_run_id, institution_id)
);

CREATE TABLE rating.rating_component_result (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    rating_result_id uuid NOT NULL REFERENCES rating.rating_result(id) ON DELETE CASCADE,
    formula_component_id uuid NOT NULL REFERENCES rating.formula_component(id),
    numerator numeric,
    denominator numeric,
    normalized_value numeric,
    weighted_value numeric,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    CHECK (jsonb_typeof(warnings) = 'array'),
    UNIQUE (rating_result_id, formula_component_id)
);

CREATE TABLE rating.official_rating_observation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id uuid NOT NULL REFERENCES catalog.institution(id),
    category text NOT NULL CHECK (btrim(category) <> ''),
    period text NOT NULL CHECK (btrim(period) <> ''),
    rank integer CHECK (rank IS NULL OR rank > 0),
    score numeric,
    source_url text NOT NULL CHECK (source_url ~ '^https://'),
    source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    fetched_at timestamptz NOT NULL,
    UNIQUE (institution_id, category, period, source_hash)
);

CREATE INDEX official_rating_observation_lookup_idx
    ON rating.official_rating_observation (institution_id, category, period, fetched_at DESC);

-- ---------------------------------------------------------------------------
-- Operations, audit, revision outbox and retention
-- ---------------------------------------------------------------------------

CREATE TABLE ops_and_admin.audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    subject text NOT NULL CHECK (btrim(subject) <> ''),
    action text NOT NULL CHECK (btrim(action) <> ''),
    target_type text NOT NULL CHECK (btrim(target_type) <> ''),
    target_id uuid,
    correlation_id uuid NOT NULL,
    before_state jsonb,
    after_state jsonb,
    outcome text NOT NULL CHECK (btrim(outcome) <> ''),
    CHECK (before_state IS NULL OR jsonb_typeof(before_state) = 'object'),
    CHECK (after_state IS NULL OR jsonb_typeof(after_state) = 'object')
);

CREATE INDEX audit_log_target_time_idx
    ON ops_and_admin.audit_log (target_type, target_id, occurred_at DESC);
CREATE INDEX audit_log_subject_time_idx
    ON ops_and_admin.audit_log (subject, occurred_at DESC);

CREATE TABLE ops_and_admin.archive_manifest (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_type text NOT NULL CHECK (btrim(dataset_type) <> ''),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    partition_start timestamptz NOT NULL,
    partition_end timestamptz NOT NULL,
    object_uri text NOT NULL CHECK (btrim(object_uri) <> ''),
    archive_format text NOT NULL DEFAULT 'parquet' CHECK (archive_format = 'parquet'),
    compression text NOT NULL DEFAULT 'zstandard' CHECK (compression = 'zstandard'),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    row_count bigint NOT NULL CHECK (row_count >= 0),
    min_observed_at timestamptz,
    max_observed_at timestamptz,
    status ops_and_admin.archive_status NOT NULL DEFAULT 'staging',
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    verified_at timestamptz,
    hot_dropped_at timestamptz,
    purge_after timestamptz,
    verification_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (partition_end > partition_start),
    CHECK (max_observed_at IS NULL OR min_observed_at IS NULL OR max_observed_at >= min_observed_at),
    CHECK (verified_at IS NULL OR verified_at >= created_at),
    CHECK (hot_dropped_at IS NULL OR verified_at IS NOT NULL),
    CHECK (jsonb_typeof(verification_details) = 'object'),
    UNIQUE (dataset_type, partition_start, partition_end, sha256)
);

CREATE INDEX archive_manifest_lifecycle_idx
    ON ops_and_admin.archive_manifest (dataset_type, status, partition_end, id);

CREATE TABLE ops_and_admin.outbox_event (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    event_type text NOT NULL CHECK (btrim(event_type) <> ''),
    aggregate_type text NOT NULL CHECK (btrim(aggregate_type) <> ''),
    aggregate_id text NOT NULL CHECK (btrim(aggregate_id) <> ''),
    affected_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    available_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    published_at timestamptz,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    last_error_code text,
    CHECK (jsonb_typeof(payload) = 'object'),
    UNIQUE (dataset_revision_id, event_type, aggregate_type, aggregate_id)
);

CREATE INDEX outbox_event_pending_idx
    ON ops_and_admin.outbox_event (available_at, id)
    WHERE published_at IS NULL;

CREATE TABLE ops_and_admin.retention_policy (
    data_class text PRIMARY KEY,
    hot_days integer CHECK (hot_days IS NULL OR hot_days >= 0),
    retention_months integer CHECK (retention_months IS NULL OR retention_months >= 0),
    archive_required boolean NOT NULL,
    notes text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

-- Only explicitly mapped legacy app_state/account cursor values belong here;
-- unknown source keys are retained in migration.legacy_evidence instead.
CREATE TABLE ops_and_admin.operational_checkpoint (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    checkpoint_key text NOT NULL CHECK (btrim(checkpoint_key) <> ''),
    scope_type text NOT NULL CHECK (scope_type IN ('system', 'platform', 'account')),
    scope_id uuid,
    platform catalog.platform_code,
    value jsonb NOT NULL,
    source_observed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    correlation_id uuid,
    CHECK (jsonb_typeof(value) IN ('object', 'array', 'string', 'number', 'boolean', 'null')),
    CHECK ((scope_type = 'system' AND scope_id IS NULL) OR (scope_type <> 'system' AND scope_id IS NOT NULL)),
    CHECK ((scope_type = 'platform' AND platform IS NOT NULL) OR scope_type <> 'platform'),
    UNIQUE NULLS NOT DISTINCT (checkpoint_key, scope_type, scope_id, platform)
);

CREATE INDEX operational_checkpoint_lookup_idx
    ON ops_and_admin.operational_checkpoint (scope_type, scope_id, checkpoint_key);

CREATE TABLE ops_and_admin.recovery_policy (
    policy_name text PRIMARY KEY,
    target_rpo interval NOT NULL CHECK (target_rpo > interval '0 seconds'),
    target_rto interval NOT NULL CHECK (target_rto > interval '0 seconds'),
    daily_base_backup_points integer NOT NULL CHECK (daily_base_backup_points > 0),
    weekly_backup_points integer NOT NULL CHECK (weekly_backup_points > 0),
    monthly_backup_points integer NOT NULL CHECK (monthly_backup_points > 0),
    automated_verification_interval interval NOT NULL CHECK (
        automated_verification_interval > interval '0 seconds'
    ),
    full_restore_drill_interval interval NOT NULL CHECK (
        full_restore_drill_interval > interval '0 seconds'
    ),
    encrypted_off_primary_copy_required boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

INSERT INTO ops_and_admin.recovery_policy (
    policy_name, target_rpo, target_rto, daily_base_backup_points,
    weekly_backup_points, monthly_backup_points,
    automated_verification_interval, full_restore_drill_interval,
    encrypted_off_primary_copy_required
)
VALUES (
    'primary', interval '15 minutes', interval '2 hours', 14, 8, 12,
    interval '1 day', interval '3 months', true
);

INSERT INTO ops_and_admin.retention_policy
    (data_class, hot_days, retention_months, archive_required, notes)
VALUES
    ('raw_payload', 7, NULL, false, 'Purge payload; retain hash, source fields and lineage.'),
    ('publication_metric_snapshot', 70, 36, true, 'Parity floor: at least 70 full hot days; retain cold details for three years.'),
    ('account_metric_snapshot', 40, 36, true, 'Archive full history or retained daily series for three years.'),
    ('aggregate', NULL, NULL, false, 'Retain indefinitely.'),
    ('formula_and_rating', NULL, NULL, false, 'Published history is immutable and retained indefinitely.'),
    ('anomaly_and_review', NULL, 36, false, 'Retain at least three calendar years.'),
    ('admin_audit', NULL, 36, false, 'Retain at least three calendar years; no secrets.'),
    ('collection_run_detail', 180, NULL, false, 'Retain aggregate indefinitely.'),
    ('application_log', 30, NULL, false, 'Security events follow a separate policy.');

-- ---------------------------------------------------------------------------
-- Migration bridge state and evidence (never available to public API roles)
-- ---------------------------------------------------------------------------

CREATE TABLE migration.import_batch (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name text NOT NULL CHECK (btrim(source_name) <> ''),
    source_file_name text NOT NULL CHECK (btrim(source_file_name) <> ''),
    source_size_bytes bigint NOT NULL CHECK (source_size_bytes >= 0),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_schema_version integer NOT NULL CHECK (source_schema_version > 0),
    snapshot_kind text NOT NULL CHECK (snapshot_kind IN ('s0', 'catch_up', 's_final', 'fixture')),
    tool_version text NOT NULL CHECK (btrim(tool_version) <> ''),
    status migration.batch_status NOT NULL DEFAULT 'pending',
    dry_run boolean NOT NULL DEFAULT false,
    source_snapshot_at timestamptz,
    started_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    finished_at timestamptz,
    rows_read bigint NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    rows_written bigint NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    error_summary text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (jsonb_typeof(metadata) = 'object'),
    UNIQUE (source_name, source_sha256, snapshot_kind, tool_version, dry_run)
);

CREATE INDEX import_batch_status_time_idx
    ON migration.import_batch (status, started_at DESC);

CREATE TABLE migration.legacy_identity_map (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source_namespace uuid NOT NULL,
    source_table text NOT NULL CHECK (btrim(source_table) <> ''),
    source_pk text NOT NULL CHECK (btrim(source_pk) <> ''),
    target_type text NOT NULL CHECK (btrim(target_type) <> ''),
    target_uuid uuid,
    target_bigint bigint,
    natural_key jsonb NOT NULL,
    source_row_hash text NOT NULL CHECK (source_row_hash ~ '^[0-9a-f]{64}$'),
    first_batch_id uuid NOT NULL REFERENCES migration.import_batch(id),
    last_seen_batch_id uuid NOT NULL REFERENCES migration.import_batch(id),
    mapped_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK ((target_uuid IS NOT NULL)::integer + (target_bigint IS NOT NULL)::integer = 1),
    CHECK (jsonb_typeof(natural_key) = 'object'),
    UNIQUE (source_namespace, source_table, source_pk, target_type)
);

CREATE INDEX legacy_identity_map_target_uuid_idx
    ON migration.legacy_identity_map (target_type, target_uuid)
    WHERE target_uuid IS NOT NULL;
CREATE INDEX legacy_identity_map_target_bigint_idx
    ON migration.legacy_identity_map (target_type, target_bigint)
    WHERE target_bigint IS NOT NULL;

CREATE TABLE migration.checkpoint (
    batch_id uuid NOT NULL REFERENCES migration.import_batch(id) ON DELETE CASCADE,
    stream_name text NOT NULL CHECK (btrim(stream_name) <> ''),
    source_table text NOT NULL CHECK (btrim(source_table) <> ''),
    high_water_mark jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_sequence bigint,
    rows_processed bigint NOT NULL DEFAULT 0 CHECK (rows_processed >= 0),
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (batch_id, stream_name),
    CHECK (jsonb_typeof(high_water_mark) = 'object')
);

CREATE TABLE migration.legacy_evidence (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES migration.import_batch(id) ON DELETE CASCADE,
    source_table text NOT NULL CHECK (btrim(source_table) <> ''),
    source_pk text NOT NULL CHECK (btrim(source_pk) <> ''),
    source_row_hash text NOT NULL CHECK (source_row_hash ~ '^[0-9a-f]{64}$'),
    evidence_kind text NOT NULL CHECK (btrim(evidence_kind) <> ''),
    evidence jsonb NOT NULL,
    sanitized boolean NOT NULL DEFAULT true CHECK (sanitized),
    retained_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (jsonb_typeof(evidence) = 'object'),
    UNIQUE (batch_id, source_table, source_pk, evidence_kind, source_row_hash)
);

CREATE TABLE migration.reconciliation_result (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES migration.import_batch(id) ON DELETE CASCADE,
    check_name text NOT NULL CHECK (btrim(check_name) <> ''),
    scope text NOT NULL CHECK (btrim(scope) <> ''),
    source_table text,
    target_table text,
    status migration.reconciliation_status NOT NULL,
    critical boolean NOT NULL DEFAULT true,
    expected_value jsonb,
    actual_value jsonb,
    difference jsonb,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    checked_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (details IS NULL OR jsonb_typeof(details) = 'object'),
    UNIQUE NULLS NOT DISTINCT (batch_id, check_name, scope, source_table, target_table)
);

CREATE INDEX reconciliation_result_gate_idx
    ON migration.reconciliation_result (batch_id, critical, status, check_name);

CREATE TABLE migration.source_change_event (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    source_namespace uuid NOT NULL,
    source_sequence bigint NOT NULL CHECK (source_sequence > 0),
    source_table text NOT NULL CHECK (btrim(source_table) <> ''),
    source_pk text NOT NULL CHECK (btrim(source_pk) <> ''),
    operation text NOT NULL CHECK (operation IN ('insert', 'update', 'delete')),
    source_row_hash text CHECK (source_row_hash IS NULL OR source_row_hash ~ '^[0-9a-f]{64}$'),
    sanitized_payload jsonb,
    source_committed_at timestamptz NOT NULL,
    imported_batch_id uuid REFERENCES migration.import_batch(id),
    imported_at timestamptz,
    UNIQUE (source_namespace, source_sequence),
    CHECK (sanitized_payload IS NULL OR jsonb_typeof(sanitized_payload) = 'object'),
    CHECK ((imported_at IS NULL) = (imported_batch_id IS NULL))
);

CREATE INDEX source_change_event_pending_idx
    ON migration.source_change_event (source_namespace, source_sequence)
    WHERE imported_at IS NULL;

-- ---------------------------------------------------------------------------
-- Guardrails and partition lifecycle
-- ---------------------------------------------------------------------------

CREATE FUNCTION rating.reject_published_formula_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, rating
AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'retired') THEN
        RAISE EXCEPTION 'published formula % version % is immutable', OLD.formula_key, OLD.version;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'retired' THEN
        RAISE EXCEPTION 'retired formula % version % is immutable', OLD.formula_key, OLD.version;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'published' THEN
        IF NEW.status <> 'retired'
           OR NEW.formula_key IS DISTINCT FROM OLD.formula_key
           OR NEW.version IS DISTINCT FROM OLD.version
           OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
           OR NEW.definition IS DISTINCT FROM OLD.definition
           OR NEW.source_hash IS DISTINCT FROM OLD.source_hash
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
            RAISE EXCEPTION 'published formula % version % is immutable except for retirement',
                OLD.formula_key, OLD.version;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER formula_definition_immutable
BEFORE UPDATE OR DELETE ON rating.formula_definition
FOR EACH ROW EXECUTE FUNCTION rating.reject_published_formula_mutation();

CREATE FUNCTION rating.reject_published_component_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, rating
AS $function$
DECLARE
    definition_status rating.formula_status;
    target_definition_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        target_definition_id := NEW.formula_definition_id;
    ELSE
        target_definition_id := OLD.formula_definition_id;
    END IF;
    SELECT status INTO definition_status
      FROM rating.formula_definition
     WHERE id = target_definition_id;
    IF definition_status IN ('published', 'retired') THEN
        RAISE EXCEPTION 'components of a published formula are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER formula_component_immutable
BEFORE INSERT OR UPDATE OR DELETE ON rating.formula_component
FOR EACH ROW EXECUTE FUNCTION rating.reject_published_component_mutation();

CREATE FUNCTION ingest.assert_publication_snapshot_month()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, ingest
AS $function$
DECLARE
    expected_month date;
BEGIN
    SELECT date_trunc('month', published_at AT TIME ZONE 'UTC')::date
      INTO expected_month
      FROM ingest.publication
     WHERE id = NEW.publication_id;
    IF expected_month IS NULL OR expected_month <> NEW.published_month THEN
        RAISE EXCEPTION 'published_month % does not match publication % month %',
            NEW.published_month, NEW.publication_id, expected_month;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER publication_snapshot_month_guard
BEFORE INSERT OR UPDATE OF published_month, publication_id
ON ingest.publication_metric_snapshot
FOR EACH ROW EXECUTE FUNCTION ingest.assert_publication_snapshot_month();

CREATE OR REPLACE FUNCTION ops_and_admin.ensure_publication_metric_partition(p_month date)
RETURNS regclass
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ingest, ops_and_admin
SET lock_timeout = '10s'
AS $function$
DECLARE
    month_start date := date_trunc('month', p_month)::date;
    month_end date := (date_trunc('month', p_month) + interval '1 month')::date;
    partition_name text := 'publication_metric_snapshot_' || to_char(month_start, 'YYYY_MM');
    reaction_partition_name text := 'reaction_breakdown_' || to_char(month_start, 'YYYY_MM');
    qualified_name text := format('ingest.%I', partition_name);
    result regclass;
BEGIN
    IF p_month IS NULL THEN
        RAISE EXCEPTION 'partition month must not be NULL';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(qualified_name, 0));
    result := to_regclass(qualified_name);
    IF result IS NULL THEN
        EXECUTE format(
            'CREATE TABLE ingest.%I PARTITION OF ingest.publication_metric_snapshot '
            'FOR VALUES FROM (%L) TO (%L)',
            partition_name, month_start, month_end
        );
        result := to_regclass(qualified_name);
    END IF;
    IF to_regclass(format('ingest.%I', reaction_partition_name)) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE ingest.%I PARTITION OF ingest.reaction_breakdown '
            'FOR VALUES FROM (%L) TO (%L)',
            reaction_partition_name, month_start, month_end
        );
    END IF;
    -- Parent privileges cover queries routed through the partitioned table but
    -- not reconciliation/archive queries that intentionally address a child.
    -- Re-issuing these exact grants also repairs a pre-existing child safely.
    EXECUTE format(
        'GRANT SELECT ON TABLE ingest.%I TO migration_bridge, maintenance',
        partition_name
    );
    EXECUTE format(
        'GRANT SELECT ON TABLE ingest.%I TO migration_bridge, maintenance',
        reaction_partition_name
    );
    RETURN result;
END
$function$;

CREATE FUNCTION ops_and_admin.drop_publication_metric_partition(
    p_month date,
    p_manifest_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ingest, ops_and_admin
SET lock_timeout = '10s'
AS $function$
DECLARE
    month_start date := date_trunc('month', p_month)::date;
    month_end date := (date_trunc('month', p_month) + interval '1 month')::date;
    partition_name text := 'publication_metric_snapshot_' || to_char(month_start, 'YYYY_MM');
    reaction_partition_name text := 'reaction_breakdown_' || to_char(month_start, 'YYYY_MM');
    hot_days integer;
    manifest_ok boolean;
BEGIN
    SELECT rp.hot_days INTO hot_days
      FROM ops_and_admin.retention_policy rp
     WHERE rp.data_class = 'publication_metric_snapshot';
    IF hot_days IS NULL OR hot_days < 70 THEN
        RAISE EXCEPTION 'publication snapshot hot retention must remain at least 70 days during parity';
    END IF;
    IF current_date < month_end + hot_days THEN
        RAISE EXCEPTION 'partition % has not completed the % day hot retention floor', month_start, hot_days;
    END IF;
    SELECT true INTO manifest_ok
      FROM ops_and_admin.archive_manifest am
     WHERE am.id = p_manifest_id
       AND am.dataset_type = 'publication_metric_snapshot'
       AND am.partition_start <= month_start::timestamptz
       AND am.partition_end >= month_end::timestamptz
       AND am.status = 'verified'
       AND am.verified_at IS NOT NULL
       AND am.row_count >= 0
       AND am.sha256 ~ '^[0-9a-f]{64}$';
    IF manifest_ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'verified archive manifest % does not cover partition %', p_manifest_id, month_start;
    END IF;
    IF to_regclass(format('ingest.%I', partition_name)) IS NULL THEN
        RAISE EXCEPTION 'partition ingest.% does not exist', partition_name;
    END IF;
    IF to_regclass(format('ingest.%I', reaction_partition_name)) IS NULL THEN
        RAISE EXCEPTION 'partition ingest.% does not exist', reaction_partition_name;
    END IF;
    EXECUTE format('DROP TABLE ingest.%I', reaction_partition_name);
    EXECUTE format('DROP TABLE ingest.%I', partition_name);
    UPDATE ops_and_admin.archive_manifest
       SET status = 'hot_dropped', hot_dropped_at = transaction_timestamp()
     WHERE id = p_manifest_id;
END
$function$;

CREATE FUNCTION ops_and_admin.purge_expired_raw_payload(p_limit integer DEFAULT 10000)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ingest, ops_and_admin
SET lock_timeout = '10s'
AS $function$
DECLARE
    deleted_count bigint;
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100000 THEN
        RAISE EXCEPTION 'raw payload purge limit must be between 1 and 100000';
    END IF;
    WITH doomed AS (
        SELECT id
          FROM ingest.raw_payload
         WHERE purge_after <= transaction_timestamp()
         ORDER BY purge_after, id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    ), deleted AS (
        DELETE FROM ingest.raw_payload payload
         USING doomed
         WHERE payload.id = doomed.id
         RETURNING 1
    )
    SELECT count(*) INTO deleted_count FROM deleted;
    RETURN deleted_count;
END
$function$;

REVOKE ALL ON FUNCTION rating.reject_published_formula_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION rating.reject_published_component_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION ingest.assert_publication_snapshot_month() FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.ensure_publication_metric_partition(date) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.drop_publication_metric_partition(date, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.purge_expired_raw_payload(integer) FROM PUBLIC;

-- Create a bounded initial set. Import/collector code must call the function for
-- every source publication month before inserting its batch.
SELECT ops_and_admin.ensure_publication_metric_partition(
    (date_trunc('month', current_date) + (offset_month || ' months')::interval)::date
)
FROM generate_series(-3, 2) AS offsets(offset_month);

-- ---------------------------------------------------------------------------
-- Least-privilege runtime grants. Future Flyway migrations must grant new
-- objects explicitly; broad default privileges are intentionally not used.
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA catalog, ingest, analytics, rating, ops_and_admin TO api_read;
GRANT SELECT ON
    catalog.institution,
    catalog.institution_external_id,
    catalog.platform_account,
    catalog.account_identity_history,
    catalog.account_external_identity,
    catalog.account_verification,
    catalog.legacy_entity_alias,
    ingest.publication,
    analytics.dataset_revision,
    analytics.metric_semantic_definition,
    analytics.platform_metric_capability,
    analytics.institution_metric_aggregate,
    analytics.anomaly_event,
    analytics.anomaly_review,
    analytics.projection_state,
    analytics.publication_latest,
    analytics.publication_hourly,
    analytics.institution_daily_metrics,
    analytics.institution_monthly_metrics,
    analytics.institution_period_metrics,
    analytics.comparison_cohort,
    analytics.comparison_cohort_member,
    analytics.comparison_metric_point,
    rating.population_observation,
    rating.formula_definition,
    rating.formula_component,
    rating.rating_run,
    rating.rating_result,
    rating.rating_component_result,
    rating.official_rating_observation,
    ops_and_admin.operational_checkpoint
TO api_read;

GRANT USAGE ON SCHEMA catalog, analytics, rating, ops_and_admin TO api_write_admin;
GRANT INSERT, UPDATE ON
    catalog.institution,
    catalog.institution_external_id,
    catalog.platform_account,
    catalog.account_identity_history,
    catalog.account_external_identity,
    catalog.account_verification,
    catalog.legacy_entity_alias,
    rating.formula_definition,
    rating.formula_component,
    rating.rating_run,
    rating.rating_result,
    rating.rating_component_result
TO api_write_admin;
GRANT INSERT ON
    analytics.dataset_revision,
    analytics.anomaly_review,
    rating.population_observation,
    rating.official_rating_observation
TO api_write_admin;
GRANT DELETE ON
    catalog.institution_external_id,
    catalog.account_verification
TO api_write_admin;
GRANT INSERT ON ops_and_admin.audit_log, ops_and_admin.outbox_event TO api_write_admin;
GRANT SELECT, INSERT, UPDATE ON ops_and_admin.operational_checkpoint TO api_write_admin;
GRANT SELECT ON ops_and_admin.outbox_event TO api_write_admin;
GRANT UPDATE (published_at, publish_attempts, last_error_code, available_at)
    ON ops_and_admin.outbox_event TO api_write_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA catalog, analytics, rating, ops_and_admin
    TO api_write_admin;

GRANT USAGE ON SCHEMA catalog, ingest, analytics, ops_and_admin TO collector_ingest;
GRANT SELECT ON catalog.institution, catalog.platform_account TO collector_ingest;
GRANT SELECT, INSERT, UPDATE ON
    ingest.collection_run,
    ingest.collection_account_result,
    ingest.publication,
    ingest.publication_identity
TO collector_ingest;
GRANT SELECT, INSERT ON
    ingest.account_metric_snapshot,
    ingest.content_group,
    ingest.publication_metric_snapshot,
    ingest.reaction_breakdown,
    ingest.deletion_observation,
    ingest.raw_payload,
    analytics.dataset_revision,
    ops_and_admin.outbox_event
TO collector_ingest;
GRANT SELECT, INSERT, UPDATE ON ops_and_admin.operational_checkpoint TO collector_ingest;
GRANT UPDATE (published_at, publish_attempts, last_error_code, available_at)
    ON ops_and_admin.outbox_event TO collector_ingest;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ingest, analytics, ops_and_admin
    TO collector_ingest;
GRANT EXECUTE ON FUNCTION ops_and_admin.ensure_publication_metric_partition(date)
    TO collector_ingest;

GRANT USAGE ON SCHEMA catalog, ingest, analytics, rating, ops_and_admin, migration
    TO migration_bridge;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA catalog, migration TO migration_bridge;
GRANT SELECT, INSERT ON
    ingest.collection_run,
    ingest.collection_account_result,
    ingest.account_metric_snapshot,
    ingest.content_group,
    ingest.publication,
    ingest.publication_identity,
    ingest.publication_metric_snapshot,
    ingest.reaction_breakdown,
    ingest.deletion_observation,
    ingest.raw_payload,
    analytics.dataset_revision,
    ops_and_admin.outbox_event,
    ops_and_admin.operational_checkpoint,
    rating.population_observation,
    rating.official_rating_observation
TO migration_bridge;
GRANT UPDATE ON
    ingest.collection_run,
    ingest.collection_account_result,
    ingest.account_metric_snapshot,
    ingest.publication,
    ingest.publication_identity,
    ingest.publication_metric_snapshot,
    ingest.reaction_breakdown,
    ingest.deletion_observation,
    ops_and_admin.operational_checkpoint
TO migration_bridge;
GRANT SELECT, INSERT, UPDATE ON analytics.projection_state TO migration_bridge;
GRANT UPDATE ON ops_and_admin.outbox_event TO migration_bridge;
GRANT SELECT ON
    ingest.publication_metric_snapshot_default,
    ingest.reaction_breakdown_default
TO migration_bridge, maintenance;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA catalog, ingest, analytics, rating, ops_and_admin, migration
    TO migration_bridge;
GRANT EXECUTE ON FUNCTION ops_and_admin.ensure_publication_metric_partition(date)
    TO migration_bridge;

GRANT USAGE ON SCHEMA catalog, ingest, analytics, rating, ops_and_admin TO maintenance;
GRANT SELECT ON
    catalog.institution,
    catalog.platform_account,
    ingest.collection_run,
    ingest.collection_account_result,
    ingest.account_metric_snapshot,
    ingest.publication,
    ingest.publication_identity,
    ingest.publication_metric_snapshot,
    ingest.reaction_breakdown,
    analytics.dataset_revision,
    analytics.metric_semantic_definition,
    analytics.platform_metric_capability,
    analytics.institution_metric_aggregate,
    analytics.projection_state,
    analytics.publication_latest,
    analytics.publication_hourly,
    analytics.institution_daily_metrics,
    analytics.institution_monthly_metrics,
    analytics.institution_period_metrics,
    analytics.comparison_cohort,
    analytics.comparison_cohort_member,
    analytics.comparison_metric_point,
    rating.formula_definition,
    rating.formula_component,
    rating.rating_run,
    rating.rating_result,
    rating.rating_component_result,
    ops_and_admin.archive_manifest,
    ops_and_admin.outbox_event,
    ops_and_admin.retention_policy,
    ops_and_admin.operational_checkpoint,
    ops_and_admin.recovery_policy
TO maintenance;
GRANT INSERT, UPDATE, DELETE ON
    analytics.institution_metric_aggregate,
    analytics.projection_state,
    analytics.publication_latest,
    analytics.publication_hourly,
    analytics.institution_daily_metrics,
    analytics.institution_monthly_metrics,
    analytics.institution_period_metrics,
    analytics.comparison_cohort,
    analytics.comparison_cohort_member,
    analytics.comparison_metric_point,
    ops_and_admin.archive_manifest,
    ops_and_admin.outbox_event
TO maintenance;
GRANT INSERT ON analytics.dataset_revision TO maintenance;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA analytics, ops_and_admin TO maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.ensure_publication_metric_partition(date)
    TO maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.drop_publication_metric_partition(date, uuid)
    TO maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_expired_raw_payload(integer)
    TO maintenance;

REVOKE ALL ON SCHEMA migration FROM api_read, api_write_admin, collector_ingest, maintenance;
REVOKE ALL ON ingest.raw_payload FROM api_read, api_write_admin;
REVOKE ALL ON ops_and_admin.audit_log FROM api_read;
REVOKE UPDATE, DELETE, TRUNCATE ON
    ingest.account_metric_snapshot,
    ingest.publication_metric_snapshot,
    ingest.reaction_breakdown,
    ingest.deletion_observation,
    ingest.raw_payload,
    ops_and_admin.audit_log
FROM api_read, collector_ingest;

RESET ROLE;
