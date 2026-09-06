-- Only the already-public text keys are exposed; all other migration evidence
-- remains inaccessible to api_read. Published revisions include this content atomically.
SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='5min';
CREATE TABLE analytics.publication_content (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id) ON DELETE CASCADE,
    archived_text text,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id)
);
CREATE INDEX publication_content_revision_idx ON analytics.publication_content(dataset_revision_id,publication_id);
GRANT SELECT ON analytics.publication_content TO api_read,api_write_admin;
CREATE FUNCTION analytics.refresh_publication_content(p_revision bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,migration,ingest AS $function$
DECLARE rows_written bigint;
BEGIN
    DELETE FROM analytics.publication_content;
    INSERT INTO analytics.publication_content(publication_id,archived_text,dataset_revision_id)
    SELECT publication.id,content.public_text,p_revision
    FROM ingest.publication publication
    JOIN analytics.dataset_revision revision ON revision.id=p_revision
    LEFT JOIN LATERAL (
        SELECT regexp_replace(candidate.value #>> '{}','^[[:space:]]+|[[:space:]]+$','','g') AS public_text
        FROM migration.legacy_identity_map identity
        JOIN migration.legacy_evidence evidence
          ON evidence.batch_id=identity.last_seen_batch_id AND evidence.source_table=identity.source_table
         AND evidence.source_pk=identity.source_pk AND evidence.source_row_hash=identity.source_row_hash
         AND evidence.evidence_kind='raw_json'
        CROSS JOIN LATERAL(VALUES(1,evidence.evidence->'payload'->'text'),
            (2,evidence.evidence->'payload'->'message'),(3,evidence.evidence->'payload'->'caption')) candidate(priority,value)
        WHERE identity.target_uuid=publication.id AND identity.target_type='publication'
          AND identity.source_table='platform_posts' AND jsonb_typeof(candidate.value)='string'
          AND regexp_replace(candidate.value #>> '{}','^[[:space:]]+|[[:space:]]+$','','g')<>''
        ORDER BY evidence.id DESC,candidate.priority LIMIT 1
    ) content ON true
    WHERE publication.published_at<=revision.committed_at;
    GET DIAGNOSTICS rows_written=ROW_COUNT;
    INSERT INTO analytics.projection_state(projection_name,dataset_revision_id,status,refreshed_at,row_count)
      VALUES('publication_content',p_revision,'ready',transaction_timestamp(),rows_written)
    ON CONFLICT(projection_name) DO UPDATE SET dataset_revision_id=excluded.dataset_revision_id,
      status=excluded.status,refreshed_at=excluded.refreshed_at,row_count=excluded.row_count,error_code=NULL;
    RETURN rows_written;
END $function$;
REVOKE ALL ON FUNCTION analytics.refresh_publication_content(bigint) FROM PUBLIC;
ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v13;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v13(bigint)
    FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
DECLARE result jsonb;
BEGIN
    result:=analytics.rebuild_core_projections_v13(p_dataset_revision_id);
    RETURN result||jsonb_build_object('publication_content',analytics.refresh_publication_content(p_dataset_revision_id));
END $function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO api_write_admin,collector_ingest,migration_bridge,maintenance;
-- Install only the new projection; no unnecessary rebuild of the unchanged metric tables.
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.refresh_publication_content(revision); END IF;
END $backfill$;
RESET ROLE;
