SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

-- These are representation lexemes, not authoritative metric observations.
-- Unsafe JSON is represented only by its hash and a classified blocking reason.
CREATE TABLE migration.legacy_export_lexeme (
    source_namespace uuid NOT NULL,
    source_table text NOT NULL CHECK(source_table IN ('institutions','channels','platform_accounts','posts',
        'platform_posts','reaction_snapshots','platform_snapshots')),
    source_pk text NOT NULL,source_row_hash text NOT NULL CHECK(source_row_hash ~ '^[0-9a-f]{64}$'),
    fields jsonb NOT NULL CHECK(jsonb_typeof(fields)='object'),
    blocked_reason text CHECK(blocked_reason IN ('UNSAFE_RAW_JSON','UNPARSEABLE_RAW_JSON','FIELD_TOO_LARGE')),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY(source_namespace,source_table,source_pk,source_row_hash)
);
CREATE TRIGGER legacy_export_lexeme_immutable BEFORE UPDATE OR DELETE
    ON migration.legacy_export_lexeme FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER legacy_export_lexeme_no_truncate BEFORE TRUNCATE
    ON migration.legacy_export_lexeme FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();
GRANT SELECT,INSERT ON migration.legacy_export_lexeme TO migration_bridge;
REVOKE ALL ON migration.legacy_export_lexeme FROM PUBLIC,api_read,api_write_admin,collector_ingest;

CREATE TABLE analytics.legacy_native_export_lexeme (
    published_month date NOT NULL,snapshot_id bigint NOT NULL,publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    fields jsonb NOT NULL CHECK(jsonb_typeof(fields)='object'),
    public_fields jsonb NOT NULL CHECK(jsonb_typeof(public_fields)='object'),
    evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
    attribution text NOT NULL DEFAULT 'target-generated-v1' CHECK(attribution='target-generated-v1'),
    PRIMARY KEY(published_month,snapshot_id)
);
CREATE INDEX legacy_native_export_publication_idx ON analytics.legacy_native_export_lexeme(publication_id,snapshot_id DESC);
CREATE TRIGGER legacy_native_export_immutable BEFORE UPDATE OR DELETE ON analytics.legacy_native_export_lexeme
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER legacy_native_export_no_truncate BEFORE TRUNCATE ON analytics.legacy_native_export_lexeme
    FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();
GRANT SELECT,INSERT ON analytics.legacy_native_export_lexeme TO collector_ingest;
GRANT SELECT ON analytics.legacy_native_export_lexeme TO migration_bridge,maintenance;
REVOKE ALL ON analytics.legacy_native_export_lexeme FROM PUBLIC,api_read,api_write_admin;

CREATE FUNCTION ops_and_admin.ensure_publication_legacy_alias(p_publication uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,catalog,ingest AS $function$
DECLARE entity text; result bigint;
BEGIN
    SELECT CASE WHEN account.platform='telegram' THEN 'posts' ELSE 'platform_posts' END INTO entity
        FROM ingest.publication publication JOIN catalog.platform_account account ON account.id=publication.primary_account_id
        WHERE publication.id=p_publication;
    IF entity IS NULL THEN RAISE EXCEPTION 'publication not found' USING ERRCODE='22023'; END IF;
    LOCK TABLE catalog.legacy_entity_alias IN SHARE ROW EXCLUSIVE MODE;
    SELECT legacy_id INTO result FROM catalog.legacy_entity_alias WHERE entity_type=entity AND target_uuid=p_publication;
    IF result IS NOT NULL THEN RETURN result; END IF;
    SELECT coalesce(max(legacy_id),0)+1 INTO result FROM catalog.legacy_entity_alias WHERE entity_type=entity;
    INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route)
        VALUES(entity,result,p_publication,'/'||replace(entity,'_','-')||'/'||result);
    RETURN result;
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.ensure_publication_legacy_alias(uuid) FROM PUBLIC,api_read,api_write_admin;
GRANT EXECUTE ON FUNCTION ops_and_admin.ensure_publication_legacy_alias(uuid) TO collector_ingest,migration_bridge;

CREATE TABLE analytics.legacy_export_row (
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    kind text NOT NULL CHECK(kind IN ('posts','snapshots')),
    namespace text NOT NULL CHECK(namespace IN ('telegram','generic')),
    platform catalog.platform_code NOT NULL,
    ordinal bigint NOT NULL,
    cells text[] NOT NULL,
    blocked_reason text,
    PRIMARY KEY(kind,namespace,ordinal)
);
CREATE INDEX legacy_export_stream_idx ON analytics.legacy_export_row(dataset_revision_id,kind,namespace,ordinal);
CREATE INDEX legacy_export_platform_stream_idx ON analytics.legacy_export_row(dataset_revision_id,kind,namespace,platform,ordinal);
GRANT SELECT ON analytics.legacy_export_row TO api_read,api_write_admin;

CREATE FUNCTION analytics.legacy_csv_timestamp(value timestamptz,lexeme text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $function$
    SELECT CASE WHEN lexeme IS NOT NULL AND lexeme::timestamptz=value THEN lexeme
        ELSE to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
            ||CASE WHEN extract(microseconds FROM value)::bigint%1000000=0 THEN ''
                ELSE '.'||to_char(value AT TIME ZONE 'UTC','US') END||'+00:00' END
$function$;
REVOKE ALL ON FUNCTION analytics.legacy_csv_timestamp(timestamptz,text) FROM PUBLIC;

CREATE FUNCTION analytics.refresh_legacy_exports(p_revision bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,migration,ingest,catalog
AS $function$
DECLARE rows_written bigint;
BEGIN
    -- Per-run temporary relations are private to the definer and dropped at commit.
    DROP TABLE IF EXISTS pg_temp.mranked_csv_lexeme;
    CREATE TEMP TABLE mranked_csv_lexeme ON COMMIT DROP AS
        SELECT mapping.source_table,mapping.source_pk,mapping.target_uuid,mapping.target_bigint,
            mapping.natural_key,lexeme.fields,lexeme.blocked_reason
        FROM migration.legacy_identity_map mapping
        LEFT JOIN migration.legacy_export_lexeme lexeme ON lexeme.source_namespace=mapping.source_namespace
            AND lexeme.source_table=mapping.source_table AND lexeme.source_pk=mapping.source_pk
            AND lexeme.source_row_hash=mapping.source_row_hash
        WHERE mapping.target_type IN ('institution','publication','publication_metric_snapshot','platform_account')
          AND mapping.source_table IN ('institutions','channels','platform_accounts','posts','platform_posts','reaction_snapshots','platform_snapshots');
    CREATE INDEX ON mranked_csv_lexeme(source_table,target_uuid);
    CREATE INDEX ON mranked_csv_lexeme(source_table,target_bigint);
    ANALYZE mranked_csv_lexeme;

    DROP TABLE IF EXISTS pg_temp.mranked_csv_publication;
    CREATE TEMP TABLE mranked_csv_publication ON COMMIT DROP AS
        SELECT publication.id,publication.primary_account_id,account.platform,
            CASE alias.entity_type WHEN 'posts' THEN 'telegram' ELSE 'generic' END AS namespace,
            alias.legacy_id,alias.entity_type,
            CASE WHEN alias.entity_type='posts' THEN
                CASE WHEN btrim(channel_lexeme.fields->>'username')=account.current_username
                    THEN channel_lexeme.fields->>'username' ELSE account.current_username END
                ELSE CASE WHEN (CASE WHEN institution_lexeme.fields->>'short_name'<>''
                    THEN btrim(institution_lexeme.fields->>'short_name') END) IS NOT DISTINCT FROM institution.short_name
                    AND institution_lexeme.fields IS NOT NULL THEN institution_lexeme.fields->>'short_name'
                    ELSE institution.short_name END END AS label,
            coalesce(account_lexeme.fields->>'external_key',account.canonical_external_id) AS account_key,
            coalesce(lexeme.fields->>'telegram_message_id',lexeme.fields->>'external_id',
                native.public_fields->>'telegram_message_id',identity.external_id) AS external_id,
            analytics.legacy_csv_timestamp(publication.published_at,coalesce(lexeme.fields->>'published_at',native.public_fields->>'published_at')) AS published,
            coalesce(lexeme.fields->>'post_type',publication.publication_type) AS post_type,
            CASE WHEN lexeme.fields IS NOT NULL THEN lexeme.fields->>'url' ELSE identity.public_url END AS url,
            CASE WHEN lexeme.fields ? 'history_complete' THEN lexeme.fields->>'history_complete'
                WHEN publication.history_completeness='complete' THEN '1' ELSE '0' END AS history_complete,
            CASE WHEN (lexeme.fields IS NULL AND native.public_fields IS NULL)
                OR (alias.source_hash IS NOT NULL AND alias.entity_type='platform_posts'
                    AND (account_lexeme.fields IS NULL OR institution_lexeme.fields IS NULL))
                OR (alias.source_hash IS NOT NULL AND alias.entity_type='posts' AND channel_lexeme.fields IS NULL)
                THEN 'LEXEMES_MISSING' ELSE lexeme.blocked_reason END AS blocked_reason
        FROM ingest.visible_publication publication
        JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
        JOIN catalog.visible_institution institution ON institution.id=account.institution_id
        JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=publication.id AND alias.entity_type IN ('posts','platform_posts')
        LEFT JOIN pg_temp.mranked_csv_lexeme lexeme ON lexeme.target_uuid=publication.id AND lexeme.source_table=alias.entity_type
        LEFT JOIN pg_temp.mranked_csv_lexeme account_lexeme ON account_lexeme.target_uuid=account.id
            AND account_lexeme.source_table='platform_accounts'
        LEFT JOIN pg_temp.mranked_csv_lexeme channel_lexeme ON channel_lexeme.target_uuid=account.id
            AND channel_lexeme.source_table='channels'
        LEFT JOIN pg_temp.mranked_csv_lexeme institution_lexeme ON institution_lexeme.target_uuid=institution.id
            AND institution_lexeme.source_table='institutions'
        LEFT JOIN LATERAL(SELECT public_fields FROM analytics.legacy_native_export_lexeme
            WHERE publication_id=publication.id ORDER BY snapshot_id DESC LIMIT 1) native ON true
        LEFT JOIN LATERAL(SELECT external_id,public_url FROM ingest.publication_identity
            WHERE publication_id=publication.id AND role='primary' ORDER BY id LIMIT 1) identity ON true;
    CREATE INDEX ON mranked_csv_publication(id,namespace);
    ANALYZE mranked_csv_publication;

    DROP TABLE IF EXISTS pg_temp.mranked_csv_snapshot;
    CREATE TEMP TABLE mranked_csv_snapshot ON COMMIT DROP AS
        SELECT publication.*,snapshot.id AS snapshot_id,snapshot.observed_at,snapshot.age_seconds,
            snapshot.views_count,snapshot.reactions_count,snapshot.comments_count,snapshot.shares_count,
            coalesce(lexeme.source_pk::bigint,snapshot.id) AS source_snapshot_id,
            analytics.legacy_csv_timestamp(snapshot.observed_at,coalesce(lexeme.fields,native.fields)->>'measured_at') AS measured,
            CASE WHEN (coalesce(lexeme.fields,native.fields)->>'age_seconds')::integer=snapshot.age_seconds
                THEN coalesce(lexeme.fields,native.fields)->>'age_hours'
                ELSE (snapshot.age_seconds/3600.0::float8)::text
                    ||CASE WHEN snapshot.age_seconds%3600=0 THEN '.0' ELSE '' END END AS age_hours,
            coalesce(lexeme.fields,native.fields)->>'reactions_json' AS reactions_json,
            coalesce(lexeme.fields,native.fields)->>'raw_json' AS raw_json,
            CASE WHEN lexeme.fields IS NOT NULL THEN lexeme.fields->>'delta_total'
                ELSE (snapshot.reactions_count-lag(snapshot.reactions_count) OVER chronology)::text END AS delta_total,
            CASE WHEN lexeme.fields IS NOT NULL THEN lexeme.fields->>'delta_views'
                ELSE (snapshot.views_count-lag(snapshot.views_count) OVER chronology)::text END AS delta_views,
            CASE WHEN lexeme.fields IS NOT NULL THEN lexeme.fields->>'delta_comments'
                ELSE (snapshot.comments_count-lag(snapshot.comments_count) OVER chronology)::text END AS delta_comments,
            CASE WHEN lexeme.fields IS NULL AND native.fields IS NULL THEN 'LEXEMES_MISSING'
                ELSE coalesce(publication.blocked_reason,lexeme.blocked_reason) END AS snapshot_blocked
        FROM pg_temp.mranked_csv_publication publication
        JOIN ingest.publication_metric_snapshot_active snapshot ON snapshot.publication_id=publication.id
        LEFT JOIN pg_temp.mranked_csv_lexeme lexeme ON lexeme.target_bigint=snapshot.id
            AND lexeme.source_table=CASE publication.namespace WHEN 'telegram' THEN 'reaction_snapshots' ELSE 'platform_snapshots' END
        LEFT JOIN analytics.legacy_native_export_lexeme native ON native.published_month=snapshot.published_month AND native.snapshot_id=snapshot.id
        WHERE lexeme.target_bigint IS NOT NULL OR NOT EXISTS(SELECT 1 FROM pg_temp.mranked_csv_lexeme other
            WHERE other.target_bigint=snapshot.id AND other.source_table IN ('reaction_snapshots','platform_snapshots'))
        WINDOW chronology AS(PARTITION BY publication.id,publication.namespace ORDER BY snapshot.observed_at,snapshot.id);
    CREATE INDEX ON mranked_csv_snapshot(id,namespace,measured DESC,source_snapshot_id);
    ANALYZE mranked_csv_snapshot;

    DELETE FROM analytics.legacy_export_row;
    INSERT INTO analytics.legacy_export_row(dataset_revision_id,kind,namespace,platform,ordinal,cells,blocked_reason)
    SELECT p_revision,'snapshots',namespace,platform,
        row_number() OVER(PARTITION BY namespace ORDER BY
            CASE WHEN namespace='generic' THEN platform::text ELSE '' END COLLATE "C",label COLLATE "C" NULLS FIRST,
            CASE WHEN namespace='telegram' THEN lpad(legacy_id::text,20,'0') ELSE published END COLLATE "C",
            measured COLLATE "C",source_snapshot_id),
        CASE WHEN namespace='telegram' THEN ARRAY[label,external_id,published,measured,age_hours,
            reactions_count::text,delta_total,views_count::text,delta_views,comments_count::text,delta_comments,reactions_json]
        ELSE ARRAY[platform::text,label,account_key,external_id,published,measured,age_hours,
            views_count::text,reactions_count::text,comments_count::text,shares_count::text,raw_json] END,
        snapshot_blocked
    FROM pg_temp.mranked_csv_snapshot;

    INSERT INTO analytics.legacy_export_row(dataset_revision_id,kind,namespace,platform,ordinal,cells,blocked_reason)
    SELECT p_revision,'posts',publication.namespace,publication.platform,
        row_number() OVER(PARTITION BY publication.namespace ORDER BY
            CASE WHEN publication.namespace='generic' THEN publication.platform::text ELSE '' END COLLATE "C",
            publication.label COLLATE "C" NULLS FIRST,publication.published COLLATE "C",publication.legacy_id),
        CASE WHEN publication.namespace='telegram' THEN ARRAY[publication.label,publication.external_id,publication.published,
            publication.history_complete,latest.reactions_count::text,latest.views_count::text,latest.comments_count::text,
            spike.delta_total,spike.age_hours]
        ELSE ARRAY[publication.platform::text,publication.label,publication.account_key,publication.external_id,
            publication.published,publication.post_type,publication.url,latest.views_count::text,
            latest.reactions_count::text,latest.comments_count::text,latest.shares_count::text] END,
        coalesce(publication.blocked_reason,CASE WHEN publication.namespace='telegram' AND EXISTS(
            SELECT 1 FROM pg_temp.mranked_csv_snapshot missing WHERE missing.id=publication.id
                AND missing.namespace=publication.namespace AND missing.snapshot_blocked='LEXEMES_MISSING')
            THEN 'LEXEMES_MISSING' END)
    FROM pg_temp.mranked_csv_publication publication
    LEFT JOIN LATERAL(SELECT snapshot.* FROM pg_temp.mranked_csv_snapshot snapshot
        WHERE snapshot.id=publication.id AND snapshot.namespace=publication.namespace
        ORDER BY measured COLLATE "C" DESC,source_snapshot_id LIMIT 1) latest ON true
    LEFT JOIN LATERAL(SELECT snapshot.delta_total,snapshot.age_hours FROM pg_temp.mranked_csv_snapshot snapshot
        WHERE snapshot.id=publication.id AND snapshot.namespace=publication.namespace
        ORDER BY delta_total::bigint DESC NULLS LAST,measured COLLATE "C" DESC,source_snapshot_id LIMIT 1) spike ON true;
    -- Never silently omit canonical target-native publications without legacy aliases.
    INSERT INTO analytics.legacy_export_row(dataset_revision_id,kind,namespace,platform,ordinal,cells,blocked_reason)
    SELECT p_revision,kind,CASE WHEN account.platform='telegram' THEN 'telegram' ELSE 'generic' END,
        account.platform,-row_number() OVER(PARTITION BY kind,CASE WHEN account.platform='telegram' THEN 'telegram' ELSE 'generic' END ORDER BY publication.id),
        ARRAY[]::text[],'LEXEMES_MISSING'
    FROM ingest.visible_publication publication JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
    CROSS JOIN(VALUES('posts'),('snapshots')) kinds(kind)
    WHERE NOT EXISTS(SELECT 1 FROM catalog.legacy_entity_alias alias WHERE alias.target_uuid=publication.id
        AND alias.entity_type IN ('posts','platform_posts'));
    -- Whole-history legacy exports must not silently become hot-partition-only.
    -- A verified restore/export path is required before these archives can be served.
    INSERT INTO analytics.legacy_export_row(dataset_revision_id,kind,namespace,platform,ordinal,cells,blocked_reason)
    SELECT p_revision,kind,namespace,platform::catalog.platform_code,
        '-9223372036854775808'::bigint+row_number() OVER(PARTITION BY kind,namespace ORDER BY platform),
        ARRAY[]::text[],'COLD_ARCHIVE_RESTORE_REQUIRED'
    FROM (VALUES('posts'),('snapshots')) kinds(kind)
    CROSS JOIN (VALUES('telegram','telegram'),('generic','telegram'),('generic','vk'),('generic','max'),('generic','rutube')) scopes(namespace,platform)
    WHERE EXISTS(SELECT 1 FROM ops_and_admin.archive_manifest
        WHERE dataset_type='publication_metric_snapshot' AND row_count>0 AND hot_dropped_at IS NOT NULL);
    SELECT count(*) INTO rows_written FROM analytics.legacy_export_row;
    INSERT INTO analytics.projection_state(projection_name,dataset_revision_id,status,refreshed_at,row_count)
        VALUES('legacy_exports',p_revision,'ready',transaction_timestamp(),rows_written)
    ON CONFLICT(projection_name) DO UPDATE SET dataset_revision_id=excluded.dataset_revision_id,status='ready',
        refreshed_at=excluded.refreshed_at,row_count=excluded.row_count,error_code=NULL;
    RETURN rows_written;
END $function$;
REVOKE ALL ON FUNCTION analytics.refresh_legacy_exports(bigint) FROM PUBLIC,api_read,api_write_admin;
ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v16;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v16(bigint)
    FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
DECLARE result jsonb;
BEGIN
    result:=analytics.rebuild_core_projections_v16(p_dataset_revision_id);
    RETURN result||jsonb_build_object('legacy_exports',analytics.refresh_legacy_exports(p_dataset_revision_id));
END $function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO api_write_admin,collector_ingest,migration_bridge,maintenance;
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.refresh_legacy_exports(revision); END IF;
END $backfill$;
RESET ROLE;
