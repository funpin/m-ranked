-- 0003 — catalog — справочник учреждений и аккаунтов
-- Порождается из каталога эталонной базы; см. db/README.md.

-- catalog.institution
CREATE TABLE catalog.institution (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    canonical_name text NOT NULL,
    short_name text,
    status catalog.institution_status DEFAULT 'active'::catalog.institution_status NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    row_version bigint DEFAULT 0 NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT institution_canonical_name_check CHECK ((btrim(canonical_name) <> ''::text)),
    CONSTRAINT institution_check CHECK ((updated_at >= created_at)),
    CONSTRAINT institution_row_version_check CHECK ((row_version >= 0)),
    CONSTRAINT institution_short_name_check CHECK (((short_name IS NULL) OR (btrim(short_name) <> ''::text)))
);

-- catalog.platform_account
CREATE TABLE catalog.platform_account (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    platform catalog.platform_code NOT NULL,
    canonical_external_id text NOT NULL,
    current_username text,
    current_title text,
    current_url text,
    access_mode catalog.access_mode NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    row_version bigint DEFAULT 0 NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT deleted_account_is_disabled CHECK (((deleted_at IS NULL) OR (NOT enabled))),
    CONSTRAINT platform_account_canonical_external_id_check CHECK ((btrim(canonical_external_id) <> ''::text)),
    CONSTRAINT platform_account_check CHECK ((updated_at >= created_at)),
    CONSTRAINT platform_account_row_version_check CHECK ((row_version >= 0)),
    CONSTRAINT platform_account_web_url CHECK (((current_url IS NULL) OR (current_url ~* '^https?://'::text)))
);

-- catalog.account_external_identity
CREATE TABLE catalog.account_external_identity (
    id bigint NOT NULL,
    platform_account_id uuid NOT NULL,
    identity_namespace text NOT NULL,
    external_id text NOT NULL,
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    verified_at timestamp with time zone,
    source_run_id uuid,
    CONSTRAINT account_external_identity_check CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT account_external_identity_external_id_check CHECK ((btrim(external_id) <> ''::text)),
    CONSTRAINT account_external_identity_identity_namespace_check CHECK ((btrim(identity_namespace) <> ''::text))
);

-- catalog.account_identity_history
CREATE TABLE catalog.account_identity_history (
    id bigint NOT NULL,
    platform_account_id uuid NOT NULL,
    username text,
    title text,
    url text,
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    source_run_id uuid,
    CONSTRAINT account_history_web_url CHECK (((url IS NULL) OR (url ~* '^https?://'::text))),
    CONSTRAINT account_identity_history_check CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))
);

-- catalog.account_verification
CREATE TABLE catalog.account_verification (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    platform_account_id uuid NOT NULL,
    status catalog.verification_status NOT NULL,
    method text NOT NULL,
    evidence_url text,
    verified_by_subject text,
    verified_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone,
    CONSTRAINT account_verification_check CHECK (((expires_at IS NULL) OR (expires_at > verified_at))),
    CONSTRAINT account_verification_evidence_url_check CHECK (((evidence_url IS NULL) OR (evidence_url ~ '^https://'::text))),
    CONSTRAINT account_verification_method_check CHECK ((btrim(method) <> ''::text))
);

-- catalog.institution_external_id
CREATE TABLE catalog.institution_external_id (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    namespace text NOT NULL,
    external_id text NOT NULL,
    valid_from timestamp with time zone NOT NULL,
    valid_to timestamp with time zone,
    verified_at timestamp with time zone,
    CONSTRAINT institution_external_id_check CHECK (((valid_to IS NULL) OR (valid_to > valid_from))),
    CONSTRAINT institution_external_id_external_id_check CHECK ((btrim(external_id) <> ''::text)),
    CONSTRAINT institution_external_id_namespace_check CHECK ((btrim(namespace) <> ''::text))
);

-- catalog.legacy_entity_alias
CREATE TABLE catalog.legacy_entity_alias (
    entity_type text NOT NULL,
    legacy_id bigint NOT NULL,
    target_uuid uuid NOT NULL,
    legacy_route text,
    source_hash text,
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT legacy_entity_alias_entity_type_check CHECK ((entity_type = ANY (ARRAY['institutions'::text, 'channels'::text, 'platform_accounts'::text, 'posts'::text, 'platform_posts'::text]))),
    CONSTRAINT legacy_entity_alias_legacy_id_check CHECK ((legacy_id > 0)),
    CONSTRAINT legacy_entity_alias_source_hash_check CHECK (((source_hash IS NULL) OR (source_hash ~ '^[0-9a-f]{64}$'::text)))
);
