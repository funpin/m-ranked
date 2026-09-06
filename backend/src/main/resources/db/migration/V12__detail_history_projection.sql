-- Same-observation public history is a derived projection. Runtime readers cannot
-- access ingestion history or migration/raw payload tables.
SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';
CREATE TABLE analytics.publication_history (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    snapshot_id bigint NOT NULL,
    published_month date NOT NULL,
    observed_at timestamptz NOT NULL,
    age_seconds integer NOT NULL,
    views_count bigint, reactions_count bigint, comments_count bigint, shares_count bigint,
    views_quality ingest.observation_quality, reactions_quality ingest.observation_quality,
    comments_quality ingest.observation_quality, shares_quality ingest.observation_quality,
    delta_views bigint, delta_reactions bigint, delta_comments bigint, delta_shares bigint,
    reaction_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
    synthetic boolean NOT NULL, interval_uncertain boolean NOT NULL,
    quality ingest.observation_quality NOT NULL,
    lineage jsonb NOT NULL,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    PRIMARY KEY(publication_id,published_month,snapshot_id),
    CHECK(jsonb_typeof(reaction_breakdown)='object'), CHECK(jsonb_typeof(lineage)='object')
);
CREATE INDEX publication_history_page_idx ON analytics.publication_history
    (dataset_revision_id,publication_id,observed_at DESC,snapshot_id DESC);
GRANT SELECT ON analytics.publication_history TO api_read,api_write_admin;
ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v11;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v11(bigint) FROM PUBLIC,api_read,api_write_admin,
    collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ingest,catalog AS $function$
DECLARE result jsonb; rows_written bigint;
BEGIN
    result:=analytics.rebuild_core_projections_v11(p_dataset_revision_id);
    DELETE FROM analytics.publication_history;
    INSERT INTO analytics.publication_history(publication_id,snapshot_id,published_month,observed_at,age_seconds,
        views_count,reactions_count,comments_count,shares_count,views_quality,reactions_quality,comments_quality,shares_quality,
        delta_views,delta_reactions,delta_comments,delta_shares,reaction_breakdown,synthetic,interval_uncertain,
        quality,lineage,dataset_revision_id)
    SELECT snapshot.publication_id,snapshot.id,snapshot.published_month,snapshot.observed_at,snapshot.age_seconds,
        snapshot.views_count,snapshot.reactions_count,snapshot.comments_count,snapshot.shares_count,
        snapshot.views_quality,snapshot.reactions_quality,snapshot.comments_quality,snapshot.shares_quality,
        snapshot.views_count-lag(snapshot.views_count) OVER chronology,
        snapshot.reactions_count-lag(snapshot.reactions_count) OVER chronology,
        snapshot.comments_count-lag(snapshot.comments_count) OVER chronology,
        snapshot.shares_count-lag(snapshot.shares_count) OVER chronology,
        coalesce((SELECT jsonb_object_agg(reaction.reaction_key,reaction.reaction_count)
            FROM ingest.reaction_breakdown reaction
            WHERE reaction.snapshot_published_month=snapshot.published_month AND reaction.snapshot_id=snapshot.id),'{}'::jsonb),
        snapshot.synthetic,snapshot.interval_uncertain,snapshot.quality,
        jsonb_build_object('sourceFingerprint',snapshot.source_fingerprint,
            'supersedesSnapshotId',snapshot.supersedes_snapshot_id::text,
            'correctionSequence',snapshot.correction_sequence,'correctionReason',snapshot.correction_reason),
        p_dataset_revision_id
    FROM analytics.usable_publication_snapshot snapshot
    JOIN analytics.dataset_revision revision ON revision.id=p_dataset_revision_id
    WHERE snapshot.observed_at<=revision.committed_at AND snapshot.collected_at<=revision.committed_at
    WINDOW chronology AS(PARTITION BY snapshot.publication_id ORDER BY snapshot.observed_at,snapshot.published_month,snapshot.id);
    GET DIAGNOSTICS rows_written=ROW_COUNT;
    INSERT INTO analytics.projection_state(projection_name,dataset_revision_id,status,refreshed_at,row_count)
        VALUES('publication_history',p_dataset_revision_id,'ready',transaction_timestamp(),rows_written)
    ON CONFLICT(projection_name) DO UPDATE SET dataset_revision_id=excluded.dataset_revision_id,
        status=excluded.status,refreshed_at=excluded.refreshed_at,row_count=excluded.row_count,error_code=NULL;
    RETURN result||jsonb_build_object('publication_history',rows_written);
END
$function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO api_write_admin,collector_ingest,migration_bridge,maintenance;
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.rebuild_core_projections(revision); END IF;
END
$backfill$;
RESET ROLE;
