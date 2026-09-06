SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

-- Eleven typed export columns, not a replacement observation authority. No raw
-- payload, reaction JSON or credential-bearing evidence is duplicated here.
CREATE TABLE analytics.legacy_csv_snapshot_fact (
    published_month date NOT NULL,id bigint NOT NULL,publication_id uuid NOT NULL,
    observed_at timestamptz NOT NULL,age_seconds integer NOT NULL CHECK(age_seconds>=0),
    sampling_bucket bigint NOT NULL,views_count bigint,reactions_count bigint,comments_count bigint,shares_count bigint,
    correction_sequence bigint NOT NULL CHECK(correction_sequence>=0),
    PRIMARY KEY(published_month,id),
    UNIQUE(published_month,publication_id,sampling_bucket,correction_sequence)
);
CREATE INDEX legacy_csv_fact_tip_idx ON analytics.legacy_csv_snapshot_fact
    (published_month,publication_id,sampling_bucket,correction_sequence DESC,id DESC);
CREATE INDEX legacy_csv_fact_publication_idx ON analytics.legacy_csv_snapshot_fact(publication_id,observed_at DESC,id DESC);
CREATE TRIGGER legacy_csv_fact_immutable BEFORE UPDATE OR DELETE ON analytics.legacy_csv_snapshot_fact
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER legacy_csv_fact_no_truncate BEFORE TRUNCATE ON analytics.legacy_csv_snapshot_fact
    FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();
REVOKE ALL ON analytics.legacy_csv_snapshot_fact FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;

CREATE VIEW analytics.legacy_csv_snapshot_fact_active AS
    SELECT DISTINCT ON(published_month,publication_id,sampling_bucket) *
    FROM analytics.legacy_csv_snapshot_fact
    ORDER BY published_month,publication_id,sampling_bucket,correction_sequence DESC,id DESC;
REVOKE ALL ON analytics.legacy_csv_snapshot_fact_active FROM PUBLIC;

CREATE TABLE analytics.legacy_csv_archive_coverage (
    manifest_id uuid PRIMARY KEY REFERENCES ops_and_admin.archive_manifest(id),
    published_month date NOT NULL,row_count bigint NOT NULL,fact_digest text NOT NULL,
    canonical_sha256 text NOT NULL,created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE TRIGGER legacy_csv_coverage_immutable BEFORE UPDATE OR DELETE ON analytics.legacy_csv_archive_coverage
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER legacy_csv_coverage_no_truncate BEFORE TRUNCATE ON analytics.legacy_csv_archive_coverage
    FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();
GRANT SELECT ON analytics.legacy_csv_archive_coverage TO maintenance;

CREATE FUNCTION analytics.capture_legacy_csv_facts(p_month date DEFAULT NULL) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,ingest AS $function$
DECLARE written bigint;
BEGIN
    INSERT INTO analytics.legacy_csv_snapshot_fact
    SELECT published_month,id,publication_id,observed_at,age_seconds,sampling_bucket,
        views_count,reactions_count,comments_count,shares_count,correction_sequence
    FROM ingest.publication_metric_snapshot WHERE p_month IS NULL OR published_month=p_month
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS written=ROW_COUNT;RETURN written;
END $function$;
REVOKE ALL ON FUNCTION analytics.capture_legacy_csv_facts(date) FROM PUBLIC;

CREATE FUNCTION analytics.legacy_csv_fact_digest(p_month date,p_hot boolean DEFAULT false)
RETURNS TABLE(row_count bigint,fact_digest text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,analytics,ingest SET TimeZone='UTC' AS $function$
DECLARE fact analytics.legacy_csv_snapshot_fact;chain bytea:=sha256(''::bytea);
BEGIN
    row_count:=0;
    FOR fact IN
        SELECT * FROM analytics.legacy_csv_snapshot_fact WHERE published_month=p_month AND NOT p_hot
        UNION ALL
        SELECT published_month,id,publication_id,observed_at,age_seconds,sampling_bucket,
            views_count,reactions_count,comments_count,shares_count,correction_sequence
        FROM ingest.publication_metric_snapshot WHERE published_month=p_month AND p_hot
        ORDER BY id
    LOOP
        chain:=sha256(chain||sha256(convert_to(to_jsonb(fact)::text,'UTF8')));row_count:=row_count+1;
    END LOOP;
    fact_digest:=encode(chain,'hex');RETURN NEXT;
END $function$;
REVOKE ALL ON FUNCTION analytics.legacy_csv_fact_digest(date,boolean) FROM PUBLIC;

-- Keep the existing archive fence, object attestation and full raw digest gate.
-- Coverage and DROP commit together under exactly the same exclusive locks.
ALTER FUNCTION ops_and_admin.drop_publication_metric_partition(date,uuid) RENAME TO drop_publication_metric_partition_v21;
REVOKE ALL ON FUNCTION ops_and_admin.drop_publication_metric_partition_v21(date,uuid) FROM PUBLIC,maintenance;
CREATE FUNCTION ops_and_admin.drop_publication_metric_partition(p_month date,p_manifest_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,ingest,ops_and_admin
SET lock_timeout='10s' SET TimeZone='UTC' AS $function$
DECLARE hot record;facts record;manifest ops_and_admin.archive_manifest;
BEGIN
    IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
    LOCK TABLE ingest.publication_metric_snapshot,ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
    LOCK TABLE ingest.publication,catalog.platform_account IN SHARE MODE;
    PERFORM analytics.capture_legacy_csv_facts(p_month);
    SELECT * INTO hot FROM analytics.legacy_csv_fact_digest(p_month,true);
    SELECT * INTO facts FROM analytics.legacy_csv_fact_digest(p_month,false);
    IF ROW(hot.row_count,hot.fact_digest) IS DISTINCT FROM ROW(facts.row_count,facts.fact_digest) THEN
        RAISE EXCEPTION 'legacy CSV fact coverage mismatch' USING ERRCODE='23514';
    END IF;
    SELECT * INTO STRICT manifest FROM ops_and_admin.archive_manifest WHERE id=p_manifest_id;
    INSERT INTO analytics.legacy_csv_archive_coverage(manifest_id,published_month,row_count,fact_digest,canonical_sha256)
        VALUES(p_manifest_id,p_month,facts.row_count,facts.fact_digest,manifest.canonical_sha256) ON CONFLICT DO NOTHING;
    PERFORM ops_and_admin.drop_publication_metric_partition_v21(p_month,p_manifest_id);
END $function$;
REVOKE ALL ON FUNCTION ops_and_admin.drop_publication_metric_partition(date,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.drop_publication_metric_partition(date,uuid) TO maintenance;

-- Restore only derived export facts for a pre-V22 cold object. A restore is one
-- transaction: incomplete or invalid canonical chains cannot leave facts behind.
CREATE FUNCTION analytics.begin_legacy_csv_restore() RETURNS timestamptz
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
DECLARE anchor timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.rebuild_core_projections',0));
    LOCK TABLE analytics.dataset_revision IN SHARE MODE;
    SELECT committed_at INTO anchor FROM analytics.dataset_revision
        WHERE id=(SELECT max(dataset_revision_id) FROM analytics.projection_state WHERE status='ready');
    IF anchor IS NULL THEN RAISE EXCEPTION 'published revision required for archive restore'; END IF;
    RETURN anchor;
END $function$;
REVOKE ALL ON FUNCTION analytics.begin_legacy_csv_restore() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.begin_legacy_csv_restore() TO maintenance;
CREATE TABLE analytics.legacy_csv_restore_state (
    manifest_id uuid PRIMARY KEY,transaction_id xid8 NOT NULL,chain bytea NOT NULL,fact_chain bytea NOT NULL,
    row_count bigint NOT NULL,last_id bigint
);
REVOKE ALL ON analytics.legacy_csv_restore_state FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.require_completed_legacy_csv_restore() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
BEGIN
    IF EXISTS(SELECT 1 FROM analytics.legacy_csv_restore_state WHERE manifest_id=NEW.manifest_id) THEN
        RAISE EXCEPTION 'incomplete archive restore cannot commit' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $function$;
REVOKE ALL ON FUNCTION analytics.require_completed_legacy_csv_restore() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER legacy_csv_restore_must_finish AFTER INSERT OR UPDATE ON analytics.legacy_csv_restore_state
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION analytics.require_completed_legacy_csv_restore();
CREATE FUNCTION analytics.restore_legacy_csv_archive(p_manifest uuid,p_records text[],p_finish boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,ops_and_admin
SET TimeZone='UTC' AS $function$
DECLARE state analytics.legacy_csv_restore_state;manifest ops_and_admin.archive_manifest;body text;data jsonb;
    fact analytics.legacy_csv_snapshot_fact;existing analytics.legacy_csv_snapshot_fact;actual record;
BEGIN
    SELECT * INTO STRICT manifest FROM ops_and_admin.archive_manifest WHERE id=p_manifest;
    IF manifest.dataset_type<>'publication_metric_snapshot' OR manifest.schema_version<>3 OR manifest.hot_dropped_at IS NULL
        OR manifest.canonical_sha256 IS NULL THEN RAISE EXCEPTION 'verified cold v3 manifest required'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||manifest.partition_start::date::text,0));
    INSERT INTO analytics.legacy_csv_restore_state VALUES(p_manifest,pg_current_xact_id(),sha256(''::bytea),sha256(''::bytea),0,NULL)
        ON CONFLICT DO NOTHING;
    SELECT * INTO STRICT state FROM analytics.legacy_csv_restore_state WHERE manifest_id=p_manifest FOR UPDATE;
    IF state.transaction_id<>pg_current_xact_id() THEN RAISE EXCEPTION 'archive restore must use one transaction'; END IF;
    IF cardinality(p_records)>1000 THEN RAISE EXCEPTION 'archive restore batch exceeds 1000 rows'; END IF;
    FOREACH body IN ARRAY p_records LOOP
        data:=body::jsonb;
        fact:=ROW((data->>'published_month')::date,(data->>'id')::bigint,(data->>'publication_id')::uuid,
            (data->>'observed_at')::timestamptz,(data->>'age_seconds')::integer,(data->>'sampling_bucket')::bigint,
            (data->>'views_count')::bigint,(data->>'reactions_count')::bigint,(data->>'comments_count')::bigint,
            (data->>'shares_count')::bigint,(data->>'correction_sequence')::bigint);
        IF fact.published_month IS DISTINCT FROM manifest.partition_start::date
            OR (state.last_id IS NOT NULL AND fact.id<=state.last_id) THEN RAISE EXCEPTION 'archive month/order mismatch'; END IF;
        INSERT INTO analytics.legacy_csv_snapshot_fact SELECT fact.* ON CONFLICT DO NOTHING;
        SELECT * INTO STRICT existing FROM analytics.legacy_csv_snapshot_fact WHERE published_month=fact.published_month AND id=fact.id;
        IF existing IS DISTINCT FROM fact THEN RAISE EXCEPTION 'archive fact conflict' USING ERRCODE='23514'; END IF;
        state.chain:=sha256(state.chain||sha256(convert_to(body,'UTF8')));
        state.fact_chain:=sha256(state.fact_chain||sha256(convert_to(to_jsonb(fact)::text,'UTF8')));
        state.row_count:=state.row_count+1;state.last_id:=fact.id;
        IF state.row_count>manifest.row_count THEN RAISE EXCEPTION 'archive row limit exceeded'; END IF;
    END LOOP;
    UPDATE analytics.legacy_csv_restore_state SET chain=state.chain,fact_chain=state.fact_chain,row_count=state.row_count,last_id=state.last_id
        WHERE manifest_id=p_manifest;
    IF p_finish THEN
        SELECT * INTO actual FROM analytics.legacy_csv_fact_digest(manifest.partition_start::date,false);
        IF state.row_count<>manifest.row_count OR encode(state.chain,'hex')<>manifest.canonical_sha256
            OR actual.row_count<>state.row_count OR actual.fact_digest<>encode(state.fact_chain,'hex') THEN
            RAISE EXCEPTION 'archive canonical/CSV coverage mismatch' USING ERRCODE='23514';
        END IF;
        INSERT INTO analytics.legacy_csv_archive_coverage(manifest_id,published_month,row_count,fact_digest,canonical_sha256)
            VALUES(p_manifest,manifest.partition_start::date,actual.row_count,actual.fact_digest,manifest.canonical_sha256) ON CONFLICT DO NOTHING;
        IF NOT EXISTS(SELECT 1 FROM analytics.legacy_csv_archive_coverage WHERE manifest_id=p_manifest
            AND row_count=actual.row_count AND fact_digest=actual.fact_digest AND canonical_sha256=manifest.canonical_sha256) THEN
            RAISE EXCEPTION 'existing archive coverage conflict' USING ERRCODE='23514';
        END IF;
        DELETE FROM analytics.legacy_csv_restore_state WHERE manifest_id=p_manifest;
    END IF;
    RETURN state.row_count;
END $function$;
REVOKE ALL ON FUNCTION analytics.restore_legacy_csv_archive(uuid,text[],boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.restore_legacy_csv_archive(uuid,text[],boolean) TO maintenance;

DO $migration$
DECLARE definition text;old text;
BEGIN
    definition:=pg_get_functiondef('analytics.refresh_legacy_exports(bigint)'::regprocedure);
    old:='    -- Per-run temporary relations';
    IF position(old IN definition)=0 THEN RAISE EXCEPTION 'CSV capture anchor missing'; END IF;
    definition:=replace(definition,old,'    PERFORM analytics.capture_legacy_csv_facts(NULL);
'||old);
    old:='ingest.publication_metric_snapshot_active';
    IF position(old IN definition)=0 THEN RAISE EXCEPTION 'CSV active snapshot anchor missing'; END IF;
    definition:=replace(definition,old,'analytics.legacy_csv_snapshot_fact_active');
    old:='WHERE dataset_type=''publication_metric_snapshot'' AND row_count>0 AND hot_dropped_at IS NOT NULL';
    IF position(old IN definition)=0 THEN RAISE EXCEPTION 'CSV cold coverage anchor missing'; END IF;
    definition:=replace(definition,old,'WHERE dataset_type=''publication_metric_snapshot'' AND row_count>0 AND hot_dropped_at IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM analytics.legacy_csv_archive_coverage coverage
            CROSS JOIN LATERAL analytics.legacy_csv_fact_digest(coverage.published_month,false) actual
            WHERE coverage.manifest_id=archive_manifest.id AND coverage.row_count=archive_manifest.row_count
                AND coverage.canonical_sha256=archive_manifest.canonical_sha256
                AND actual.row_count=coverage.row_count AND actual.fact_digest=coverage.fact_digest)');
    EXECUTE definition;
END $migration$;
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    PERFORM analytics.capture_legacy_csv_facts(NULL);
    IF revision IS NOT NULL THEN PERFORM analytics.refresh_legacy_exports(revision); END IF;
END $backfill$;
RESET ROLE;
