-- 0002 — перечисления и домены
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.aggregation_code
CREATE TYPE analytics.aggregation_code AS ENUM (
    'sum',
    'median',
    'mean',
    'minimum',
    'maximum',
    'count',
    'rate',
    'percentile'
);

-- analytics.anomaly_status
CREATE TYPE analytics.anomaly_status AS ENUM (
    'unreviewed',
    'explained',
    'unresolved',
    'data_error',
    'dismissed',
    'superseded'
);

-- analytics.metric_key
CREATE TYPE analytics.metric_key AS ENUM (
    'views',
    'reactions',
    'comments',
    'shares',
    'subscribers',
    'interactions'
);

-- analytics.platform_scope
CREATE TYPE analytics.platform_scope AS ENUM (
    'all',
    'telegram',
    'vk',
    'max',
    'rutube'
);

-- analytics.projection_status
CREATE TYPE analytics.projection_status AS ENUM (
    'ready',
    'rebuilding',
    'failed'
);

-- analytics.review_decision
CREATE TYPE analytics.review_decision AS ENUM (
    'explained',
    'unresolved',
    'data_error',
    'dismissed'
);

-- analytics.revision_cause
CREATE TYPE analytics.revision_cause AS ENUM (
    'ingestion',
    'correction',
    'configuration',
    'analytics',
    'migration',
    'retention'
);

-- catalog.access_mode
CREATE TYPE catalog.access_mode AS ENUM (
    'public_web',
    'telegram_web',
    'mtproto',
    'official_api',
    'public_api',
    'user_session',
    'disabled'
);

-- catalog.institution_status
CREATE TYPE catalog.institution_status AS ENUM (
    'active',
    'inactive',
    'merged'
);

-- catalog.platform_code
CREATE TYPE catalog.platform_code AS ENUM (
    'telegram',
    'vk',
    'max',
    'rutube'
);

-- catalog.verification_status
CREATE TYPE catalog.verification_status AS ENUM (
    'unverified',
    'pending',
    'verified',
    'rejected',
    'expired'
);

-- ingest.deletion_probe_outcome
CREATE TYPE ingest.deletion_probe_outcome AS ENUM (
    'present',
    'missing',
    'transient_error',
    'confirmed_deleted',
    'unsupported'
);

-- ingest.history_completeness
CREATE TYPE ingest.history_completeness AS ENUM (
    'complete',
    'incomplete',
    'forced_incomplete'
);

-- ingest.observation_quality
CREATE TYPE ingest.observation_quality AS ENUM (
    'unknown',
    'rounded',
    'estimated',
    'exact',
    'degraded',
    'suspected_reset',
    'invalid'
);

-- ingest.publication_account_role
CREATE TYPE ingest.publication_account_role AS ENUM (
    'primary',
    'album_member',
    'joint_author',
    'source',
    'repost_source'
);

-- ingest.raw_owner_type
CREATE TYPE ingest.raw_owner_type AS ENUM (
    'account',
    'publication',
    'snapshot',
    'run',
    'migration'
);

-- ingest.run_status
CREATE TYPE ingest.run_status AS ENUM (
    'pending',
    'running',
    'succeeded',
    'partial',
    'failed',
    'skipped',
    'cancelled'
);

-- ops_and_admin.archive_status
CREATE TYPE ops_and_admin.archive_status AS ENUM (
    'staging',
    'verified',
    'hot_dropped',
    'expired',
    'failed'
);

-- rating.formula_status
CREATE TYPE rating.formula_status AS ENUM (
    'draft',
    'in_review',
    'published',
    'retired'
);
