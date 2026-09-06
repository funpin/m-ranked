-- Preserve presentation order and stored Telegram deltas without exposing raw
-- migration evidence. Native deltas use the entire published history, so page
-- boundaries never change their values. Existing observation authority is unchanged.
SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

ALTER TABLE analytics.publication_history
    ADD COLUMN reaction_entries jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN delta_reaction_breakdown jsonb,
    ADD COLUMN delta_reaction_entries jsonb,
    ADD CONSTRAINT history_reaction_entries_array CHECK(jsonb_typeof(reaction_entries)='array'),
    ADD CONSTRAINT history_delta_reaction_object CHECK(delta_reaction_breakdown IS NULL OR jsonb_typeof(delta_reaction_breakdown)='object'),
    ADD CONSTRAINT history_delta_reaction_entries_array CHECK(delta_reaction_entries IS NULL OR jsonb_typeof(delta_reaction_entries)='array');

CREATE FUNCTION analytics.ordered_history_reactions(p_text text,p_signed boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $function$
DECLARE document json;entry record;result jsonb;
BEGIN
    IF p_text IS NULL OR octet_length(p_text)>1048576 THEN RETURN NULL; END IF;
    document:=p_text::json;
    IF json_typeof(document)<>'object' THEN RETURN NULL; END IF;
    IF (SELECT count(*) FROM json_each(document))>1024 THEN RETURN NULL; END IF;
    FOR entry IN SELECT key,value FROM json_each(document) LOOP
        -- Only reaction labels and integer counts cross the public boundary. The
        -- retained payload itself, arbitrary fields, URLs and secrets stay private.
        IF entry.key='' OR length(entry.key)>200 OR entry.key~'[[:cntrl:]]'
            OR entry.key~*'(password|secret|token|session|cookie|authorization|://)'
            OR json_typeof(entry.value)<>'number' OR entry.value::text!~'^-?[0-9]+$'
            OR (entry.value::text)::numeric NOT BETWEEN '-9223372036854775808'::numeric AND '9223372036854775807'::numeric
            OR (NOT p_signed AND (entry.value::text)::bigint<0) THEN RETURN NULL; END IF;
    END LOOP;
    -- Python json.loads keeps the first key position and the last duplicate value.
    WITH entries AS (
        SELECT key,value,ordinality,min(ordinality) OVER(PARTITION BY key) AS first_position
        FROM json_each(document) WITH ORDINALITY
    ), last_value AS (
        SELECT DISTINCT ON(key) key,value,first_position FROM entries ORDER BY key,ordinality DESC
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('reaction',key,'count',(value::text)::bigint)
        ORDER BY first_position),'[]'::jsonb) INTO result FROM last_value;
    RETURN result;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN NULL;
END $function$;
REVOKE ALL ON FUNCTION analytics.ordered_history_reactions(text,boolean) FROM PUBLIC;

CREATE FUNCTION analytics.refresh_history_reaction_details(p_revision bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics,migration AS $function$
DECLARE written bigint;
BEGIN
    WITH history AS MATERIALIZED (
        SELECT h.*,lag(h.reaction_breakdown) OVER chronology AS prior_reactions,
            lag(h.reactions_count) OVER chronology AS prior_reactions_count
        FROM analytics.publication_history h WHERE dataset_revision_id=p_revision
        WINDOW chronology AS(PARTITION BY publication_id ORDER BY observed_at,published_month,snapshot_id)
    ), sources AS MATERIALIZED (
        SELECT h.publication_id,h.published_month,h.snapshot_id,mapping.source_namespace,
            lexeme.fields->>'reactions_json' AS current_json,
            CASE WHEN evidence.evidence ? 'delta_by_reaction_json' THEN
                CASE WHEN jsonb_typeof(evidence.evidence->'delta_by_reaction_json')='null' THEN '{}'
                     WHEN jsonb_typeof(evidence.evidence->'delta_by_reaction_json')='string'
                     THEN coalesce(nullif(evidence.evidence->>'delta_by_reaction_json',''),'{}') END END AS delta_json
        FROM history h
        LEFT JOIN LATERAL (
            SELECT identity.* FROM migration.legacy_identity_map identity
            WHERE identity.target_type='publication_metric_snapshot' AND identity.target_bigint=h.snapshot_id
                AND identity.source_table='reaction_snapshots'
                AND identity.natural_key->>'publication_id'=h.publication_id::text
                AND identity.natural_key->>'published_month'=h.published_month::text
            ORDER BY identity.last_seen_batch_id,identity.source_namespace LIMIT 1
        ) mapping ON true
        LEFT JOIN migration.legacy_export_lexeme lexeme
            ON lexeme.source_namespace=mapping.source_namespace AND lexeme.source_table=mapping.source_table
            AND lexeme.source_pk=mapping.source_pk AND lexeme.source_row_hash=mapping.source_row_hash
            AND lexeme.blocked_reason IS NULL
        LEFT JOIN migration.legacy_evidence evidence
            ON evidence.batch_id=mapping.last_seen_batch_id AND evidence.source_table=mapping.source_table
            AND evidence.source_pk=mapping.source_pk AND evidence.source_row_hash=mapping.source_row_hash
            AND evidence.evidence_kind='legacy_derived_metrics' AND evidence.sanitized
    ), parsed AS MATERIALIZED (
        SELECT h.*,sources.source_namespace,
            analytics.ordered_history_reactions(sources.current_json,false) AS retained_current,
            analytics.ordered_history_reactions(sources.delta_json,true) AS retained_delta
        FROM history h JOIN sources USING(publication_id,published_month,snapshot_id)
    ), entries AS (
        SELECT parsed.*,
            CASE WHEN retained_current IS NOT NULL AND
                (SELECT coalesce(jsonb_object_agg(value->>'reaction',value->'count'),'{}'::jsonb)
                 FROM jsonb_array_elements(retained_current))=reaction_breakdown
            THEN retained_current ELSE coalesce(analytics.ordered_history_reactions(reaction_breakdown::text,false),'[]'::jsonb) END AS current_entries,
            CASE WHEN source_namespace IS NOT NULL THEN retained_delta
                WHEN reactions_count IS NULL OR prior_reactions_count IS NULL THEN NULL
                ELSE (SELECT coalesce(jsonb_agg(jsonb_build_object('reaction',key,'count',difference) ORDER BY key COLLATE "C"),'[]'::jsonb)
                    FROM (SELECT key,coalesce((reaction_breakdown->>key)::bigint,0)-coalesce((prior_reactions->>key)::bigint,0) AS difference
                        FROM (SELECT jsonb_object_keys(reaction_breakdown) AS key UNION SELECT jsonb_object_keys(prior_reactions)) keys) deltas
                    WHERE difference<>0) END AS delta_entries
        FROM parsed
    )
    UPDATE analytics.publication_history target SET reaction_entries=entries.current_entries,
        delta_reaction_entries=entries.delta_entries,
        delta_reaction_breakdown=CASE WHEN entries.delta_entries IS NULL THEN NULL ELSE
            (SELECT coalesce(jsonb_object_agg(value->>'reaction',value->'count'),'{}'::jsonb)
                FROM jsonb_array_elements(entries.delta_entries)) END,
        lineage=target.lineage||jsonb_build_object('reactionDetailsSource',
            CASE WHEN entries.source_namespace IS NULL THEN 'canonical'
                WHEN entries.retained_delta IS NULL THEN 'legacy_unavailable' ELSE 'legacy' END)
    FROM entries WHERE target.publication_id=entries.publication_id AND target.published_month=entries.published_month
        AND target.snapshot_id=entries.snapshot_id AND target.dataset_revision_id=p_revision;
    GET DIAGNOSTICS written=ROW_COUNT;RETURN written;
END $function$;
REVOKE ALL ON FUNCTION analytics.refresh_history_reaction_details(bigint) FROM PUBLIC;

ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v23;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v23(bigint)
    FROM PUBLIC,api_read,api_write_admin,collector_ingest,migration_bridge,maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,analytics AS $function$
DECLARE result jsonb;
BEGIN
    result:=analytics.rebuild_core_projections_v23(p_dataset_revision_id);
    RETURN result||jsonb_build_object('publication_history_reactions',analytics.refresh_history_reaction_details(p_dataset_revision_id));
END $function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint) TO api_write_admin,collector_ingest,migration_bridge,maintenance;
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT dataset_revision_id INTO revision FROM analytics.projection_state WHERE projection_name='publication_history' AND status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.refresh_history_reaction_details(revision); END IF;
END $backfill$;
RESET ROLE;
