SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

CREATE TABLE rating.official_account_rating_observation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    period text NOT NULL,rank integer CHECK(rank IS NULL OR rank>0),score numeric,
    source_url text NOT NULL CHECK(source_url ~ '^https://'),source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
    fetched_at timestamptz NOT NULL,UNIQUE(platform_account_id,period,source_hash)
);
CREATE INDEX official_account_rating_latest_idx ON rating.official_account_rating_observation(platform_account_id,fetched_at DESC,id DESC);
CREATE TRIGGER official_account_rating_immutable BEFORE UPDATE OR DELETE ON rating.official_account_rating_observation
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
GRANT SELECT ON rating.official_account_rating_observation TO api_read,api_write_admin,maintenance;
CREATE TABLE rating.official_import (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),actor text NOT NULL,correlation_id uuid NOT NULL,
    period text NOT NULL,source_url text NOT NULL CHECK(source_url ~ '^https://'),
    source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),fetched_at timestamptz NOT NULL,
    evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),evidence_sha256 text NOT NULL,
    UNIQUE(actor,correlation_id)
);
CREATE TRIGGER official_import_immutable BEFORE UPDATE OR DELETE ON rating.official_import
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
GRANT SELECT ON rating.official_import TO maintenance;

-- Preserve per-channel official ranks when several Telegram channels belong to
-- one institution. Rank/score come from actual observations, mapping only links identities.
INSERT INTO rating.official_account_rating_observation(platform_account_id,period,rank,score,source_url,source_hash,fetched_at)
SELECT DISTINCT alias.target_uuid,observation.period,observation.rank,observation.score,observation.source_url,observation.source_hash,observation.fetched_at
FROM rating.official_rating_observation observation
JOIN migration.legacy_identity_map mapping ON mapping.target_uuid=observation.id
    AND mapping.source_table='channels' AND mapping.target_type='official_rating_observation:telegram'
JOIN catalog.legacy_entity_alias alias ON alias.entity_type='channels' AND alias.legacy_id::text=mapping.source_pk
ON CONFLICT DO NOTHING;

CREATE FUNCTION analytics.refresh_official_account_ratings(p_revision bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,rating AS $function$
DECLARE written bigint;
BEGIN
    -- A bridge may run after this migration. Copy only independently stored
    -- official observations; migration metadata supplies the channel identity.
    INSERT INTO rating.official_account_rating_observation(platform_account_id,period,rank,score,source_url,source_hash,fetched_at)
    SELECT DISTINCT alias.target_uuid,observation.period,observation.rank,observation.score,observation.source_url,observation.source_hash,observation.fetched_at
    FROM rating.official_rating_observation observation
    JOIN migration.legacy_identity_map mapping ON mapping.target_uuid=observation.id
        AND mapping.source_table='channels' AND mapping.target_type='official_rating_observation:telegram'
    JOIN catalog.legacy_entity_alias alias ON alias.entity_type='channels' AND alias.legacy_id::text=mapping.source_pk
    ON CONFLICT DO NOTHING;
    WITH latest AS (
        SELECT DISTINCT ON(observation.platform_account_id) observation.*
        FROM rating.official_account_rating_observation observation JOIN analytics.dataset_revision revision ON revision.id=p_revision
        WHERE observation.fetched_at<=revision.committed_at ORDER BY observation.platform_account_id,observation.fetched_at DESC,observation.id DESC
    ) UPDATE analytics.legacy_overview_card card SET rating_rank=latest.rank,rating_score=latest.score,
        rating_period=latest.period,rating_fetched_at=latest.fetched_at
      FROM latest WHERE card.platform='telegram' AND card.entity_id=latest.platform_account_id AND card.dataset_revision_id=p_revision;
    GET DIAGNOSTICS written=ROW_COUNT;RETURN written;
END $function$;
REVOKE ALL ON FUNCTION analytics.refresh_official_account_ratings(bigint) FROM PUBLIC;
ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v17;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v17(bigint) FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
DECLARE result jsonb;
BEGIN
    result:=analytics.rebuild_core_projections_v17(p_dataset_revision_id);
    RETURN result||jsonb_build_object('official_account_ratings',analytics.refresh_official_account_ratings(p_dataset_revision_id));
END $function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint) TO api_write_admin,collector_ingest,migration_bridge,maintenance;

CREATE FUNCTION ops_and_admin.previous_official_rating(p_actor text,p_correlation uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,ops_and_admin AS $function$
DECLARE response jsonb;
BEGIN
    SELECT receipt.response INTO response FROM ops_and_admin.catalog_command_receipt receipt WHERE actor=p_actor AND correlation_id=p_correlation;
    IF response IS NOT NULL AND response->>'kind' IS DISTINCT FROM 'official_rating' THEN RETURN '{"outcome":"idempotency_conflict"}'::jsonb; END IF;
    RETURN response;
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.previous_official_rating(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.previous_official_rating(text,uuid) TO api_write_admin;

CREATE FUNCTION ops_and_admin.import_official_rating(p_payload jsonb,p_actor text,p_correlation uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,catalog,rating,analytics,ops_and_admin
SET lock_timeout='10s' SET statement_timeout='15min' AS $function$
DECLARE response jsonb;before_state jsonb;import_id uuid;revision bigint;item jsonb;updated integer;observation_hash text;
    request_digest text:=encode(sha256(convert_to('official_rating.refresh','UTF8')),'hex');
BEGIN
    IF p_actor IS NULL OR btrim(p_actor)='' OR length(p_actor)>200 OR p_actor ~ '[[:cntrl:]]' OR p_correlation IS NULL
        OR jsonb_typeof(p_payload)<>'object' OR jsonb_typeof(p_payload->'institutions')<>'array'
        OR jsonb_typeof(p_payload->'accounts')<>'array' OR jsonb_array_length(p_payload->'institutions')>50000
        OR jsonb_array_length(p_payload->'accounts')>10000 THEN RAISE EXCEPTION 'invalid official import' USING ERRCODE='22023'; END IF;
    PERFORM pg_advisory_xact_lock(782194601);
    response:=ops_and_admin.previous_official_rating(p_actor,p_correlation);
    IF response IS NOT NULL THEN RETURN response; END IF;
    -- Each successful fetch is a distinct observation, including an unchanged
    -- document fetched later. The immutable import retains the document hash.
    observation_hash:=encode(sha256(convert_to((p_payload->>'sourceSha256')||':'||(p_payload->>'fetchedAt'),'UTF8')),'hex');
    SELECT value INTO before_state FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='admin.m_rating' AND scope_type='system';
    INSERT INTO rating.official_import(actor,correlation_id,period,source_url,source_hash,fetched_at,evidence,evidence_sha256)
        VALUES(p_actor,p_correlation,p_payload->>'period',p_payload->>'sourceUrl',p_payload->>'sourceSha256',
            (p_payload->>'fetchedAt')::timestamptz,p_payload->'evidence',encode(sha256(convert_to((p_payload->'evidence')::text,'UTF8')),'hex'))
        RETURNING id INTO import_id;
    FOR item IN SELECT value FROM jsonb_array_elements(p_payload->'institutions') LOOP
        IF item->>'category' NOT IN ('social','telegram','vk','max','rutube') THEN RAISE EXCEPTION 'invalid category' USING ERRCODE='22023'; END IF;
        IF NOT EXISTS(SELECT 1 FROM catalog.visible_institution WHERE id=(item->>'institutionId')::uuid) THEN
            RAISE EXCEPTION 'catalog changed during official fetch' USING ERRCODE='40001'; END IF;
        INSERT INTO rating.official_rating_observation(institution_id,category,period,rank,score,source_url,source_hash,fetched_at)
            VALUES((item->>'institutionId')::uuid,item->>'category',p_payload->>'period',(item->>'rank')::integer,(item->>'score')::numeric,
                p_payload->>'sourceUrl',observation_hash,(p_payload->>'fetchedAt')::timestamptz)
            ON CONFLICT(institution_id,category,period,source_hash) DO NOTHING;
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(p_payload->'accounts') LOOP
        IF NOT EXISTS(SELECT 1 FROM catalog.visible_platform_account WHERE id=(item->>'accountId')::uuid AND platform='telegram') THEN
            RAISE EXCEPTION 'catalog changed during official fetch' USING ERRCODE='40001'; END IF;
        INSERT INTO rating.official_account_rating_observation(platform_account_id,period,rank,score,source_url,source_hash,fetched_at)
            VALUES((item->>'accountId')::uuid,p_payload->>'period',(item->>'rank')::integer,(item->>'score')::numeric,
                p_payload->>'sourceUrl',observation_hash,(p_payload->>'fetchedAt')::timestamptz)
            ON CONFLICT(platform_account_id,period,source_hash) DO NOTHING;
    END LOOP;
    SELECT count(DISTINCT value->>'institutionId') INTO updated FROM jsonb_array_elements(p_payload->'institutions');
    INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES('configuration',p_correlation) RETURNING id INTO revision;
    PERFORM analytics.rebuild_core_projections(revision);
    response:=jsonb_build_object('kind','official_rating','period',p_payload->>'period','updated',updated,
        'available',(p_payload->>'available')::integer,'fetchedAt',p_payload->>'fetchedAt','datasetRevision',revision);
    INSERT INTO ops_and_admin.operational_checkpoint(checkpoint_key,scope_type,value,source_observed_at,correlation_id)
        VALUES('admin.m_rating','system',jsonb_build_object('period',p_payload->>'period','updatedAt',p_payload->>'fetchedAt','error',NULL),
            (p_payload->>'fetchedAt')::timestamptz,p_correlation)
        ON CONFLICT(checkpoint_key,scope_type,scope_id,platform) DO UPDATE SET value=excluded.value,source_observed_at=excluded.source_observed_at,
            updated_at=transaction_timestamp(),correlation_id=excluded.correlation_id;
    INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,before_state,after_state,outcome)
        VALUES(p_actor,'official_rating.refresh','official_rating_import',import_id,p_correlation,before_state,
            response||jsonb_build_object('sourceSha256',p_payload->>'sourceSha256'),'succeeded');
    INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,aggregate_id,affected_tags,payload)
        VALUES(revision,'official_rating.updated','official_rating_import',import_id::text,ARRAY['rating','overview','catalog'],response);
    INSERT INTO ops_and_admin.catalog_command_receipt(actor,correlation_id,request_digest,response) VALUES(p_actor,p_correlation,request_digest,response);
    RETURN response;
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.import_official_rating(jsonb,text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.import_official_rating(jsonb,text,uuid) TO api_write_admin;
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.refresh_official_account_ratings(revision); END IF;
END $backfill$;
RESET ROLE;
