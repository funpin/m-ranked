-- One-time atomic transition from the production schema observed on 2026-09-08
-- to the final storage/publisher schema. This is intentionally not a Flyway
-- migration and is never run by application startup or a normal deploy.
-- Apply only through the explicit database cutover procedure after backup and
-- restored-copy rehearsal.

BEGIN;

SET ROLE migration_owner;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '15min';

DO $production_contract_guard$
BEGIN
    IF to_regclass('ingest.publication_metric_snapshot') IS NULL
       OR to_regclass('analytics.dataset_revision') IS NULL
       OR to_regclass('ops_and_admin.outbox_event') IS NULL
       OR to_regclass('catalog.legacy_entity_alias') IS NULL
       OR to_regclass('migration.identity_map_history') IS NULL
       OR to_regprocedure('analytics.rebuild_core_projections(bigint)') IS NULL THEN
        RAISE EXCEPTION
            'source database does not match the verified production schema';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'ingest.publication'::regclass
           AND conname = 'publication_baseline_history_check'
           AND pg_get_constraintdef(oid) LIKE '%forced_incomplete%'
    ) THEN
        RAISE EXCEPTION
            'source database is not the exact observed production baseline';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM pg_attribute
         WHERE attrelid = 'ingest.publication_metric_snapshot'::regclass
           AND attname = 'semantic_fingerprint'
           AND NOT attisdropped
    ) OR to_regclass('ops_and_admin.schema_contract') IS NOT NULL THEN
        RAISE EXCEPTION
            'final schema is already installed or the source is not the verified production schema';
    END IF;
END
$production_contract_guard$;

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Semantic publication snapshots and compact availability state
-- ---------------------------------------------------------------------------
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

-- A fixed-width digest lets collectors distinguish a changed historical state
-- from another successful poll.  Existing rows remain NULL: their complete
-- semantic input is not reconstructible after raw-evidence retention expires.
ALTER TABLE ingest.publication_metric_snapshot
    ADD COLUMN semantic_fingerprint bytea
    CHECK (
        semantic_fingerprint IS NULL
        OR octet_length(semantic_fingerprint) = 32
    );

COMMENT ON COLUMN ingest.publication_metric_snapshot.semantic_fingerprint IS
'SHA-256 of historical metric/quality/evidence/reaction semantics, excluding poll and run timestamps. NULL only for rows preceding the final schema contract.';

CREATE OR REPLACE VIEW ingest.publication_metric_snapshot_active AS
SELECT s.*
FROM ingest.publication_metric_snapshot AS s
WHERE NOT EXISTS (
    SELECT 1
    FROM ingest.publication_metric_snapshot AS successor
    WHERE successor.published_month = s.published_month
      AND successor.publication_id = s.publication_id
      AND successor.sampling_bucket = s.sampling_bucket
      AND successor.correction_sequence > s.correction_sequence
);

-- Current availability is one narrow, HOT-update-friendly row per publication.
-- The append-only table below contains only transitions or changed probe facts.
CREATE TABLE ingest.publication_availability_state (
    publication_id uuid PRIMARY KEY
        REFERENCES ingest.publication(id) ON DELETE CASCADE,
    status ingest.deletion_probe_outcome NOT NULL,
    last_probe_outcome ingest.deletion_probe_outcome NOT NULL,
    last_checked_at timestamptz NOT NULL,
    last_present_at timestamptz,
    first_missing_at timestamptz,
    consecutive_missing integer NOT NULL CHECK (consecutive_missing >= 0),
    reason_code text NOT NULL CHECK (btrim(reason_code) <> ''),
    last_collection_run_id uuid NOT NULL
        REFERENCES ingest.collection_run(id),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK (status IN ('present', 'missing', 'confirmed_deleted')),
    CHECK (
        (status = 'present' AND consecutive_missing = 0 AND first_missing_at IS NULL)
        OR (status IN ('missing', 'confirmed_deleted')
            AND consecutive_missing > 0 AND first_missing_at IS NOT NULL)
    ),
    CHECK (last_present_at IS NULL OR last_present_at <= last_checked_at),
    CHECK (first_missing_at IS NULL OR first_missing_at <= last_checked_at)
) WITH (fillfactor = 80);

CREATE TABLE ingest.publication_availability_event (
    publication_id uuid NOT NULL
        REFERENCES ingest.publication(id) ON DELETE CASCADE,
    collection_run_id uuid NOT NULL
        REFERENCES ingest.collection_run(id),
    observed_at timestamptz NOT NULL,
    old_status ingest.deletion_probe_outcome,
    new_status ingest.deletion_probe_outcome NOT NULL,
    probe_outcome ingest.deletion_probe_outcome NOT NULL,
    reason_code text NOT NULL CHECK (btrim(reason_code) <> ''),
    consecutive_missing integer NOT NULL CHECK (consecutive_missing >= 0),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (publication_id, collection_run_id, observed_at),
    CHECK (old_status IS NULL OR old_status IN ('present', 'missing', 'confirmed_deleted')),
    CHECK (new_status IN ('present', 'missing', 'confirmed_deleted'))
);

CREATE TRIGGER availability_event_immutable
BEFORE UPDATE OR DELETE ON ingest.publication_availability_event
FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();

-- Seed current state without deleting or rewriting legacy history.  A latest
-- transient/unsupported result does not erase the latest authoritative state.
WITH latest_probe AS (
    SELECT DISTINCT ON (observation.publication_id)
           observation.publication_id,
           observation.collection_run_id,
           observation.observed_at,
           observation.outcome,
           observation.reason_code,
           observation.consecutive_missing
    FROM ingest.deletion_observation AS observation
    ORDER BY observation.publication_id,
             observation.observed_at DESC,
             observation.id DESC
),
latest_authoritative AS (
    SELECT DISTINCT ON (observation.publication_id)
           observation.publication_id,
           observation.outcome AS status,
           observation.consecutive_missing
    FROM ingest.deletion_observation AS observation
    WHERE observation.outcome IN ('present', 'missing', 'confirmed_deleted')
    ORDER BY observation.publication_id,
             observation.observed_at DESC,
             observation.id DESC
),
last_present AS (
    SELECT observation.publication_id, max(observation.observed_at) AS observed_at
    FROM ingest.deletion_observation AS observation
    WHERE observation.outcome = 'present'
    GROUP BY observation.publication_id
),
first_missing AS (
    SELECT observation.publication_id, min(observation.observed_at) AS observed_at
    FROM ingest.deletion_observation AS observation
    LEFT JOIN last_present
      ON last_present.publication_id = observation.publication_id
    WHERE observation.outcome IN ('missing', 'confirmed_deleted')
      AND observation.observed_at > coalesce(last_present.observed_at, '-infinity'::timestamptz)
    GROUP BY observation.publication_id
)
INSERT INTO ingest.publication_availability_state (
    publication_id, status, last_probe_outcome, last_checked_at,
    last_present_at, first_missing_at, consecutive_missing, reason_code,
    last_collection_run_id
)
SELECT latest_probe.publication_id,
       coalesce(
           latest_authoritative.status,
           CASE WHEN publication.deleted_at IS NULL
                THEN 'present'::ingest.deletion_probe_outcome
                ELSE 'confirmed_deleted'::ingest.deletion_probe_outcome END
       ),
       latest_probe.outcome,
       latest_probe.observed_at,
       last_present.observed_at,
       CASE WHEN coalesce(
                    latest_authoritative.status,
                    CASE WHEN publication.deleted_at IS NULL
                         THEN 'present'::ingest.deletion_probe_outcome
                         ELSE 'confirmed_deleted'::ingest.deletion_probe_outcome END
                 ) IN ('missing', 'confirmed_deleted')
            THEN coalesce(first_missing.observed_at, latest_probe.observed_at) END,
       CASE WHEN coalesce(
                    latest_authoritative.status,
                    CASE WHEN publication.deleted_at IS NULL
                         THEN 'present'::ingest.deletion_probe_outcome
                         ELSE 'confirmed_deleted'::ingest.deletion_probe_outcome END
                 ) = 'present'
            THEN 0 ELSE greatest(coalesce(latest_authoritative.consecutive_missing, 1), 1) END,
       latest_probe.reason_code,
       latest_probe.collection_run_id
FROM latest_probe
JOIN ingest.publication AS publication ON publication.id = latest_probe.publication_id
LEFT JOIN latest_authoritative USING (publication_id)
LEFT JOIN last_present USING (publication_id)
LEFT JOIN first_missing USING (publication_id);

GRANT SELECT, INSERT, UPDATE ON ingest.publication_availability_state
    TO collector_ingest;
GRANT SELECT, INSERT ON ingest.publication_availability_event
    TO collector_ingest;
GRANT SELECT, INSERT, UPDATE ON ingest.publication_availability_state
    TO migration_bridge;
GRANT SELECT, INSERT ON ingest.publication_availability_event
    TO migration_bridge;
GRANT SELECT ON
    ingest.publication_availability_state,
    ingest.publication_availability_event
    TO maintenance;

-- Keep the legacy INSERT grant during the compatibility window so rolling back
-- collector code does not require a DDL rollback. Final-contract collectors do not use it;
-- revocation belongs in a later cleanup migration after the rollback window.

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Captured projection watermark
-- ---------------------------------------------------------------------------
-- Permit a projection build to finish at its captured high-water mark while
-- collectors continue committing newer revisions. Publication remains atomic:
-- all projection and state changes occur in the caller's single transaction.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '5min';

DO $migration$
DECLARE
    definition text;
    stale_guard text := $guard$
    SELECT max(id) INTO newest_revision_id FROM analytics.dataset_revision;
    IF newest_revision_id IS DISTINCT FROM p_dataset_revision_id THEN
        RAISE EXCEPTION 'refusing to publish stale revision %; newest revision is %',
            p_dataset_revision_id, newest_revision_id;
    END IF;
$guard$;
BEGIN
    definition := pg_get_functiondef(
        'analytics.rebuild_core_projections_v2(bigint)'::regprocedure
    );
    IF position('LOCK TABLE analytics.dataset_revision IN SHARE MODE;' IN definition) = 0 THEN
        RAISE EXCEPTION 'projection lock patch anchor is missing';
    END IF;
    IF position(stale_guard IN definition) = 0 THEN
        RAISE EXCEPTION 'projection latest-revision guard patch anchor is missing';
    END IF;
    definition := replace(
        definition,
        'LOCK TABLE analytics.dataset_revision IN SHARE MODE;',
        '-- Captured watermarks do not block dataset revision writers.'
    );
    definition := replace(
        definition,
        stale_guard,
        E'    -- Newer revisions remain queued for a later publication.\n'
    );
    EXECUTE definition;
END
$migration$;

COMMENT ON FUNCTION analytics.rebuild_core_projections_v2(bigint) IS
'Builds an atomic generation at a captured dataset revision. Newer collector revisions neither block nor invalidate the running generation.';

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Semantic account snapshots
-- ---------------------------------------------------------------------------
-- Account polls use the same semantic snapshot/heartbeat policy as publication
-- metrics. Poll/run timestamps and collector transport metadata do not create a
-- new historical subscriber observation by themselves.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '5min';

ALTER TABLE ingest.account_metric_snapshot
    ADD COLUMN semantic_fingerprint bytea
    CHECK (
        semantic_fingerprint IS NULL
        OR octet_length(semantic_fingerprint) = 32
    );

COMMENT ON COLUMN ingest.account_metric_snapshot.semantic_fingerprint IS
'SHA-256 of subscriber value/display/quality semantics, excluding poll, run, collector version and transport timestamps. NULL only for rows preceding the final schema transition.';

CREATE OR REPLACE VIEW ingest.account_metric_snapshot_active AS
SELECT snapshot.*
FROM ingest.account_metric_snapshot AS snapshot
WHERE NOT EXISTS (
    SELECT 1
    FROM ingest.account_metric_snapshot AS successor
    WHERE successor.platform_account_id = snapshot.platform_account_id
      AND successor.observed_at = snapshot.observed_at
      AND successor.correction_sequence > snapshot.correction_sequence
);

GRANT SELECT ON ingest.account_metric_snapshot_active
    TO collector_ingest, migration_bridge, maintenance;

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Outbox classes and storage observability
-- ---------------------------------------------------------------------------
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '5min';

ALTER TABLE ops_and_admin.outbox_event
    ADD COLUMN terminal_at timestamptz,
    ADD COLUMN terminal_reason text,
    ADD CONSTRAINT outbox_terminal_state_complete CHECK (
        (terminal_at IS NULL AND terminal_reason IS NULL)
        OR (terminal_at IS NOT NULL AND btrim(terminal_reason) <> '')
    );

CREATE INDEX outbox_event_class_pending_idx
    ON ops_and_admin.outbox_event (event_type, available_at, id)
    INCLUDE (occurred_at, publish_attempts)
    WHERE published_at IS NULL AND terminal_at IS NULL;

CREATE TABLE ops_and_admin.storage_observation (
    observed_at timestamptz PRIMARY KEY DEFAULT transaction_timestamp(),
    database_size_bytes bigint NOT NULL CHECK (database_size_bytes >= 0),
    temporary_bytes bigint NOT NULL CHECK (temporary_bytes >= 0),
    wal_bytes numeric NOT NULL CHECK (wal_bytes >= 0),
    largest_relations jsonb NOT NULL CHECK (jsonb_typeof(largest_relations) = 'array'),
    row_estimates jsonb NOT NULL CHECK (jsonb_typeof(row_estimates) = 'object')
);

CREATE FUNCTION ops_and_admin.refresh_storage_observation() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, ops_and_admin
SET lock_timeout = '2s'
SET statement_timeout = '2min'
AS $function$
DECLARE
    sample ops_and_admin.storage_observation%ROWTYPE;
BEGIN
    INSERT INTO ops_and_admin.storage_observation (
        database_size_bytes, temporary_bytes, wal_bytes,
        largest_relations, row_estimates
    )
    SELECT pg_database_size(current_database()),
           database_stats.temp_bytes,
           wal_stats.wal_bytes,
           coalesce((
               SELECT jsonb_agg(to_jsonb(relation_size) ORDER BY relation_size.total_bytes DESC)
               FROM (
                   SELECT namespace.nspname AS schema,
                          relation.relname AS relation,
                          pg_total_relation_size(relation.oid) AS total_bytes,
                          pg_relation_size(relation.oid) AS heap_bytes,
                          pg_indexes_size(relation.oid) AS index_bytes
                   FROM pg_class AS relation
                   JOIN pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   WHERE namespace.nspname IN ('ingest', 'analytics')
                     AND relation.relkind IN ('r', 'm')
                   ORDER BY total_bytes DESC
                   LIMIT 12
               ) AS relation_size
           ), '[]'::jsonb),
           coalesce((
               WITH observed_table(schema_name, relation_name) AS (VALUES
                   ('ingest', 'publication_metric_snapshot'),
                   ('ingest', 'account_metric_snapshot'),
                   ('ingest', 'reaction_breakdown'),
                   ('ingest', 'deletion_observation'),
                   ('ingest', 'publication_availability_event'),
                   ('analytics', 'publication_history'),
                   ('analytics', 'legacy_export_row')
               ), estimates AS (
                   SELECT concat(observed.schema_name, '.', observed.relation_name) AS relation,
                          coalesce(sum(table_stats.n_live_tup), 0)::bigint AS estimated_rows
                     FROM observed_table AS observed
                     JOIN pg_namespace AS namespace
                       ON namespace.nspname = observed.schema_name
                     JOIN pg_class AS root
                       ON root.relnamespace = namespace.oid
                      AND root.relname = observed.relation_name
                     LEFT JOIN LATERAL pg_partition_tree(root.oid) AS tree ON true
                     LEFT JOIN pg_stat_all_tables AS table_stats
                       ON table_stats.relid = coalesce(tree.relid, root.oid)
                    GROUP BY observed.schema_name, observed.relation_name
               )
               SELECT jsonb_object_agg(relation, estimated_rows)
                 FROM estimates
           ), '{}'::jsonb)
      FROM pg_stat_database AS database_stats
     CROSS JOIN pg_stat_wal AS wal_stats
     WHERE database_stats.datname = current_database()
    RETURNING * INTO sample;

    -- Hourly execution retains at most about 744 tiny rows. This bounded delete
    -- never touches collector facts or projection data.
    DELETE FROM ops_and_admin.storage_observation
     WHERE observed_at < sample.observed_at - interval '31 days';

    RETURN to_jsonb(sample);
END
$function$;

REVOKE ALL ON FUNCTION ops_and_admin.refresh_storage_observation() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.refresh_storage_observation() TO maintenance;
GRANT SELECT ON ops_and_admin.storage_observation TO maintenance;

CREATE OR REPLACE FUNCTION ops_and_admin.public_health_snapshot()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog
SET statement_timeout = '3s'
AS $function$
WITH keys(key) AS (
    VALUES ('last_poll'),('next_poll'),('poll_last_started_at'),('poll_last_completed_at'),
      ('poll_last_duration_seconds'),('poll_last_error_count'),('poll_last_channel_count'),
      ('telegram_web_last_success_at'),('telegram_web_last_error'),
      ('vk_poll_last_completed_at'),('vk_poll_last_duration_seconds'),('vk_poll_last_error_count'),('vk_poll_last_account_count'),
      ('max_poll_last_completed_at'),('max_poll_last_duration_seconds'),('max_poll_last_error_count'),('max_poll_last_account_count'),
      ('rutube_poll_last_completed_at'),('rutube_poll_last_duration_seconds'),('rutube_poll_last_error_count'),('rutube_poll_last_account_count')
), checkpoints AS (
    SELECT keys.key, CASE
      WHEN c.value IS NULL OR c.value='null'::jsonb THEN 'null'::jsonb
      WHEN keys.key='telegram_web_last_error' THEN
        CASE WHEN c.value='""'::jsonb OR c.value='false'::jsonb OR c.value->'present'='false'::jsonb
             THEN 'null'::jsonb ELSE '"upstream_error"'::jsonb END
      WHEN keys.key ~ '(count|seconds)$' AND c.value #>> '{}' ~ '^[0-9]{1,12}(\.[0-9]{1,6})?$' THEN to_jsonb(c.value #>> '{}')
      WHEN keys.key ~ '(_at|_poll)$' AND c.value #>> '{}' ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{5,30}Z?$' THEN c.value
      ELSE 'null'::jsonb END AS value
    FROM keys LEFT JOIN LATERAL (
      SELECT CASE WHEN jsonb_typeof(value)='object' AND value ? 'unparsed_text'
        THEN value->'unparsed_text' ELSE value END AS value
      FROM ops_and_admin.operational_checkpoint c
      WHERE c.checkpoint_key=keys.key AND c.scope_type IN ('system','platform')
      ORDER BY c.source_observed_at DESC NULLS LAST,c.updated_at DESC,c.id DESC LIMIT 1
    ) c ON true
), platforms(platform) AS (VALUES ('telegram'),('vk'),('max'),('rutube')),
run_states AS (
    SELECT p.platform, jsonb_build_object('started_at',started.started_at,'completed_at',r.completed_at,
      'duration_seconds',extract(epoch FROM r.completed_at-r.started_at),'status',r.status,
      'error_count',r.error_count,'account_count',r.account_count) AS value
    FROM platforms p LEFT JOIN LATERAL (
      SELECT started_at FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%'
      ORDER BY r.started_at DESC,r.id DESC LIMIT 1
    ) started ON true LEFT JOIN LATERAL (
      SELECT started_at,completed_at,status,error_count,account_count FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%' AND completed_at IS NOT NULL
      ORDER BY r.completed_at DESC,r.id DESC LIMIT 1
    ) r ON true
), required(name) AS (VALUES ('publication_latest'),('publication_hourly'),('institution_daily_metrics'),
    ('institution_monthly_metrics'),('institution_period_metrics'),('comparison')),
published AS (
    SELECT s.dataset_revision_id, revision.committed_at
      FROM analytics.projection_state s
      JOIN analytics.dataset_revision AS revision
        ON revision.id = s.dataset_revision_id
    WHERE s.status='ready' AND s.projection_name IN (SELECT name FROM required)
    GROUP BY s.dataset_revision_id, revision.committed_at
    HAVING count(*)=(SELECT count(*) FROM required)
    ORDER BY s.dataset_revision_id DESC LIMIT 1
), outbox_class AS (
    SELECT CASE
             WHEN event_type = 'projection.rebuild.requested' THEN 'projectionControl'
             WHEN event_type = 'projection.published' THEN 'projectionLifecycle'
             ELSE 'cacheDelivery'
           END AS class,
           count(*) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS pending,
           min(occurred_at) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS oldest_pending_at,
           max(publish_attempts) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS max_attempts,
           count(*) FILTER (WHERE terminal_at IS NOT NULL) AS terminal
      FROM ops_and_admin.outbox_event
     GROUP BY class
), outbox AS (
    SELECT jsonb_build_object(
        'classes', coalesce((SELECT jsonb_object_agg(class, jsonb_build_object(
            'pending', pending,
            'oldestPendingAt', oldest_pending_at,
            'maxAttempts', coalesce(max_attempts, 0),
            'terminal', terminal
        )) FROM outbox_class), '{}'::jsonb),
        'oldestDeliverableAt', (
            SELECT min(occurred_at)
              FROM ops_and_admin.outbox_event
             WHERE published_at IS NULL
               AND terminal_at IS NULL
               AND event_type <> 'projection.rebuild.requested'
               AND event_type <> 'projection.published'
        )
    ) AS value
), storage AS (
    SELECT current_sample.*,
           CASE WHEN previous_sample.observed_at IS NULL THEN NULL ELSE
             round((current_sample.database_size_bytes-previous_sample.database_size_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS growth_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.wal_bytes < previous_sample.wal_bytes THEN NULL ELSE
             round((current_sample.wal_bytes-previous_sample.wal_bytes)
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS wal_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.temporary_bytes < previous_sample.temporary_bytes THEN NULL ELSE
             round((current_sample.temporary_bytes-previous_sample.temporary_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS temporary_bytes_per_day
      FROM LATERAL (
          SELECT * FROM ops_and_admin.storage_observation ORDER BY observed_at DESC LIMIT 1
      ) AS current_sample
      LEFT JOIN LATERAL (
          SELECT * FROM ops_and_admin.storage_observation
           WHERE observed_at < current_sample.observed_at ORDER BY observed_at DESC LIMIT 1
      ) AS previous_sample ON true
)
SELECT jsonb_build_object(
    'asOf',statement_timestamp(),
    'channels',(SELECT count(*) FROM catalog.platform_account WHERE platform='telegram' AND enabled),
    'checkpoints',(SELECT jsonb_object_agg(key,value) FROM checkpoints),
    'runs',(SELECT jsonb_object_agg(platform,value) FROM run_states),
    'rawRevision',coalesce((SELECT max(id) FROM analytics.dataset_revision),0),
    'publishedRevision',coalesce((SELECT dataset_revision_id FROM published),0),
    'publishedGenerationAgeSeconds',(
        SELECT greatest(0, extract(epoch FROM statement_timestamp()-committed_at))::bigint
          FROM published
    ),
    'revisionLag',greatest(0,
        coalesce((SELECT max(id) FROM analytics.dataset_revision),0)
        - coalesce((SELECT dataset_revision_id FROM published),0)),
    'outbox',(SELECT value FROM outbox),
    'storage',coalesce((SELECT jsonb_build_object(
        'sampledAt',observed_at,
        'databaseSizeBytes',database_size_bytes,
        'growthBytesPerDay',growth_bytes_per_day,
        'walBytesPerDay',wal_bytes_per_day,
        'temporaryBytesPerDay',temporary_bytes_per_day,
        'largestRelations',largest_relations,
        'rowEstimates',row_estimates
    ) FROM storage), '{}'::jsonb)
)
$function$;

REVOKE ALL ON FUNCTION ops_and_admin.public_health_snapshot() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.public_health_snapshot() TO api_read,maintenance;

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Serving-only projection generation
-- ---------------------------------------------------------------------------
-- Normal publication advances the seven public serving projections, including
-- publication history. Content and legacy export remain compatibility data
-- refreshed only through an explicit bootstrap.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '5min';

-- The publisher must be runnable immediately after both a clean bootstrap and
-- the guarded production transition. Preserve any stricter existing policy;
-- only create or raise the publication hot window to the parity-safe floor.
INSERT INTO ops_and_admin.retention_policy (
    data_class, hot_days, retention_months, archive_required, notes
) VALUES (
    'publication_metric_snapshot', 90, NULL, true,
    'Default final-schema hot window; do not reduce below 70 days during parity.'
)
ON CONFLICT (data_class) DO UPDATE
SET hot_days = greatest(ops_and_admin.retention_policy.hot_days, 70),
    archive_required = true,
    notes = CASE
        WHEN ops_and_admin.retention_policy.hot_days IS NULL
          OR ops_and_admin.retention_policy.hot_days < 70
        THEN excluded.notes
        ELSE ops_and_admin.retention_policy.notes
    END,
    updated_at = CASE
        WHEN ops_and_admin.retention_policy.hot_days IS NULL
          OR ops_and_admin.retention_policy.hot_days < 70
          OR NOT ops_and_admin.retention_policy.archive_required
        THEN transaction_timestamp()
        ELSE ops_and_admin.retention_policy.updated_at
    END;

CREATE FUNCTION analytics.rebuild_serving_projections(
    p_dataset_revision_id bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    result jsonb;
BEGIN
    -- History belongs to the public consistency boundary.  Publishing it in
    -- the same transaction prevents a newer revision from labelling stale
    -- publication/account history as current.
    result := analytics.rebuild_core_projections_v13(p_dataset_revision_id);
    RETURN result || jsonb_build_object(
        'official_account_ratings',
        analytics.refresh_official_account_ratings(p_dataset_revision_id),
        'publication_history_reactions',
        analytics.refresh_history_reaction_details(p_dataset_revision_id),
        'generation', 'serving'
    );
END
$function$;

REVOKE ALL ON FUNCTION analytics.rebuild_serving_projections(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.rebuild_serving_projections(bigint)
    TO maintenance;

COMMENT ON FUNCTION analytics.rebuild_serving_projections(bigint) IS
'Atomically publishes the seven API serving projections, including publication history, at a captured high-water mark without rebuilding content or legacy CSV exports.';

RESET ROLE;

-- ---------------------------------------------------------------------------
-- Remove serving/runtime dependencies on the completed migration subsystem
-- ---------------------------------------------------------------------------
-- Remove hot/runtime reads from the completed SQLite bridge schema. Recovery
-- evidence stays in migration.* until the separately rehearsed drop is approved.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

ALTER TABLE rating.official_rating_observation
    ADD COLUMN entity_scope text NOT NULL DEFAULT 'institution'
    CHECK (entity_scope IN ('institution', 'legacy_account'));

UPDATE rating.official_rating_observation AS observation
   SET entity_scope = 'legacy_account'
 WHERE EXISTS (
    SELECT 1
      FROM migration.legacy_identity_map AS mapping
     WHERE mapping.target_uuid = observation.id
       AND mapping.source_table = 'channels'
       AND mapping.target_type = 'official_rating_observation:telegram'
 );

CREATE OR REPLACE VIEW rating.official_institution_rating_observation AS
SELECT observation.*
  FROM rating.official_rating_observation AS observation
 WHERE observation.entity_scope = 'institution';

GRANT SELECT ON rating.official_institution_rating_observation
    TO api_read, api_write_admin, maintenance;

CREATE OR REPLACE FUNCTION analytics.refresh_official_account_ratings(
    p_revision bigint
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics, rating
AS $function$
DECLARE written bigint;
BEGIN
    UPDATE analytics.legacy_overview_card
       SET rating_rank = NULL,
           rating_score = NULL,
           rating_period = NULL,
           rating_fetched_at = NULL
     WHERE platform = 'telegram'
       AND dataset_revision_id = p_revision;

    WITH latest AS (
        SELECT DISTINCT ON (observation.platform_account_id) observation.*
          FROM rating.official_account_rating_observation AS observation
          JOIN analytics.dataset_revision AS revision ON revision.id = p_revision
         WHERE observation.fetched_at <= revision.committed_at
         ORDER BY observation.platform_account_id,
                  observation.fetched_at DESC,
                  observation.id DESC
    )
    UPDATE analytics.legacy_overview_card AS card
       SET rating_rank = latest.rank,
           rating_score = latest.score,
           rating_period = latest.period,
           rating_fetched_at = latest.fetched_at
      FROM latest
     WHERE card.platform = 'telegram'
       AND card.entity_id = latest.platform_account_id
       AND card.dataset_revision_id = p_revision;
    GET DIAGNOSTICS written = ROW_COUNT;
    RETURN written;
END
$function$;

CREATE OR REPLACE FUNCTION ops_and_admin.legacy_account_presentation(
    p_account uuid
) RETURNS TABLE(access_mode text, last_error_code text, error_present boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest
SET statement_timeout = '3s'
AS $function$
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
$function$;

-- The pre-history serving chain inherited a legacy-error CTE.
-- Replace only that CTE with an empty, typed compatibility input: completed
-- target collection results above are now the authoritative runtime status.
DO $patch_serving$
DECLARE
    definition text;
    start_at integer;
    finish_at integer;
    replacement text := $replacement$    ), legacy_error AS (
        SELECT NULL::uuid AS platform_account_id,
               false AS channel_error,
               false AS platform_account_error
         WHERE false
$replacement$;
BEGIN
    definition := pg_get_functiondef(
        'analytics.rebuild_core_projections_v9(bigint)'::regprocedure
    );
    start_at := position('    ), legacy_error AS (' IN definition);
    finish_at := position('    ), last_checked AS (' IN definition);
    IF start_at = 0 OR finish_at <= start_at THEN
        RAISE EXCEPTION 'legacy-error projection dependency patch anchors are missing';
    END IF;
    definition := overlay(
        definition PLACING replacement
        FROM start_at FOR finish_at - start_at
    );
    EXECUTE definition;
END
$patch_serving$;

-- Configuration writes must not synchronously run the historical bootstrap.
-- Preserve their atomic revision/audit/domain-event transaction and enqueue a
-- coalescible projection-control event for the explicit oneshot publisher.
DO $patch_admin_publication$
DECLARE
    signature regprocedure;
    definition text;
    old_call text := 'PERFORM analytics.rebuild_core_projections(revision);';
    queued_call text := $queued$INSERT INTO ops_and_admin.outbox_event(
            dataset_revision_id, event_type, aggregate_type, aggregate_id,
            affected_tags, payload
        ) VALUES (
            revision, 'projection.rebuild.requested', 'projection', 'core',
            ARRAY['publications', 'overview', 'comparison'],
            jsonb_build_object('revision', revision, 'cause', 'configuration')
        )
        ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
        DO NOTHING;$queued$;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid)'::regprocedure,
        'ops_and_admin.import_official_rating(jsonb,text,uuid)'::regprocedure
    ] LOOP
        definition := pg_get_functiondef(signature);
        IF position(old_call IN definition) = 0 THEN
            RAISE EXCEPTION 'admin projection patch anchor is missing in %', signature;
        END IF;
        definition := replace(definition, old_call, queued_call);
        EXECUTE definition;
    END LOOP;
END
$patch_admin_publication$;

CREATE OR REPLACE FUNCTION analytics.refresh_publication_content(
    p_revision bigint
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics, ingest
AS $function$
DECLARE rows_written bigint;
BEGIN
    INSERT INTO analytics.publication_content(
        publication_id, archived_text, dataset_revision_id
    )
    SELECT publication.id, NULL, p_revision
      FROM ingest.publication AS publication
      JOIN analytics.dataset_revision AS revision ON revision.id = p_revision
     WHERE publication.published_at <= revision.committed_at
    ON CONFLICT (publication_id) DO UPDATE
       SET dataset_revision_id = excluded.dataset_revision_id;
    GET DIAGNOSTICS rows_written = ROW_COUNT;
    INSERT INTO analytics.projection_state(
        projection_name, dataset_revision_id, status, refreshed_at, row_count
    ) VALUES (
        'publication_content', p_revision, 'ready',
        transaction_timestamp(), rows_written
    )
    ON CONFLICT(projection_name) DO UPDATE SET
        dataset_revision_id = excluded.dataset_revision_id,
        status = excluded.status,
        refreshed_at = excluded.refreshed_at,
        row_count = excluded.row_count,
        error_code = NULL;
    RETURN rows_written;
END
$function$;

CREATE OR REPLACE FUNCTION analytics.refresh_history_reaction_details(
    p_revision bigint
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics
AS $function$
DECLARE written bigint;
BEGIN
    WITH history AS MATERIALIZED (
        SELECT item.*,
               lag(item.reaction_breakdown) OVER chronology AS prior_reactions,
               lag(item.reactions_count) OVER chronology AS prior_reactions_count
          FROM analytics.publication_history AS item
         WHERE dataset_revision_id = p_revision
        WINDOW chronology AS (
            PARTITION BY publication_id
            ORDER BY observed_at, published_month, snapshot_id
        )
    ), entries AS (
        SELECT history.*,
               coalesce(
                   analytics.ordered_history_reactions(
                       reaction_breakdown::text, false
                   ),
                   '[]'::jsonb
               ) AS current_entries,
               CASE
                 WHEN reactions_count IS NULL OR prior_reactions_count IS NULL
                   THEN NULL
                 ELSE (
                   SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'reaction', key, 'count', difference
                   ) ORDER BY key COLLATE "C"), '[]'::jsonb)
                     FROM (
                       SELECT key,
                              coalesce((reaction_breakdown->>key)::bigint, 0)
                              - coalesce((prior_reactions->>key)::bigint, 0)
                              AS difference
                         FROM (
                           SELECT jsonb_object_keys(reaction_breakdown) AS key
                           UNION
                           SELECT jsonb_object_keys(prior_reactions) AS key
                         ) AS keys
                     ) AS deltas
                    WHERE difference <> 0
                 )
               END AS delta_entries
          FROM history
    )
    UPDATE analytics.publication_history AS target
       SET reaction_entries = entries.current_entries,
           delta_reaction_entries = entries.delta_entries,
           delta_reaction_breakdown = CASE
             WHEN entries.delta_entries IS NULL THEN NULL
             ELSE (
               SELECT coalesce(jsonb_object_agg(
                   value->>'reaction', value->'count'
               ), '{}'::jsonb)
                 FROM jsonb_array_elements(entries.delta_entries)
             )
           END,
           lineage = target.lineage || jsonb_build_object(
               'reactionDetailsSource', 'canonical'
           )
      FROM entries
     WHERE target.publication_id = entries.publication_id
       AND target.published_month = entries.published_month
       AND target.snapshot_id = entries.snapshot_id
       AND target.dataset_revision_id = p_revision;
    GET DIAGNOSTICS written = ROW_COUNT;
    RETURN written;
END
$function$;

-- Retain an explicit historical bootstrap without the retired legacy CSV path.
CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections(
    p_dataset_revision_id bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE result jsonb;
BEGIN
    result := analytics.rebuild_core_projections_v13(p_dataset_revision_id);
    RETURN result || jsonb_build_object(
        'publication_content',
        analytics.refresh_publication_content(p_dataset_revision_id),
        'official_account_ratings',
        analytics.refresh_official_account_ratings(p_dataset_revision_id),
        'publication_history_reactions',
        analytics.refresh_history_reaction_details(p_dataset_revision_id),
        'generation', 'historical-bootstrap'
    );
END
$function$;

REVOKE ALL ON FUNCTION
    analytics.refresh_official_account_ratings(bigint),
    analytics.refresh_publication_content(bigint),
    analytics.refresh_history_reaction_details(bigint),
    analytics.rebuild_core_projections(bigint)
FROM PUBLIC, api_write_admin, collector_ingest, migration_bridge, maintenance;
GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO maintenance, migration_bridge;

RESET ROLE;

SET ROLE migration_owner;

CREATE VIEW ops_and_admin.schema_contract AS
SELECT 'storage-publisher-final-2026-09-08-r2'::text AS contract_id;

COMMENT ON VIEW ops_and_admin.schema_contract IS
'Single runtime database contract. Services validate this identifier; historical migration metadata is not a runtime input.';

REVOKE ALL ON ops_and_admin.schema_contract FROM PUBLIC;
GRANT SELECT ON ops_and_admin.schema_contract
    TO api_read, api_write_admin, collector_ingest, maintenance;

RESET ROLE;

COMMIT;
