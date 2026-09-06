SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

-- app/platform_analytics.py gates a platform publication-time baseline by the
-- first observation INSIDE the selected window. The legacy default is six
-- minutes (app/config.py), independently of publication.history_complete.
-- Policy changes are append-only and activate at a new configuration revision;
-- rebuilding an earlier revision continues to use its original policy.
CREATE TABLE analytics.legacy_period_policy (
    effective_from_revision bigint PRIMARY KEY CHECK(effective_from_revision>=0),
    first_age_limit_seconds integer NOT NULL CHECK(first_age_limit_seconds BETWEEN 0 AND 86400),
    reason text NOT NULL CHECK(btrim(reason)<>''),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
INSERT INTO analytics.legacy_period_policy(effective_from_revision,first_age_limit_seconds,reason)
    VALUES(0,360,'Legacy COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES default 6');
CREATE FUNCTION analytics.guard_legacy_period_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,analytics AS $function$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.rebuild_core_projections',0));
    IF NEW.effective_from_revision<=coalesce((SELECT max(dataset_revision_id) FROM analytics.projection_state),0)
       OR NEW.effective_from_revision<=coalesce((SELECT max(effective_from_revision) FROM analytics.legacy_period_policy),0)
       OR NOT EXISTS(SELECT 1 FROM analytics.dataset_revision WHERE id=NEW.effective_from_revision AND cause='configuration') THEN
        RAISE EXCEPTION 'period policy requires a new unpublished configuration revision' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $function$;
REVOKE ALL ON FUNCTION analytics.guard_legacy_period_policy() FROM PUBLIC;
CREATE TRIGGER legacy_period_policy_revision_guard BEFORE INSERT ON analytics.legacy_period_policy
    FOR EACH ROW EXECUTE FUNCTION analytics.guard_legacy_period_policy();
CREATE TRIGGER legacy_period_policy_immutable BEFORE UPDATE OR DELETE ON analytics.legacy_period_policy
    FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER legacy_period_policy_no_truncate BEFORE TRUNCATE ON analytics.legacy_period_policy
    FOR EACH STATEMENT EXECUTE FUNCTION ingest.reject_observation_mutation();
REVOKE ALL ON analytics.legacy_period_policy FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge;
GRANT SELECT ON analytics.legacy_period_policy TO maintenance;

CREATE FUNCTION analytics.legacy_period_first_age_limit(p_revision bigint) RETURNS integer
LANGUAGE sql STABLE SET search_path=pg_catalog,analytics AS $function$
    SELECT first_age_limit_seconds FROM analytics.legacy_period_policy
    WHERE effective_from_revision<=p_revision ORDER BY effective_from_revision DESC LIMIT 1
$function$;
REVOKE ALL ON FUNCTION analytics.legacy_period_first_age_limit(bigint) FROM PUBLIC;

DO $migration$
DECLARE name text;definition text;old text;new text;expected integer;
BEGIN
    FOREACH name IN ARRAY ARRAY['rebuild_core_projections_v5','rebuild_core_projections_v9'] LOOP
        definition:=pg_get_functiondef(('analytics.'||name||'(bigint)')::regprocedure);
        old:='               max(observation.observation_count) AS observation_count,';
        new:='               max(observation.age_seconds) FILTER (WHERE observation.first_position=1) AS first_age_seconds,
'||old;
        IF position(old IN definition)=0 THEN RAISE EXCEPTION 'first-age bounds anchor missing: %',name; END IF;
        definition:=replace(definition,old,new);
        IF name='rebuild_core_projections_v5' THEN
            old:='               snapshot.id AS snapshot_id,';expected:=1;
        ELSE
            old:='               snapshot.views_count,';expected:=4;
        END IF;
        IF position(old IN definition)=0 THEN RAISE EXCEPTION 'first-age observation anchor missing: %',name; END IF;
        definition:=replace(definition,old,'               snapshot.age_seconds,
'||old);
        old:='bounds.history_completeness = ''complete''';
        IF (length(definition)-length(replace(definition,old,'')))/length(old)<>expected THEN
            RAISE EXCEPTION 'first-age baseline anchor count changed: %',name;
        END IF;
        definition:=replace(definition,old,'bounds.first_age_seconds <= analytics.legacy_period_first_age_limit(p_dataset_revision_id)');
        EXECUTE definition;
    END LOOP;
END $migration$;

COMMENT ON TABLE analytics.legacy_period_policy IS
'Owner-managed append-only configuration: add a new configuration dataset revision and policy row together, then rebuild that revision. Never retrofit a published revision.';

-- A formula correction gets a new revision/ETag while retaining the source
-- observation anchor. Empty installations stay empty until their first import.
DO $backfill$
DECLARE anchor timestamptz;revision bigint;
BEGIN
    SELECT source.committed_at INTO anchor FROM analytics.dataset_revision source
    WHERE source.id=(SELECT max(dataset_revision_id) FROM analytics.projection_state WHERE status='ready');
    IF anchor IS NOT NULL THEN
        INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at,metadata)
            VALUES('configuration',gen_random_uuid(),anchor,'{"migration":"V21","formula":"legacy-first-window-age"}')
            RETURNING id INTO revision;
        PERFORM analytics.rebuild_core_projections(revision);
    END IF;
END $backfill$;
RESET ROLE;
