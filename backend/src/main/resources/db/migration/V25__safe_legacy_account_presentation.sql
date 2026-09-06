-- The admin presentation preserves a known source label separately from the
-- canonical collector protocol. No raw evidence grants or raw errors are exposed.
SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='5min';

CREATE FUNCTION ops_and_admin.legacy_account_presentation(p_account uuid)
RETURNS TABLE(access_mode text,last_error_code text,error_present boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,catalog,migration
SET statement_timeout='3s'
AS $function$
    WITH context AS (
        SELECT account.platform,account.access_mode::text AS canonical_mode,
            retained.evidence->>'access_mode' AS source_mode,
            coalesce(retained.evidence->'last_error'->'present'='true'::jsonb,
                retained.prior_error->'present'='true'::jsonb,false) AS has_error
        FROM catalog.visible_platform_account account
        LEFT JOIN LATERAL (
            SELECT presentation.evidence,prior_error.evidence AS prior_error
            FROM migration.legacy_identity_map mapping
            LEFT JOIN migration.legacy_evidence presentation
                ON presentation.batch_id=mapping.last_seen_batch_id AND presentation.source_table=mapping.source_table
                AND presentation.source_pk=mapping.source_pk AND presentation.source_row_hash=mapping.source_row_hash
                AND presentation.evidence_kind='legacy_account_presentation' AND presentation.sanitized
            LEFT JOIN migration.legacy_evidence prior_error
                ON prior_error.batch_id=mapping.last_seen_batch_id AND prior_error.source_table=mapping.source_table
                AND prior_error.source_pk=mapping.source_pk AND prior_error.source_row_hash=mapping.source_row_hash
                AND prior_error.evidence_kind='sanitized_last_error' AND prior_error.sanitized
            WHERE mapping.target_uuid=account.id AND mapping.target_type='platform_account'
                AND mapping.source_table='platform_accounts'
            ORDER BY coalesce(presentation.created_at,prior_error.created_at,mapping.mapped_at) DESC,
                mapping.id DESC LIMIT 1
        ) retained ON true
        WHERE account.id=p_account
    ), modes AS (
        SELECT context.*,
            CASE source_mode
                WHEN 'public' THEN CASE WHEN platform='telegram' THEN 'public_web' ELSE 'public_api' END
                WHEN 'api' THEN 'official_api' WHEN 'official' THEN 'official_api'
                WHEN 'user' THEN 'user_session' WHEN 'user_api' THEN 'user_session'
                WHEN 'owner' THEN CASE platform WHEN 'max' THEN 'user_session' WHEN 'vk' THEN 'official_api'
                    WHEN 'rutube' THEN 'public_api' ELSE 'public_web' END
                WHEN 'public_web' THEN 'public_web' WHEN 'telegram_web' THEN 'telegram_web'
                WHEN 'mtproto' THEN 'mtproto' WHEN 'official_api' THEN 'official_api'
                WHEN 'public_api' THEN 'public_api' WHEN 'user_session' THEN 'user_session'
                WHEN 'disabled' THEN 'disabled' ELSE NULL END AS normalized_source_mode
        FROM context
    )
    SELECT CASE WHEN normalized_source_mode=canonical_mode THEN source_mode
        WHEN canonical_mode IN ('public_web','public_api') OR (platform='vk' AND canonical_mode='official_api') THEN 'public'
        ELSE canonical_mode END,
        CASE WHEN has_error THEN 'legacy_collection_error' ELSE NULL END,has_error
    FROM modes
$function$;
REVOKE ALL ON FUNCTION ops_and_admin.legacy_account_presentation(uuid) FROM PUBLIC,api_read,collector_ingest,migration_bridge,maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.legacy_account_presentation(uuid) TO api_write_admin;
RESET ROLE;
