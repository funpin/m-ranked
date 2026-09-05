-- 0013 — функции поверх представлений
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.publication_snapshot_slice(uuid, date)
CREATE FUNCTION analytics.publication_snapshot_slice(p_publication uuid, p_month date) RETURNS SETOF analytics.usable_publication_snapshot
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'analytics'
    AS $$
WITH ranked AS MATERIALIZED (
 SELECT snapshot.*, row_number() OVER (
   PARTITION BY snapshot.sampling_bucket ORDER BY snapshot.correction_sequence DESC
 ) AS correction_rank
 FROM ingest.publication_metric_snapshot snapshot
 WHERE snapshot.published_month=p_month AND snapshot.publication_id=p_publication
), active AS (
 SELECT ranked.*, coalesce(ranked.metric_evidence,dictionary.payload) AS resolved_evidence
 FROM ranked LEFT JOIN ingest.metric_evidence_dictionary dictionary ON dictionary.id=ranked.metric_evidence_id
 WHERE correction_rank=1
)
 SELECT visible.published_month,
    visible.id,
    visible.publication_id,
    visible.collection_run_id,
    visible.observed_at,
    visible.age_seconds,
    visible.sampling_bucket,
    visible.views_count,
    visible.reactions_count,
    visible.comments_count,
    visible.shares_count,
    visible.quality,
    visible.interval_uncertain,
    visible.synthetic,
    visible.metric_semantics_version,
    visible.capability_version,
    visible.source_fingerprint,
    visible.created_at,
    visible.collected_at,
    visible.correction_sequence,
    visible.supersedes_snapshot_id,
    visible.correction_reason,
    visible.views_quality,
    visible.reactions_quality,
    visible.comments_quality,
    visible.shares_quality,
    visible.metric_evidence
   FROM (( SELECT s.published_month,
            s.id,
            s.publication_id,
            s.collection_run_id,
            s.observed_at,
            s.age_seconds,
            s.sampling_bucket,
                CASE
                    WHEN (s.views_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.views_count
                END AS views_count,
                CASE
                    WHEN (s.reactions_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.reactions_count
                END AS reactions_count,
                CASE
                    WHEN (s.comments_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.comments_count
                END AS comments_count,
                CASE
                    WHEN (s.shares_quality = ANY (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])) THEN NULL::bigint
                    ELSE s.shares_count
                END AS shares_count,
            analytics.observation_quality_from_rank((COALESCE(( SELECT max(analytics.observation_quality_rank(v.quality)) AS max
                   FROM ( VALUES (s.views_count,s.views_quality), (s.reactions_count,s.reactions_quality), (s.comments_count,s.comments_quality), (s.shares_count,s.shares_quality)) v(value, quality)
                  WHERE ((v.value IS NOT NULL) AND (v.quality <> ALL (ARRAY['invalid'::ingest.observation_quality, 'suspected_reset'::ingest.observation_quality])))), analytics.observation_quality_rank(s.quality)))::integer) AS quality,
            s.interval_uncertain,
            s.synthetic,
            s.metric_semantics_version,
            s.capability_version,
            s.source_fingerprint,
            s.created_at,
            s.collected_at,
            s.correction_sequence,
            s.supersedes_snapshot_id,
            s.correction_reason,
            s.views_quality,
            s.reactions_quality,
            s.comments_quality,
            s.shares_quality,
            s.resolved_evidence AS metric_evidence
           FROM active s) visible
     JOIN ingest.visible_publication publication ON ((publication.id = visible.publication_id)));
$$;

-- ops_and_admin.import_official_rating(jsonb, text, uuid)
CREATE FUNCTION ops_and_admin.import_official_rating(p_payload jsonb, p_actor text, p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'rating', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET statement_timeout TO '15min'
    AS $$
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
    INSERT INTO ops_and_admin.outbox_event(
            dataset_revision_id, event_type, aggregate_type, aggregate_id,
            affected_tags, payload
        ) VALUES (
            revision, 'cache.invalidated', 'cache', 'public',
            ARRAY['publications', 'overview', 'comparison'],
            jsonb_build_object('revision', revision, 'cause', 'configuration')
        )
        ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
        DO NOTHING;
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
END $$;

-- ops_and_admin.legacy_account_presentation(uuid)
CREATE FUNCTION ops_and_admin.legacy_account_presentation(p_account uuid) RETURNS TABLE(access_mode text, last_error_code text, error_present boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ingest'
    SET statement_timeout TO '3s'
    AS $$
    SELECT CASE account.access_mode::text
             WHEN 'public_web' THEN 'public'
             WHEN 'public_api' THEN 'public'
             WHEN 'official_api' THEN 'api'
             WHEN 'user_session' THEN 'user'
             ELSE account.access_mode::text
           END,
           CASE WHEN result.status IN ('failed', 'partial')
                THEN coalesce(result.sanitized_error_code, 'collection_failed') END,
           coalesce(result.status IN ('failed', 'partial'), false)
      FROM catalog.visible_platform_account AS account
      LEFT JOIN LATERAL (
          SELECT status, sanitized_error_code
            FROM ingest.collection_account_result
           WHERE platform_account_id = account.id
             AND completed_at IS NOT NULL
           ORDER BY completed_at DESC, id DESC
           LIMIT 1
      ) AS result ON true
     WHERE account.id = p_account
$$;

-- ops_and_admin.publication_archive_record(date, bigint)
CREATE FUNCTION ops_and_admin.publication_archive_record(p_month date, p_id bigint) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'catalog'
    SET "TimeZone" TO 'UTC'
    AS $$
 SELECT (to_jsonb(s) || jsonb_build_object(
   'primary_account_id',p.primary_account_id,'platform',a.platform,
   'published_at',p.published_at,
   'reaction_breakdown',coalesce((SELECT jsonb_object_agg(r.reaction_key,r.reaction_count ORDER BY r.reaction_key)
     FROM ingest.reaction_breakdown r WHERE r.snapshot_published_month=s.published_month AND r.snapshot_id=s.id),'{}'::jsonb)))::text
 FROM ingest.publication_metric_snapshot_resolved s
 JOIN ingest.publication p ON p.id=s.publication_id
 JOIN catalog.platform_account a ON a.id=p.primary_account_id
 WHERE s.published_month=p_month AND s.id=p_id
$$;
