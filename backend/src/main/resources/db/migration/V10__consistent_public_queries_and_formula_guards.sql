-- V1--V8 are published and immutable. All replacements live in this additive release.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

CREATE OR REPLACE FUNCTION rating.reject_published_component_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, rating AS $function$
DECLARE parent record;
BEGIN
    -- Ordered parent row locks also serialize component edits against publication.
    FOR parent IN SELECT id, status FROM rating.formula_definition
       WHERE id IN (CASE WHEN TG_OP <> 'INSERT' THEN OLD.formula_definition_id END,
                    CASE WHEN TG_OP <> 'DELETE' THEN NEW.formula_definition_id END)
       ORDER BY id FOR UPDATE
    LOOP
        IF parent.status IN ('published', 'retired') THEN
            RAISE EXCEPTION 'components of a published or retired formula are immutable'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$function$;

CREATE FUNCTION ops_and_admin.reject_audit_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $function$
BEGIN
    RAISE EXCEPTION 'admin audit is append-only' USING ERRCODE = '55000';
END
$function$;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON ops_and_admin.audit_log
FOR EACH ROW EXECUTE FUNCTION ops_and_admin.reject_audit_mutation();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON ops_and_admin.audit_log
FOR EACH STATEMENT EXECUTE FUNCTION ops_and_admin.reject_audit_mutation();
REVOKE UPDATE, DELETE, TRUNCATE ON ops_and_admin.audit_log FROM api_write_admin;

CREATE TABLE analytics.account_latest (
    platform_account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    metric_key analytics.metric_key NOT NULL CHECK (metric_key = 'subscribers'),
    value bigint CHECK (value IS NULL OR value >= 0),
    observed_at timestamptz NOT NULL,
    quality ingest.observation_quality NOT NULL,
    source_snapshot_id bigint NOT NULL,
    dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    PRIMARY KEY (platform_account_id, metric_key)
);
CREATE INDEX account_latest_revision_idx ON analytics.account_latest
    (dataset_revision_id, metric_key, platform_account_id) INCLUDE (value, observed_at, quality);
GRANT SELECT ON analytics.account_latest TO api_read, api_write_admin;
REVOKE SELECT ON ingest.account_metric_snapshot FROM api_read;
REVOKE SELECT (id, platform_account_id, observed_at, collected_at, subscriber_count, quality)
    ON ingest.account_metric_snapshot FROM api_read;

ALTER TABLE analytics.legacy_overview_card
ADD COLUMN aggregate_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
CHECK (jsonb_typeof(aggregate_metadata) = 'object');

-- Extend the existing candidate CTE, so metadata and values use the exact same rows.
DO $migration$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('analytics.rebuild_core_projections(bigint)'::regprocedure)
        INTO definition;
    IF position($old$sum(metric.delta_value) AS total_value,$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$sum(metric.delta_value) AS total_value,$old$, $new$max(metric.sample_size)::integer AS aggregate_sample_size,
               (SELECT count(*) FROM publication_delta eligible
                 WHERE eligible.period_key = metric.period_key
                   AND eligible.window_index = metric.window_index
                   AND eligible.platform = metric.platform
                   AND eligible.entity_id = metric.entity_id) AS aggregate_population,
               sum(metric.delta_value) AS total_value,$new$);
    IF position($old$    ), metric_pivot AS ($old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$    ), metric_pivot AS ($old$, $new$    ), metric_metadata AS (
        SELECT period_key, platform, entity_id,
               jsonb_object_agg(metric_key::text || ':' || window_index, jsonb_build_object(
                   'sampleSize', aggregate_sample_size,
                   'coverage', aggregate_sample_size::numeric / nullif(aggregate_population, 0),
                   'quality', 'unknown',
                   'asOf', revision_as_of,
                   'datasetRevision', p_dataset_revision_id
               )) AS metadata
          FROM metric_aggregate GROUP BY period_key, platform, entity_id
    ), metric_pivot AS ($new$);
    IF position($old$               revision_as_of AS as_of
          FROM dimensions AS dimension$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$               revision_as_of AS as_of
          FROM dimensions AS dimension$old$, $new$               coalesce(metadata.metadata, '{}'::jsonb) AS aggregate_metadata,
               revision_as_of AS as_of
          FROM dimensions AS dimension$new$);
    IF position($old$          LEFT JOIN metric_pivot AS metric$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$          LEFT JOIN metric_pivot AS metric$old$, $new$          LEFT JOIN metric_metadata AS metadata
            ON metadata.period_key = period.period_key
           AND metadata.platform = dimension.platform
           AND metadata.entity_id = dimension.entity_id
          LEFT JOIN metric_pivot AS metric$new$);
    IF position($old$        as_of, refreshed_at
    )$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$        as_of, refreshed_at
    )$old$, $new$        as_of, refreshed_at, aggregate_metadata
    )$new$);
    IF position($old$           transaction_timestamp()
      FROM card_source AS card;$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview metadata patch anchor missing'; END IF;
    definition := replace(definition, $old$           transaction_timestamp()
      FROM card_source AS card;$old$, $new$           transaction_timestamp(), card.aggregate_metadata
      FROM card_source AS card;$new$);
    IF position($old$snapshot.shares_count,
               row_number()$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$snapshot.shares_count,
               row_number()$old$, $new$snapshot.shares_count,
               snapshot.views_quality,
               snapshot.reactions_quality,
               snapshot.comments_quality,
               snapshot.shares_quality,
               row_number()$new$);
    IF position($old$               max(observation.observation_count) AS observation_count,$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$               max(observation.observation_count) AS observation_count,$old$, $new$               max(analytics.observation_quality_rank(observation.views_quality))
                   FILTER (WHERE (observation.first_position = 1 OR observation.latest_position = 1)
                           AND observation.views_count IS NOT NULL) AS views_quality_rank,
               max(analytics.observation_quality_rank(observation.reactions_quality))
                   FILTER (WHERE (observation.first_position = 1 OR observation.latest_position = 1)
                           AND observation.reactions_count IS NOT NULL) AS reactions_quality_rank,
               max(analytics.observation_quality_rank(observation.comments_quality))
                   FILTER (WHERE (observation.first_position = 1 OR observation.latest_position = 1)
                           AND observation.comments_count IS NOT NULL) AS comments_quality_rank,
               max(analytics.observation_quality_rank(observation.shares_quality))
                   FILTER (WHERE (observation.first_position = 1 OR observation.latest_position = 1)
                           AND observation.shares_count IS NOT NULL) AS shares_quality_rank,
               max(observation.observation_count) AS observation_count,$new$);
    IF position($old$               metric.delta_value
          FROM publication_delta$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$               metric.delta_value
          FROM publication_delta$old$, $new$               metric.delta_value, metric.quality_rank
          FROM publication_delta$new$);
    IF position($old$'views'::analytics.metric_key, delta.views_delta)$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$'views'::analytics.metric_key, delta.views_delta)$old$, $new$'views'::analytics.metric_key, delta.views_delta, delta.views_quality_rank)$new$);
    IF position($old$'reactions'::analytics.metric_key, delta.reactions_delta)$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$'reactions'::analytics.metric_key, delta.reactions_delta)$old$, $new$'reactions'::analytics.metric_key, delta.reactions_delta, delta.reactions_quality_rank)$new$);
    IF position($old$'comments'::analytics.metric_key, delta.comments_delta)$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$'comments'::analytics.metric_key, delta.comments_delta)$old$, $new$'comments'::analytics.metric_key, delta.comments_delta, delta.comments_quality_rank)$new$);
    IF position($old$'shares'::analytics.metric_key, delta.shares_delta)$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$'shares'::analytics.metric_key, delta.shares_delta)$old$, $new$'shares'::analytics.metric_key, delta.shares_delta, delta.shares_quality_rank)$new$);
    IF position($old$AS metric(metric_key, delta_value)$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$AS metric(metric_key, delta_value)$old$, $new$AS metric(metric_key, delta_value, quality_rank)$new$);
    IF position($old$max(metric.sample_size)::integer AS aggregate_sample_size,$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$max(metric.sample_size)::integer AS aggregate_sample_size,$old$, $new$max(metric.sample_size)::integer AS aggregate_sample_size,
               max(metric.quality_rank) AS aggregate_quality_rank,$new$);
    IF position($old$'quality', 'unknown',$old$ in definition) = 0 THEN RAISE EXCEPTION 'overview quality patch anchor missing'; END IF;
    definition := replace(definition, $old$'quality', 'unknown',$old$, $new$'quality', analytics.observation_quality_from_rank(aggregate_quality_rank),$new$);
    EXECUTE definition;
END
$migration$;

ALTER FUNCTION analytics.rebuild_core_projections(bigint) RENAME TO rebuild_core_projections_v9;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v9(bigint) FROM PUBLIC, api_read, api_write_admin, maintenance;
CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics, ingest, catalog AS $function$
DECLARE result jsonb; account_rows bigint;
BEGIN
    result := analytics.rebuild_core_projections_v9(p_dataset_revision_id);
    DELETE FROM analytics.account_latest;
    INSERT INTO analytics.account_latest
        (platform_account_id, metric_key, value, observed_at, quality, source_snapshot_id, dataset_revision_id)
    SELECT DISTINCT ON (snapshot.platform_account_id)
           snapshot.platform_account_id, 'subscribers'::analytics.metric_key,
           snapshot.subscriber_count, snapshot.observed_at, snapshot.subscriber_quality,
           snapshot.id, p_dataset_revision_id
      FROM ingest.account_metric_snapshot_active snapshot
      JOIN analytics.dataset_revision revision ON revision.id = p_dataset_revision_id
     WHERE snapshot.observed_at <= revision.committed_at
       AND snapshot.collected_at <= revision.committed_at
       AND snapshot.subscriber_quality NOT IN ('invalid', 'suspected_reset')
     ORDER BY snapshot.platform_account_id, snapshot.observed_at DESC,
              snapshot.correction_sequence DESC, snapshot.id DESC;
    GET DIAGNOSTICS account_rows = ROW_COUNT;
    RETURN result || jsonb_build_object('account_latest', account_rows);
END
$function$;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO api_write_admin, maintenance, migration_bridge, collector_ingest;
-- Upgrade an already-published V8 database atomically; the new projection must not
-- silently appear empty before the next collector publication.
DO $backfill$
DECLARE revision bigint;
BEGIN
    SELECT max(dataset_revision_id) INTO revision FROM analytics.projection_state WHERE status='ready';
    IF revision IS NOT NULL THEN PERFORM analytics.rebuild_core_projections(revision); END IF;
END
$backfill$;
RESET ROLE;
