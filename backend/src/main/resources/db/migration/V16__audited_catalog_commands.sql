-- Administrative removal hides the monitoring enrollment, never erases source
-- observations. A subsequent enrollment receives new UUID and legacy aliases.
SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';
ALTER TABLE catalog.institution ADD COLUMN deleted_at timestamptz;
ALTER TABLE catalog.platform_account ADD COLUMN deleted_at timestamptz;
ALTER TABLE catalog.platform_account ADD CONSTRAINT deleted_account_is_disabled
    CHECK(deleted_at IS NULL OR NOT enabled);
ALTER TABLE catalog.platform_account DROP CONSTRAINT platform_account_platform_canonical_external_id_key;
CREATE UNIQUE INDEX platform_account_active_canonical_uq
    ON catalog.platform_account(platform,canonical_external_id) WHERE deleted_at IS NULL;
CREATE VIEW catalog.visible_institution AS SELECT * FROM catalog.institution WHERE deleted_at IS NULL;
CREATE VIEW catalog.visible_platform_account AS SELECT account.* FROM catalog.platform_account account
    JOIN catalog.visible_institution institution ON institution.id=account.institution_id
    WHERE account.deleted_at IS NULL;
CREATE VIEW ingest.visible_publication AS SELECT publication.* FROM ingest.publication publication
    JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id;
GRANT SELECT ON catalog.visible_institution,catalog.visible_platform_account,ingest.visible_publication
    TO api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;

-- Keep the exact existing formulas and output column contracts. Only their
-- catalog/publication input relations change. This list is deliberately closed.
DO $migration$
DECLARE signature text; definition text;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'analytics.rebuild_core_projections(bigint)',
        'analytics.rebuild_core_projections_v2(bigint)',
        'analytics.rebuild_core_projections_v5(bigint)',
        'analytics.rebuild_core_projections_v6(bigint)',
        'analytics.rebuild_core_projections_v9(bigint)',
        'analytics.rebuild_core_projections_v11(bigint)',
        'analytics.rebuild_core_projections_v13(bigint)',
        'analytics.refresh_publication_content(bigint)'
    ] LOOP
        definition:=pg_get_functiondef(signature::regprocedure);
        definition:=regexp_replace(definition,'catalog\.platform_account\M','catalog.visible_platform_account','g');
        definition:=regexp_replace(definition,'catalog\.institution\M','catalog.visible_institution','g');
        definition:=regexp_replace(definition,'ingest\.publication\M','ingest.visible_publication','g');
        EXECUTE definition;
    END LOOP;
    definition:=pg_get_viewdef('analytics.usable_publication_snapshot'::regclass,true);
    EXECUTE 'CREATE OR REPLACE VIEW analytics.usable_publication_snapshot AS SELECT visible.* FROM ('
        ||rtrim(definition,E';\n ')||') visible JOIN ingest.visible_publication publication ON publication.id=visible.publication_id';
END $migration$;

CREATE TABLE ops_and_admin.catalog_command_receipt (
    actor text NOT NULL, correlation_id uuid NOT NULL, request_digest text NOT NULL,
    response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY(actor,correlation_id), CHECK(request_digest ~ '^[0-9a-f]{64}$')
);
CREATE TRIGGER catalog_command_receipt_immutable BEFORE UPDATE OR DELETE
    ON ops_and_admin.catalog_command_receipt FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
REVOKE ALL ON ops_and_admin.catalog_command_receipt FROM PUBLIC,api_write_admin;

CREATE FUNCTION ops_and_admin.allocate_catalog_alias(p_type text,p_target uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,catalog AS $function$
DECLARE result bigint;
BEGIN
    IF p_type NOT IN ('institutions','channels','platform_accounts') THEN RAISE EXCEPTION 'unsupported alias'; END IF;
    -- Serialize with bridge's alias inserts as well as concurrent admin requests.
    LOCK TABLE catalog.legacy_entity_alias IN SHARE ROW EXCLUSIVE MODE;
    SELECT legacy_id INTO result FROM catalog.legacy_entity_alias WHERE entity_type=p_type AND target_uuid=p_target;
    IF result IS NOT NULL THEN RETURN result; END IF;
    SELECT coalesce(max(legacy_id),0)+1 INTO result FROM catalog.legacy_entity_alias WHERE entity_type=p_type;
    INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route)
        VALUES(p_type,result,p_target,'/'||replace(p_type,'_','-')||'/'||result);
    RETURN result;
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.allocate_catalog_alias(text,uuid) FROM PUBLIC,api_write_admin;

CREATE FUNCTION ops_and_admin.catalog_command(p_action text,p_target uuid,p_expected bigint,
    p_body jsonb,p_actor text,p_correlation uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,catalog,analytics,ops_and_admin
SET lock_timeout='10s' SET statement_timeout='15min' AS $function$
DECLARE
    before_state jsonb; after_state jsonb; result jsonb; receipt ops_and_admin.catalog_command_receipt%ROWTYPE;
    account catalog.platform_account%ROWTYPE; institution catalog.institution%ROWTYPE;
    target uuid:=p_target; parent uuid; previous_parent uuid; revision bigint; alias_id bigint;
    request_digest text; outcome text:='succeeded'; target_type text; transition timestamptz;
    native_value text; old_native text; identity_changed boolean:=false;
BEGIN
    IF p_actor IS NULL OR btrim(p_actor)='' OR length(p_actor)>200 OR p_actor ~ '[[:cntrl:]]'
       OR p_correlation IS NULL OR jsonb_typeof(p_body)<>'object' THEN
        RAISE EXCEPTION 'invalid command envelope' USING ERRCODE='22023';
    END IF;
    IF p_action NOT IN ('institution.create','institution.update','institution.delete',
        'account.upsert','channel.upsert','account.enable','account.disable','account.delete','channel.delete','account.native_id') THEN
        RAISE EXCEPTION 'unsupported catalog command' USING ERRCODE='22023';
    END IF;
    -- Lock order is shared by all catalog commands, including concurrent replay.
    PERFORM pg_advisory_xact_lock(782194601);
    request_digest:=encode(sha256(convert_to(jsonb_build_object('action',p_action,'target',p_target,
        'expected',p_expected,'body',p_body)::text,'UTF8')),'hex');
    SELECT * INTO receipt FROM ops_and_admin.catalog_command_receipt WHERE actor=p_actor AND correlation_id=p_correlation;
    IF FOUND THEN
        IF receipt.request_digest<>request_digest THEN RETURN jsonb_build_object('outcome','idempotency_conflict'); END IF;
        RETURN receipt.response;
    END IF;
    target_type:=CASE WHEN p_action LIKE 'institution.%' THEN 'institution' ELSE 'platform_account' END;
    IF p_action='institution.create' THEN
        IF btrim(coalesce(p_body->>'name',''))='' OR length(p_body->>'name')>1000 THEN
            RAISE EXCEPTION 'institution name is required' USING ERRCODE='22023'; END IF;
        INSERT INTO catalog.institution(canonical_name,short_name,status)
            VALUES(btrim(p_body->>'name'),coalesce(nullif(btrim(p_body->>'shortName'),''),btrim(p_body->>'name')),'active')
            RETURNING * INTO institution;
        target:=institution.id;
        alias_id:=ops_and_admin.allocate_catalog_alias('institutions',target);
        after_state:=to_jsonb(institution);
    ELSIF p_action LIKE 'institution.%' THEN
        SELECT * INTO institution FROM catalog.institution WHERE id=target AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSE
            before_state:=to_jsonb(institution);
            IF p_expected IS NULL OR p_expected<>institution.row_version THEN outcome:='version_conflict';
            ELSIF p_action='institution.update' THEN
                IF btrim(coalesce(p_body->>'name',''))='' OR btrim(coalesce(p_body->>'shortName',''))=''
                   OR length(p_body->>'name')>1000 OR length(p_body->>'shortName')>1000 THEN
                    RAISE EXCEPTION 'institution names are required' USING ERRCODE='22023'; END IF;
                UPDATE catalog.institution SET canonical_name=btrim(p_body->>'name'),short_name=btrim(p_body->>'shortName'),
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO institution;
            ELSE
                UPDATE catalog.platform_account SET deleted_at=transaction_timestamp(),enabled=false,
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE institution_id=target AND deleted_at IS NULL;
                UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                    updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO institution;
            END IF;
            after_state:=to_jsonb(institution);
        END IF;
    ELSIF p_action IN ('account.upsert','channel.upsert') THEN
        parent:=(p_body->>'institutionId')::uuid;
        IF p_action='channel.upsert' THEN
            IF p_body->>'platform'<>'telegram' THEN RAISE EXCEPTION 'channel platform must be telegram' USING ERRCODE='22023'; END IF;
            SELECT institution_id INTO parent FROM catalog.platform_account WHERE platform='telegram' AND deleted_at IS NULL
                AND lower(current_username)=lower(p_body->>'username') ORDER BY id LIMIT 1 FOR UPDATE;
            IF parent IS NULL THEN
                INSERT INTO catalog.institution(canonical_name,short_name) VALUES('@'||(p_body->>'username'),'@'||(p_body->>'username'))
                    RETURNING id INTO parent;
                PERFORM ops_and_admin.allocate_catalog_alias('institutions',parent);
            END IF;
        END IF;
        SELECT * INTO institution FROM catalog.institution WHERE id=parent AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSIF p_body ? 'expectedInstitutionVersion' AND institution.row_version<>(p_body->>'expectedInstitutionVersion')::bigint
            THEN outcome:='version_conflict';
        ELSE
            SELECT * INTO account FROM catalog.platform_account WHERE deleted_at IS NULL
                AND platform=(p_body->>'platform')::catalog.platform_code
                AND (canonical_external_id=p_body->>'externalKey' OR lower(current_username)=lower(p_body->>'username'))
                ORDER BY id LIMIT 1 FOR UPDATE;
            IF FOUND THEN
                target:=account.id; before_state:=to_jsonb(account); previous_parent:=account.institution_id;
                IF (p_expected IS NOT NULL AND p_expected<>account.row_version)
                    OR (p_body ? 'expectedAccountVersions' AND (
                        NOT (p_body->'expectedAccountVersions' ? target::text)
                        OR (p_body->'expectedAccountVersions'->>target::text)::bigint<>account.row_version))
                    THEN outcome:='version_conflict';
                ELSE
                    identity_changed:=account.current_username IS DISTINCT FROM p_body->>'username'
                        OR (p_body->>'title' IS NOT NULL AND account.current_title IS DISTINCT FROM p_body->>'title')
                        OR (p_body->>'url' IS NOT NULL AND account.current_url IS DISTINCT FROM p_body->>'url');
                    UPDATE catalog.platform_account SET institution_id=parent,enabled=true,
                        current_username=p_body->>'username',current_title=coalesce(p_body->>'title',current_title),
                        current_url=coalesce(p_body->>'url',current_url),access_mode=(p_body->>'accessMode')::catalog.access_mode,
                        row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO account;
                END IF;
            ELSE
                INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,current_username,
                    current_title,current_url,access_mode) VALUES(parent,(p_body->>'platform')::catalog.platform_code,
                    p_body->>'externalKey',p_body->>'username',p_body->>'title',p_body->>'url',(p_body->>'accessMode')::catalog.access_mode)
                    RETURNING * INTO account;
                target:=account.id; identity_changed:=true;
                alias_id:=ops_and_admin.allocate_catalog_alias('platform_accounts',target);
                IF account.platform='telegram' THEN PERFORM ops_and_admin.allocate_catalog_alias('channels',target); END IF;
            END IF;
            IF outcome='succeeded' AND identity_changed THEN
                SELECT greatest(transaction_timestamp(),max(valid_from)+interval '1 microsecond') INTO transition
                    FROM catalog.account_identity_history WHERE platform_account_id=target AND valid_to IS NULL;
                UPDATE catalog.account_identity_history SET valid_to=transition WHERE platform_account_id=target AND valid_to IS NULL;
                INSERT INTO catalog.account_identity_history(platform_account_id,username,title,url,valid_from)
                    VALUES(target,account.current_username,account.current_title,account.current_url,transition);
            END IF;
            -- Legacy moving a Telegram channel removes its now-empty auto institution.
            IF outcome='succeeded' AND account.platform='telegram' AND previous_parent IS DISTINCT FROM parent
               AND previous_parent IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog.platform_account
                    WHERE institution_id=previous_parent AND deleted_at IS NULL) THEN
                UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                    updated_at=transaction_timestamp() WHERE id=previous_parent;
            END IF;
            after_state:=to_jsonb(account);
        END IF;
    ELSE
        SELECT * INTO account FROM catalog.platform_account WHERE id=target AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSE
            before_state:=to_jsonb(account);
            IF p_expected IS NULL OR p_expected<>account.row_version THEN outcome:='version_conflict';
            ELSE
                IF p_action='account.native_id' THEN
                    native_value:=nullif(btrim(p_body->>'nativeId'),'');
                    IF account.platform='max' AND native_value IS NOT NULL AND native_value !~ '^-?[0-9]+$' THEN
                        RAISE EXCEPTION 'MAX chat_id must be numeric' USING ERRCODE='22023'; END IF;
                    SELECT external_id INTO old_native FROM catalog.account_external_identity WHERE platform_account_id=target
                        AND identity_namespace=account.platform::text||':native_id' AND valid_to IS NULL FOR UPDATE;
                    IF old_native IS DISTINCT FROM native_value THEN
                        SELECT greatest(transaction_timestamp(),max(valid_from)+interval '1 microsecond') INTO transition
                            FROM catalog.account_external_identity WHERE platform_account_id=target
                            AND identity_namespace=account.platform::text||':native_id' AND valid_to IS NULL;
                        UPDATE catalog.account_external_identity SET valid_to=transition WHERE platform_account_id=target
                            AND identity_namespace=account.platform::text||':native_id' AND valid_to IS NULL;
                        IF native_value IS NOT NULL THEN
                            INSERT INTO catalog.account_external_identity(platform_account_id,identity_namespace,external_id,valid_from,verified_at)
                                VALUES(target,account.platform::text||':native_id',native_value,transition,transition);
                        END IF;
                    END IF;
                    before_state:=before_state||jsonb_build_object('native_id',old_native);
                END IF;
                UPDATE catalog.platform_account SET enabled=CASE WHEN p_action='account.enable' THEN true
                        WHEN p_action IN ('account.disable','account.delete','channel.delete') THEN false ELSE enabled END,
                    deleted_at=CASE WHEN p_action IN ('account.delete','channel.delete') THEN transaction_timestamp() ELSE deleted_at END,
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO account;
                IF p_action='channel.delete' AND NOT EXISTS(SELECT 1 FROM catalog.platform_account
                    WHERE institution_id=account.institution_id AND deleted_at IS NULL) THEN
                    UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                        updated_at=transaction_timestamp() WHERE id=account.institution_id;
                END IF;
            END IF;
            after_state:=to_jsonb(account);
            IF p_action='account.native_id' THEN after_state:=after_state||jsonb_build_object('native_id',native_value); END IF;
        END IF;
    END IF;
    IF outcome='succeeded' THEN
        INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES('configuration',p_correlation) RETURNING id INTO revision;
        PERFORM analytics.rebuild_core_projections(revision);
        INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,aggregate_id,affected_tags,payload)
            VALUES(revision,p_action,target_type,target::text,ARRAY['catalog','institution:'||coalesce(account.institution_id,target)::text],
                jsonb_build_object('action',p_action,'rowVersion',after_state->'row_version'));
    END IF;
    INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,before_state,after_state,outcome)
        VALUES(p_actor,p_action,target_type,target,p_correlation,before_state,after_state,outcome);
    SELECT legacy_id INTO alias_id FROM catalog.legacy_entity_alias WHERE target_uuid=target
        AND entity_type=CASE WHEN target_type='institution' THEN 'institutions' ELSE 'platform_accounts' END;
    result:=jsonb_build_object('outcome',outcome,'targetId',target,'legacyId',alias_id,
        'datasetRevision',revision,'state',after_state,'correlationId',p_correlation);
    INSERT INTO ops_and_admin.catalog_command_receipt(actor,correlation_id,request_digest,response)
        VALUES(p_actor,p_correlation,request_digest,result);
    RETURN result;
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid) TO api_write_admin;
RESET ROLE;
