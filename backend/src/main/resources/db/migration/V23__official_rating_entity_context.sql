SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

-- V1 stored both institution and channel imports in one observation table.
-- The lineage map identifies the source entity; ranking values still come
-- exclusively from the immutable observation. Native institutional imports
-- have no channel lineage and remain included.
CREATE VIEW rating.official_institution_rating_observation AS
SELECT observation.* FROM rating.official_rating_observation observation
WHERE NOT EXISTS(SELECT 1 FROM migration.legacy_identity_map mapping
    WHERE mapping.target_uuid=observation.id AND mapping.source_table='channels'
      AND mapping.target_type='official_rating_observation:telegram');
GRANT SELECT ON rating.official_institution_rating_observation TO api_read,api_write_admin,maintenance;

DO $context$
DECLARE definition text;function record;changed integer:=0;needle text:='rating.official_rating_observation';
BEGIN
    FOR function IN SELECT procedure.oid FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
        WHERE namespace.nspname='analytics' AND procedure.proname LIKE 'rebuild_core_projections%'
    LOOP
        definition:=pg_get_functiondef(function.oid);
        IF position(needle IN definition)>0 THEN
            EXECUTE replace(definition,needle,'rating.official_institution_rating_observation');changed:=changed+1;
        END IF;
    END LOOP;
    IF changed<>1 THEN RAISE EXCEPTION 'institutional rating projection inventory changed'; END IF;
    definition:=pg_get_functiondef('analytics.refresh_official_account_ratings(bigint)'::regprocedure);
    IF position('    WITH latest AS (' IN definition)=0 THEN RAISE EXCEPTION 'channel rating projection anchor changed'; END IF;
    -- An unrated channel does not inherit its parent's institution rank.
    definition:=replace(definition,'    WITH latest AS (',E'    UPDATE analytics.legacy_overview_card SET rating_rank=NULL,rating_score=NULL,rating_period=NULL,rating_fetched_at=NULL\n        WHERE platform=''telegram'' AND dataset_revision_id=p_revision;\n    WITH latest AS (');
    EXECUTE definition;
END $context$;

DO $backfill$
DECLARE anchor timestamptz;revision bigint;
BEGIN
    SELECT source.committed_at INTO anchor FROM analytics.dataset_revision source
    WHERE source.id=(SELECT max(dataset_revision_id) FROM analytics.projection_state WHERE status='ready');
    IF anchor IS NOT NULL THEN
        INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at,metadata)
            VALUES('configuration',gen_random_uuid(),anchor,'{"migration":"V23","projection":"official-entity-context"}') RETURNING id INTO revision;
        PERFORM analytics.rebuild_core_projections(revision);
    END IF;
END $backfill$;
RESET ROLE;
