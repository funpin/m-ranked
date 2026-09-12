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
SET statement_timeout = '2h'
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

-- r3-delta:begin
-- Everything between the r3-delta markers is the difference between the base
-- final contract and storage-publisher-final-2026-09-08-r3. It is replayable on
-- a database that already carries the base final contract, which is how the
-- local review stand upgrades a restored production copy
-- (infra/local/prodcopy.sh). Keep the markers around this section.
-- ---------------------------------------------------------------------------
-- Independent publication-level anomaly analysis (analytics_worker, candidate
-- queue, attempts/state/findings/reviews, safe public views, ADMIN commands).
-- Does not touch analytics.rebuild_core_projections or the seven-projection
-- barrier. The analytics_worker login role must be provisioned before this
-- transition (infra/postgres/init/001-create-roles.sh).
-- ---------------------------------------------------------------------------
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

DO $anomaly_role_guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_worker') THEN
        RAISE EXCEPTION 'analytics_worker role must be provisioned before the final transition';
    END IF;
END
$anomaly_role_guard$;

-- Partition-crossing read plans are priced above jit_above_cost while run-time
-- pruning leaves a single partition, so JIT emission dominates every request.
-- Role defaults keep this out of the schema dump and out of every client.
-- Altering a role needs more than migration_owner holds, so the statement is
-- skipped with a notice when the cutover session cannot issue it; in that case
-- run the three ALTER ROLE statements separately as the superuser.
RESET ROLE;
DO $anomaly_jit_defaults$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND (rolsuper OR rolcreaterole)) THEN
        ALTER ROLE api_read SET jit = off;
        ALTER ROLE api_write_admin SET jit = off;
        ALTER ROLE analytics_worker SET jit = off;
    ELSE
        RAISE NOTICE 'jit defaults not applied: run ALTER ROLE api_read/api_write_admin/analytics_worker SET jit = off as the superuser';
    END IF;
END
$anomaly_jit_defaults$;
SET ROLE migration_owner;


CREATE TABLE analytics.anomaly_analysis_revision (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    reason text NOT NULL CHECK (reason IN ('automatic_success','automatic_failure','manual_signal','review')),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE INDEX anomaly_analysis_revision_publication_idx
    ON analytics.anomaly_analysis_revision(publication_id,id DESC);

CREATE TABLE analytics.anomaly_source_revision (
    dataset_revision_id bigint PRIMARY KEY REFERENCES analytics.dataset_revision(id),
    committed_at timestamptz NOT NULL,
    pinned_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE analytics.publication_analysis_attempt (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    attempt_key uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('succeeded','failed')),
    claimed_generation bigint NOT NULL CHECK (claimed_generation > 0),
    source_dataset_revision_id bigint NOT NULL REFERENCES analytics.dataset_revision(id),
    source_revision_at timestamptz NOT NULL,
    input_hash text CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    detector_manifest_hash text NOT NULL CHECK (detector_manifest_hash ~ '^[0-9a-f]{64}$'),
    preprocessing_version text NOT NULL CHECK (btrim(preprocessing_version) <> ''),
    aggregator_version text NOT NULL CHECK (btrim(aggregator_version) <> ''),
    metric_semantics_version integer NOT NULL CHECK (metric_semantics_version > 0),
    capability_version integer NOT NULL CHECK (capability_version > 0),
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    error_code text,
    analysis_revision_id bigint UNIQUE REFERENCES analytics.anomaly_analysis_revision(id),
    CHECK (completed_at >= started_at),
    CHECK ((status='succeeded' AND input_hash IS NOT NULL AND error_code IS NULL)
        OR (status='failed' AND error_code ~ '^[a-z0-9_]{1,64}$')),
    UNIQUE(publication_id,attempt_key)
);
CREATE INDEX publication_analysis_attempt_retention_idx
    ON analytics.publication_analysis_attempt(publication_id,status,completed_at DESC);

CREATE TABLE analytics.publication_analysis_state (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id),
    analysis_revision_id bigint REFERENCES analytics.anomaly_analysis_revision(id),
    current_success_attempt_id uuid UNIQUE REFERENCES analytics.publication_analysis_attempt(id),
    latest_failure_attempt_id uuid UNIQUE REFERENCES analytics.publication_analysis_attempt(id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','partial','stale','failed')),
    suspicion_score numeric,
    automatic_severity text CHECK (automatic_severity IS NULL OR automatic_severity IN ('low','medium','high')),
    affected_metrics analytics.metric_key[] NOT NULL DEFAULT ARRAY[]::analytics.metric_key[],
    active_automatic_finding_count integer NOT NULL DEFAULT 0 CHECK(active_automatic_finding_count>=0),
    source_dataset_revision_id bigint REFERENCES analytics.dataset_revision(id),
    source_revision_at timestamptz,
    analyzed_at timestamptz,
    input_hash text CHECK(input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
    detector_manifest_hash text CHECK(detector_manifest_hash IS NULL OR detector_manifest_hash ~ '^[0-9a-f]{64}$'),
    preprocessing_version text,
    aggregator_version text,
    CHECK(suspicion_score IS NULL OR (suspicion_score>=0 AND suspicion_score<=1)),
    CHECK((current_success_attempt_id IS NULL)=(analyzed_at IS NULL)),
    CHECK(status<>'ready' OR current_success_attempt_id IS NOT NULL)
);
CREATE INDEX publication_analysis_state_public_idx
    ON analytics.publication_analysis_state(analysis_revision_id DESC,publication_id);

CREATE TABLE analytics.publication_anomaly_finding (
    id uuid PRIMARY KEY,
    -- Stable identity across attempts: publication, origin, metric, detector,
    -- version and suspicious interval. Review state follows this key, so a
    -- re-fired signal keeps its effective decision after retention pruning.
    finding_key uuid NOT NULL,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    attempt_id uuid REFERENCES analytics.publication_analysis_attempt(id) ON DELETE CASCADE,
    created_analysis_revision_id bigint NOT NULL REFERENCES analytics.anomaly_analysis_revision(id),
    origin text NOT NULL CHECK(origin IN ('automatic','manual')),
    metric analytics.metric_key NOT NULL CHECK(metric IN ('views','reactions','comments','shares')),
    detector_id text,
    detector_version text,
    suspicion_score numeric,
    severity text NOT NULL CHECK(severity IN ('low','medium','high')),
    explanation_code text NOT NULL CHECK(explanation_code ~ '^[a-z0-9_]{1,80}$'),
    suspicious_start_at timestamptz NOT NULL,
    suspicious_end_at timestamptz NOT NULL,
    start_snapshot_id text,
    end_snapshot_id text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    alternative_explanation_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK(suspicious_end_at>suspicious_start_at),
    CHECK(jsonb_typeof(evidence)='object' AND pg_column_size(evidence)<=8192),
    CHECK(cardinality(quality_codes)<=16 AND cardinality(alternative_explanation_codes)<=16),
    CHECK((origin='automatic' AND attempt_id IS NOT NULL AND detector_id IS NOT NULL
           AND detector_version IS NOT NULL AND suspicion_score BETWEEN 0 AND 1)
       OR (origin='manual' AND attempt_id IS NULL AND detector_id IS NULL
           AND detector_version IS NULL AND suspicion_score IS NULL))
);
CREATE INDEX publication_anomaly_finding_public_idx
    ON analytics.publication_anomaly_finding(publication_id,created_analysis_revision_id DESC,id);
CREATE UNIQUE INDEX publication_anomaly_finding_attempt_key_idx
    ON analytics.publication_anomaly_finding(attempt_id,finding_key) WHERE attempt_id IS NOT NULL;

CREATE TABLE analytics.publication_anomaly_review (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    finding_key uuid NOT NULL,
    -- Historical reference only: retention prunes superseded automatic findings
    -- and must never fail because an ADMIN reviewed them.
    finding_id uuid NOT NULL,
    analysis_revision_id bigint NOT NULL REFERENCES analytics.anomaly_analysis_revision(id),
    reviewer_subject text NOT NULL CHECK(btrim(reviewer_subject)<>'' AND length(reviewer_subject)<=200),
    decision analytics.review_decision NOT NULL,
    private_comment text CHECK(private_comment IS NULL OR length(private_comment)<=2000),
    reviewed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE INDEX publication_anomaly_review_effective_idx
    ON analytics.publication_anomaly_review(publication_id,finding_key,reviewed_at DESC,id DESC);

CREATE TABLE ops_and_admin.anomaly_analysis_candidate (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id),
    dirty_generation bigint NOT NULL DEFAULT 1 CHECK(dirty_generation>0),
    eligible_at timestamptz NOT NULL,
    priority smallint NOT NULL DEFAULT 100,
    config_backfill boolean NOT NULL DEFAULT false,
    claim_token uuid,
    claimed_generation bigint,
    leased_until timestamptz,
    retry_count integer NOT NULL DEFAULT 0 CHECK(retry_count BETWEEN 0 AND 20),
    last_error_code text CHECK(last_error_code IS NULL OR last_error_code ~ '^[a-z0-9_]{1,64}$'),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CHECK((claim_token IS NULL AND claimed_generation IS NULL AND leased_until IS NULL)
       OR (claim_token IS NOT NULL AND claimed_generation IS NOT NULL AND leased_until IS NOT NULL))
);
CREATE INDEX anomaly_analysis_candidate_claim_idx
    ON ops_and_admin.anomaly_analysis_candidate(priority DESC,eligible_at,publication_id)
    WHERE claim_token IS NULL;
CREATE INDEX anomaly_analysis_candidate_lease_idx
    ON ops_and_admin.anomaly_analysis_candidate(leased_until) WHERE claim_token IS NOT NULL;

CREATE TABLE ops_and_admin.anomaly_command_receipt (
    subject text NOT NULL,
    command_type text NOT NULL CHECK(command_type IN ('manual_signal','review')),
    idempotency_key uuid NOT NULL,
    request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL CHECK(jsonb_typeof(result)='object' AND pg_column_size(result)<=4096),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY(subject,command_type,idempotency_key)
);

CREATE FUNCTION ops_and_admin.mark_anomaly_candidate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ingest,ops_and_admin AS $function$
BEGIN
    INSERT INTO ops_and_admin.anomaly_analysis_candidate(
        publication_id,dirty_generation,eligible_at,priority,config_backfill,updated_at
    )
    SELECT NEW.publication_id,1,greatest(
        published_at+interval '15 minutes',
        transaction_timestamp()+CASE
          WHEN transaction_timestamp()-published_at<interval '6 hours' THEN interval '2 minutes'
          WHEN transaction_timestamp()-published_at<interval '1 day' THEN interval '5 minutes'
          WHEN transaction_timestamp()-published_at<interval '7 days' THEN interval '15 minutes'
          ELSE interval '1 hour' END
      ),100,false,transaction_timestamp()
      FROM ingest.publication WHERE id=NEW.publication_id
    ON CONFLICT(publication_id) DO UPDATE SET
        dirty_generation=ops_and_admin.anomaly_analysis_candidate.dirty_generation+1,
        eligible_at=least(ops_and_admin.anomaly_analysis_candidate.eligible_at,excluded.eligible_at),
        priority=greatest(ops_and_admin.anomaly_analysis_candidate.priority,100),
        config_backfill=false,updated_at=transaction_timestamp();
    RETURN NULL;
END $function$;
CREATE TRIGGER anomaly_candidate_after_effective_snapshot
AFTER INSERT ON ingest.publication_metric_snapshot
FOR EACH ROW EXECUTE FUNCTION ops_and_admin.mark_anomaly_candidate();

CREATE FUNCTION ops_and_admin.seed_anomaly_backfill(p_limit integer,p_manifest_hash text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,catalog,ingest,analytics,ops_and_admin
SET statement_timeout='15s' AS $function$
DECLARE inserted_count integer;
BEGIN
    IF p_limit<1 OR p_limit>1000 OR p_manifest_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid bounded anomaly backfill request';
    END IF;
    WITH eligible AS (
        SELECT publication.id
          FROM ingest.publication publication
         WHERE publication.published_at>=transaction_timestamp()-interval '70 days'
           AND publication.published_at<=transaction_timestamp()-interval '15 minutes'
           AND NOT EXISTS (
               SELECT 1 FROM analytics.publication_analysis_state state
                WHERE state.publication_id=publication.id
                  AND state.detector_manifest_hash=p_manifest_hash
           )
           AND NOT EXISTS (
               SELECT 1 FROM ops_and_admin.anomaly_analysis_candidate candidate
                WHERE candidate.publication_id=publication.id
           )
           AND EXISTS (
               SELECT 1 FROM ingest.publication_metric_snapshot snapshot
                WHERE snapshot.publication_id=publication.id
           )
         ORDER BY publication.published_at DESC,publication.id
         LIMIT p_limit
    ), inserted AS (
        INSERT INTO ops_and_admin.anomaly_analysis_candidate(
            publication_id,dirty_generation,eligible_at,priority,config_backfill
        ) SELECT id,1,transaction_timestamp(),10,true FROM eligible
        ON CONFLICT(publication_id) DO NOTHING
        RETURNING 1
    ) SELECT count(*) INTO inserted_count FROM inserted;
    RETURN inserted_count;
END $function$;

CREATE FUNCTION analytics.latest_fully_published_dataset_revision()
RETURNS TABLE(id bigint,committed_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,analytics
AS $function$
-- Mirrors the core barrier of JdbcDatasetRevisionProvider.CURRENT_REVISION_SQL.
WITH required(name) AS (VALUES
 ('publication_latest'),('publication_hourly'),('institution_daily_metrics'),
 ('institution_monthly_metrics'),('institution_period_metrics'),('comparison'),
 ('publication_history')
)
SELECT revision.id,revision.committed_at
  FROM analytics.dataset_revision revision
 CROSS JOIN required
  LEFT JOIN analytics.projection_state state
    ON state.projection_name=required.name AND state.dataset_revision_id=revision.id AND state.status='ready'
 GROUP BY revision.id,revision.committed_at
HAVING count(state.projection_name)=7
 ORDER BY revision.id DESC LIMIT 1
$function$;

CREATE FUNCTION ops_and_admin.pin_latest_anomaly_source_revision()
RETURNS TABLE(id bigint,committed_at timestamptz)
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,analytics AS $function$
WITH latest AS MATERIALIZED (
  SELECT source.id,source.committed_at
    FROM analytics.latest_fully_published_dataset_revision() source
), pinned AS (
  INSERT INTO analytics.anomaly_source_revision(dataset_revision_id,committed_at)
  SELECT latest.id,latest.committed_at FROM latest
  ON CONFLICT(dataset_revision_id) DO NOTHING
  RETURNING dataset_revision_id,anomaly_source_revision.committed_at
)
SELECT latest.id,latest.committed_at FROM latest
$function$;

CREATE FUNCTION analytics.anomaly_operational_metrics()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin AS $function$
SELECT jsonb_build_object(
  'candidate_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate),
  'eligible_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE eligible_at<=transaction_timestamp()),
  'oldest_candidate_age_seconds',(SELECT coalesce(greatest(0,extract(epoch FROM transaction_timestamp()-min(eligible_at))),0) FROM ops_and_admin.anomaly_analysis_candidate),
  'expired_leases',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE claim_token IS NOT NULL AND leased_until<transaction_timestamp()),
  'retry_candidates',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE retry_count>0),
  'failures_last_hour',(SELECT count(*) FROM analytics.publication_analysis_attempt WHERE status='failed' AND completed_at>=transaction_timestamp()-interval '1 hour'),
  'latest_analysis_revision',(SELECT coalesce(max(id),0) FROM analytics.anomaly_analysis_revision),
  'latest_source_dataset_revision',(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state),
  'source_revision_lag',greatest(0,
      coalesce((SELECT id FROM analytics.latest_fully_published_dataset_revision()),0)
      -(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state)),
  'last_success_unixtime',(SELECT coalesce(extract(epoch FROM max(completed_at)),0) FROM analytics.publication_analysis_attempt WHERE status='succeeded')
)
$function$;

CREATE FUNCTION ops_and_admin.claim_anomaly_candidates(
    p_limit integer,p_lease_seconds integer,p_claim_token uuid
) RETURNS TABLE(publication_id uuid,dirty_generation bigint,retry_count integer,config_backfill boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ops_and_admin
SET statement_timeout='10s' AS $function$
BEGIN
    IF p_limit<1 OR p_limit>100 OR p_lease_seconds<10 OR p_lease_seconds>900 OR p_claim_token IS NULL THEN
        RAISE EXCEPTION 'invalid anomaly claim bounds';
    END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate candidate
       SET claim_token=NULL,claimed_generation=NULL,leased_until=NULL,updated_at=transaction_timestamp()
     WHERE candidate.claim_token IS NOT NULL AND candidate.leased_until<transaction_timestamp();
    RETURN QUERY
    WITH selected AS (
        SELECT candidate.publication_id
          FROM ops_and_admin.anomaly_analysis_candidate candidate
         WHERE candidate.eligible_at<=transaction_timestamp()
           AND candidate.claim_token IS NULL
         ORDER BY candidate.priority DESC,candidate.eligible_at,candidate.publication_id
         FOR UPDATE SKIP LOCKED LIMIT p_limit
    ), claimed AS (
        UPDATE ops_and_admin.anomaly_analysis_candidate candidate
           SET claim_token=p_claim_token,claimed_generation=candidate.dirty_generation,
               leased_until=transaction_timestamp()+make_interval(secs=>p_lease_seconds),
               updated_at=transaction_timestamp()
          FROM selected WHERE candidate.publication_id=selected.publication_id
        RETURNING candidate.publication_id,candidate.dirty_generation,candidate.retry_count,candidate.config_backfill
    ) SELECT * FROM claimed;
END $function$;

CREATE FUNCTION analytics.extract_publication_history_as_of(
    p_publication_ids uuid[],p_source_dataset_revision bigint,p_max_points integer
) RETURNS TABLE(
    publication_id uuid,institution_id uuid,account_id uuid,platform text,published_at timestamptz,
    deleted_at timestamptz,history_completeness text,source_revision_at timestamptz,
    snapshot_id text,observed_at timestamptz,age_seconds integer,views_count bigint,reactions_count bigint,
    comments_count bigint,shares_count bigint,views_quality text,reactions_quality text,comments_quality text,
    shares_quality text,synthetic boolean,interval_uncertain boolean,correction_sequence bigint,
    supersedes_snapshot_id text,metric_semantics_version integer,capability_version integer,
    supported_metrics text[],point_ordinal bigint,total_points bigint
) LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,catalog,ingest,analytics
SET statement_timeout='15s' AS $function$
DECLARE anchor timestamptz;
BEGIN
    IF cardinality(p_publication_ids)<1 OR cardinality(p_publication_ids)>100 OR p_max_points<1 OR p_max_points>10000 THEN
        RAISE EXCEPTION 'invalid anomaly extraction bounds';
    END IF;
    SELECT pinned.committed_at INTO anchor
      FROM analytics.anomaly_source_revision pinned
     WHERE pinned.dataset_revision_id=p_source_dataset_revision;
    IF anchor IS NULL THEN RAISE EXCEPTION 'source dataset revision is not fully published'; END IF;
    RETURN QUERY
    WITH ranked_corrections AS (
        SELECT snapshot.*,
               row_number() OVER(PARTITION BY snapshot.published_month,snapshot.publication_id,snapshot.sampling_bucket
                                 ORDER BY snapshot.correction_sequence DESC,snapshot.id DESC) AS correction_rank
          FROM ingest.publication_metric_snapshot snapshot
         WHERE snapshot.publication_id=ANY(p_publication_ids) AND snapshot.created_at<=anchor
    ), effective AS (
        SELECT snapshot.*,
               row_number() OVER(PARTITION BY snapshot.publication_id ORDER BY snapshot.observed_at,snapshot.id) AS ordinal,
               count(*) OVER(PARTITION BY snapshot.publication_id) AS points
          FROM ranked_corrections snapshot WHERE snapshot.correction_rank=1
    )
    SELECT publication.id,account.institution_id,account.id,account.platform::text,publication.published_at,
           publication.deleted_at,publication.history_completeness::text,anchor,
           effective.id::text,effective.observed_at,effective.age_seconds,
           CASE WHEN effective.views_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.views_count END,
           CASE WHEN effective.reactions_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.reactions_count END,
           CASE WHEN effective.comments_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.comments_count END,
           CASE WHEN effective.shares_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.shares_count END,
           effective.views_quality::text,effective.reactions_quality::text,effective.comments_quality::text,effective.shares_quality::text,
           effective.synthetic,effective.interval_uncertain,effective.correction_sequence,effective.supersedes_snapshot_id::text,
           effective.metric_semantics_version,effective.capability_version,
           ARRAY(SELECT capability.metric_key::text
                   FROM (SELECT DISTINCT ON (c.metric_key) c.metric_key,c.supported
                           FROM analytics.platform_metric_capability c
                          WHERE c.platform=account.platform AND c.effective_from<=anchor
                            AND (c.retired_at IS NULL OR c.retired_at>anchor)
                          ORDER BY c.metric_key,c.capability_version DESC) capability
                  WHERE capability.supported ORDER BY 1),
           effective.ordinal,effective.points
      FROM effective
      JOIN ingest.publication publication ON publication.id=effective.publication_id
      JOIN catalog.platform_account account ON account.id=publication.primary_account_id
     WHERE effective.ordinal<=p_max_points+1
     ORDER BY publication.id,effective.ordinal;
END $function$;

CREATE FUNCTION ops_and_admin.complete_anomaly_noop(
    p_publication_id uuid,p_claim_token uuid,p_generation bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ops_and_admin AS $function$
BEGIN
    DELETE FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token
       AND claimed_generation=p_generation AND dirty_generation=p_generation;
    IF FOUND THEN RETURN true; END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate SET
        claim_token=NULL,claimed_generation=NULL,leased_until=NULL,eligible_at=transaction_timestamp(),
        retry_count=0,last_error_code=NULL,updated_at=transaction_timestamp()
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation;
    RETURN FOUND;
END $function$;

CREATE FUNCTION analytics.anomaly_input_is_unchanged(
    p_publication_id uuid,p_input_hash text,p_manifest_hash text
) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,analytics AS $function$
SELECT EXISTS(
    SELECT 1 FROM analytics.publication_analysis_state state
     WHERE state.publication_id=p_publication_id
       AND state.current_success_attempt_id IS NOT NULL
       AND state.status IN ('ready','partial')
       AND state.input_hash=p_input_hash
       AND state.detector_manifest_hash=p_manifest_hash
)
$function$;

CREATE FUNCTION ops_and_admin.record_anomaly_attempt_tombstone(
    p_attempt_id uuid,p_superseded_by uuid,p_reason text
) RETURNS void LANGUAGE sql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin AS $function$
INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,before_state,outcome)
SELECT 'analytics_worker','anomaly.attempt.prune','publication_analysis_attempt',attempt.id,p_superseded_by,
       jsonb_build_object('attemptKey',attempt.attempt_key,'publicationId',attempt.publication_id,
         'status',attempt.status,'sourceDatasetRevision',attempt.source_dataset_revision_id,
         'inputHash',attempt.input_hash,'detectorManifestHash',attempt.detector_manifest_hash,
         'preprocessingVersion',attempt.preprocessing_version,'aggregatorVersion',attempt.aggregator_version,
         'errorCode',attempt.error_code,'completedAt',attempt.completed_at,'reason',p_reason),
       'pruned'
  FROM analytics.publication_analysis_attempt attempt WHERE attempt.id=p_attempt_id
$function$;

CREATE FUNCTION analytics.publish_anomaly_success(
    p_publication_id uuid,p_claim_token uuid,p_generation bigint,p_attempt_key uuid,
    p_source_revision bigint,p_input_hash text,p_manifest_hash text,p_preprocessor text,p_aggregator text,
    p_semantic_version integer,p_capability_version integer,p_started_at timestamptz,p_status text,
    p_score numeric,p_severity text,p_findings jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin
SET statement_timeout='15s' AS $function$
DECLARE attempt uuid; revision bigint; source_at timestamptz; previous_success uuid;
BEGIN
    IF p_status NOT IN ('ready','partial') OR (p_score IS NOT NULL AND (p_score<0 OR p_score>1))
       OR jsonb_typeof(p_findings)<>'array' OR jsonb_array_length(p_findings)>200 THEN
        RAISE EXCEPTION 'invalid anomaly success envelope';
    END IF;
    SELECT id INTO attempt FROM analytics.publication_analysis_attempt
     WHERE publication_id=p_publication_id AND attempt_key=p_attempt_key;
    IF FOUND THEN
        SELECT analysis_revision_id INTO revision FROM analytics.publication_analysis_attempt WHERE id=attempt;
        RETURN revision;
    END IF;
    PERFORM 1 FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'anomaly claim lost' USING ERRCODE='55000'; END IF;
    SELECT committed_at INTO source_at FROM analytics.anomaly_source_revision WHERE dataset_revision_id=p_source_revision;
    IF source_at IS NULL THEN RAISE EXCEPTION 'source revision was not pinned as fully published'; END IF;
    INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason)
      VALUES(p_publication_id,'automatic_success') RETURNING id INTO revision;
    INSERT INTO analytics.publication_analysis_attempt(
      publication_id,attempt_key,status,claimed_generation,source_dataset_revision_id,source_revision_at,input_hash,
      detector_manifest_hash,preprocessing_version,aggregator_version,metric_semantics_version,capability_version,
      started_at,analysis_revision_id
    ) VALUES(p_publication_id,p_attempt_key,'succeeded',p_generation,p_source_revision,source_at,p_input_hash,
      p_manifest_hash,p_preprocessor,p_aggregator,p_semantic_version,p_capability_version,p_started_at,revision)
      RETURNING id INTO attempt;
    INSERT INTO analytics.publication_anomaly_finding(
      id,finding_key,publication_id,attempt_id,created_analysis_revision_id,origin,metric,detector_id,detector_version,
      suspicion_score,severity,explanation_code,suspicious_start_at,suspicious_end_at,start_snapshot_id,end_snapshot_id,
      evidence,quality_codes,alternative_explanation_codes
    ) SELECT md5(attempt::text||':'||keyed.finding_key::text)::uuid,keyed.finding_key,p_publication_id,attempt,revision,
      'automatic',keyed.metric::analytics.metric_key,
      keyed.detector_id,keyed.detector_version,keyed.score,keyed.severity,keyed.explanation_code,
      keyed.start_at,keyed.end_at,keyed.start_snapshot_id,keyed.end_snapshot_id,
      keyed.evidence,coalesce(keyed.quality_codes,ARRAY[]::text[]),coalesce(keyed.alternative_codes,ARRAY[]::text[])
      FROM (
        SELECT finding.*,
               md5(p_publication_id::text||':automatic:'||finding.metric||':'||finding.detector_id||':'
                   ||finding.detector_version||':'||coalesce(finding.start_snapshot_id,'')||':'
                   ||coalesce(finding.end_snapshot_id,''))::uuid AS finding_key
          FROM jsonb_to_recordset(p_findings) AS finding(
            metric text,detector_id text,detector_version text,score numeric,severity text,explanation_code text,
            start_at timestamptz,end_at timestamptz,start_snapshot_id text,end_snapshot_id text,evidence jsonb,
            quality_codes text[],alternative_codes text[])
      ) keyed;
    SELECT current_success_attempt_id INTO previous_success
      FROM analytics.publication_analysis_state WHERE publication_id=p_publication_id FOR UPDATE;
    INSERT INTO analytics.publication_analysis_state(
      publication_id,analysis_revision_id,current_success_attempt_id,status,suspicion_score,automatic_severity,
      affected_metrics,active_automatic_finding_count,source_dataset_revision_id,source_revision_at,analyzed_at,
      input_hash,detector_manifest_hash,preprocessing_version,aggregator_version
    ) SELECT p_publication_id,revision,attempt,p_status,p_score,p_severity,
      coalesce(array_agg(DISTINCT (item->>'metric')::analytics.metric_key) FILTER(WHERE item ? 'metric'),ARRAY[]::analytics.metric_key[]),
      jsonb_array_length(p_findings),p_source_revision,source_at,transaction_timestamp(),p_input_hash,p_manifest_hash,p_preprocessor,p_aggregator
      FROM jsonb_array_elements(p_findings) item
    ON CONFLICT(publication_id) DO UPDATE SET
      analysis_revision_id=excluded.analysis_revision_id,current_success_attempt_id=excluded.current_success_attempt_id,
      status=excluded.status,suspicion_score=excluded.suspicion_score,automatic_severity=excluded.automatic_severity,
      affected_metrics=excluded.affected_metrics,active_automatic_finding_count=excluded.active_automatic_finding_count,
      source_dataset_revision_id=excluded.source_dataset_revision_id,source_revision_at=excluded.source_revision_at,
      analyzed_at=excluded.analyzed_at,input_hash=excluded.input_hash,detector_manifest_hash=excluded.detector_manifest_hash,
      preprocessing_version=excluded.preprocessing_version,aggregator_version=excluded.aggregator_version;
    IF previous_success IS NOT NULL AND previous_success<>attempt THEN
        -- Two-slot retention: the superseded generated payload is removed after the
        -- pointer switch; the audit log keeps only safe attempt metadata.
        PERFORM ops_and_admin.record_anomaly_attempt_tombstone(previous_success,attempt,'superseded_by_success');
        DELETE FROM analytics.publication_analysis_attempt WHERE id=previous_success;
    END IF;
    PERFORM ops_and_admin.complete_anomaly_noop(p_publication_id,p_claim_token,p_generation);
    RETURN revision;
END $function$;

CREATE FUNCTION analytics.publish_anomaly_failure(
    p_publication_id uuid,p_claim_token uuid,p_generation bigint,p_attempt_key uuid,p_source_revision bigint,
    p_manifest_hash text,p_preprocessor text,p_aggregator text,p_semantic_version integer,p_capability_version integer,
    p_started_at timestamptz,p_error_code text,p_retry_seconds integer
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin
SET statement_timeout='15s' AS $function$
DECLARE attempt uuid; revision bigint; source_at timestamptz; previous_failure uuid; has_success boolean;
BEGIN
    IF p_error_code !~ '^[a-z0-9_]{1,64}$' OR p_retry_seconds<1 OR p_retry_seconds>86400 THEN
       RAISE EXCEPTION 'invalid anomaly failure envelope'; END IF;
    SELECT id INTO attempt FROM analytics.publication_analysis_attempt
     WHERE publication_id=p_publication_id AND attempt_key=p_attempt_key;
    IF FOUND THEN SELECT analysis_revision_id INTO revision FROM analytics.publication_analysis_attempt WHERE id=attempt; RETURN revision; END IF;
    PERFORM 1 FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'anomaly claim lost' USING ERRCODE='55000'; END IF;
    SELECT committed_at INTO source_at FROM analytics.anomaly_source_revision WHERE dataset_revision_id=p_source_revision;
    IF source_at IS NULL THEN RAISE EXCEPTION 'source revision was not pinned as fully published'; END IF;
    SELECT latest_failure_attempt_id,current_success_attempt_id IS NOT NULL INTO previous_failure,has_success
      FROM analytics.publication_analysis_state WHERE publication_id=p_publication_id FOR UPDATE;
    INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason)
      VALUES(p_publication_id,'automatic_failure') RETURNING id INTO revision;
    INSERT INTO analytics.publication_analysis_attempt(
      publication_id,attempt_key,status,claimed_generation,source_dataset_revision_id,source_revision_at,
      detector_manifest_hash,preprocessing_version,aggregator_version,metric_semantics_version,capability_version,
      started_at,error_code,analysis_revision_id
    ) VALUES(p_publication_id,p_attempt_key,'failed',p_generation,p_source_revision,source_at,p_manifest_hash,
      p_preprocessor,p_aggregator,p_semantic_version,p_capability_version,p_started_at,p_error_code,revision)
      RETURNING id INTO attempt;
    INSERT INTO analytics.publication_analysis_state(publication_id,analysis_revision_id,latest_failure_attempt_id,status)
      VALUES(p_publication_id,revision,attempt,CASE WHEN has_success THEN 'stale' ELSE 'failed' END)
    ON CONFLICT(publication_id) DO UPDATE SET analysis_revision_id=excluded.analysis_revision_id,
      latest_failure_attempt_id=excluded.latest_failure_attempt_id,status=excluded.status;
    IF previous_failure IS NOT NULL AND previous_failure<>attempt THEN
      PERFORM ops_and_admin.record_anomaly_attempt_tombstone(previous_failure,attempt,'superseded_by_failure');
      DELETE FROM analytics.publication_analysis_attempt WHERE id=previous_failure;
    END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate SET claim_token=NULL,claimed_generation=NULL,leased_until=NULL,
      retry_count=least(retry_count+1,20),last_error_code=p_error_code,
      eligible_at=transaction_timestamp()+make_interval(secs=>p_retry_seconds),updated_at=transaction_timestamp()
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation;
    RETURN revision;
END $function$;

CREATE VIEW analytics.publication_anomaly_finding_public AS
WITH effective AS (
 SELECT finding.*,(SELECT review.decision FROM analytics.publication_anomaly_review review
                    WHERE review.publication_id=finding.publication_id AND review.finding_key=finding.finding_key
                    ORDER BY review.reviewed_at DESC,review.id DESC LIMIT 1) AS review_state
 FROM analytics.publication_anomaly_finding finding
), current_findings AS (
 SELECT effective.* FROM effective
 LEFT JOIN analytics.publication_analysis_state state ON state.publication_id=effective.publication_id
 WHERE (effective.origin='automatic' AND effective.attempt_id=state.current_success_attempt_id)
    OR effective.origin='manual'
)
SELECT id,publication_id,origin,metric,detector_id,detector_version,suspicion_score,severity,explanation_code,
 suspicious_start_at,suspicious_end_at,start_snapshot_id,end_snapshot_id,evidence,quality_codes,
 alternative_explanation_codes,coalesce(review_state::text,'unreviewed') AS review_state,
 review_state IS DISTINCT FROM 'dismissed'::analytics.review_decision
 AND review_state IS DISTINCT FROM 'data_error'::analytics.review_decision AS active
FROM current_findings;

CREATE VIEW analytics.publication_analysis_state_public AS
SELECT publication_id,analysis_revision_id,status,suspicion_score,automatic_severity,
       affected_metrics,active_automatic_finding_count,source_dataset_revision_id,
       source_revision_at,analyzed_at
  FROM analytics.publication_analysis_state;

CREATE FUNCTION analytics.create_manual_anomaly_signal(
 p_publication_id uuid,p_metric text,p_severity text,p_explanation_code text,p_start_at timestamptz,p_end_at timestamptz,
 p_evidence jsonb,p_subject text,p_correlation_id uuid,p_idempotency_key uuid,p_request_digest text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin AS $function$
DECLARE existing ops_and_admin.anomaly_command_receipt%ROWTYPE; finding uuid; revision bigint; result jsonb;
BEGIN
 SELECT * INTO existing FROM ops_and_admin.anomaly_command_receipt WHERE subject=p_subject AND command_type='manual_signal' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF existing.request_digest<>p_request_digest THEN RAISE EXCEPTION 'idempotency digest conflict' USING ERRCODE='23505'; END IF;
   RETURN existing.result;
 END IF;
 IF p_metric NOT IN ('views','reactions','comments','shares') OR p_severity NOT IN ('low','medium','high')
    OR p_explanation_code !~ '^[a-z0-9_]{1,80}$' OR p_end_at<=p_start_at OR pg_column_size(p_evidence)>8192 THEN
   RAISE EXCEPTION 'invalid manual anomaly signal'; END IF;
 finding:=gen_random_uuid();
 INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason) VALUES(p_publication_id,'manual_signal') RETURNING id INTO revision;
 INSERT INTO analytics.publication_anomaly_finding(id,finding_key,publication_id,created_analysis_revision_id,origin,metric,severity,
   explanation_code,suspicious_start_at,suspicious_end_at,evidence)
 VALUES(finding,finding,p_publication_id,revision,'manual',p_metric::analytics.metric_key,p_severity,p_explanation_code,p_start_at,p_end_at,p_evidence);
 INSERT INTO analytics.publication_analysis_state(publication_id,analysis_revision_id,status)
 VALUES(p_publication_id,revision,'pending') ON CONFLICT(publication_id) DO UPDATE SET analysis_revision_id=excluded.analysis_revision_id;
 result:=jsonb_build_object('findingId',finding,'analysisRevision',revision);
 INSERT INTO ops_and_admin.anomaly_command_receipt VALUES(p_subject,'manual_signal',p_idempotency_key,p_request_digest,result,transaction_timestamp());
 INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,after_state,outcome)
 VALUES(p_subject,'anomaly.manual_signal.create','publication_anomaly_finding',finding,p_correlation_id,
        jsonb_build_object('publicationId',p_publication_id,'metric',p_metric,'severity',p_severity),'succeeded');
 RETURN result;
END $function$;

CREATE FUNCTION analytics.append_anomaly_review(
 p_finding_id uuid,p_decision text,p_private_comment text,p_subject text,p_correlation_id uuid,
 p_idempotency_key uuid,p_request_digest text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,analytics,ops_and_admin AS $function$
DECLARE existing ops_and_admin.anomaly_command_receipt%ROWTYPE; publication uuid; key uuid; review uuid; revision bigint; result jsonb;
BEGIN
 SELECT * INTO existing FROM ops_and_admin.anomaly_command_receipt WHERE subject=p_subject AND command_type='review' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF existing.request_digest<>p_request_digest THEN RAISE EXCEPTION 'idempotency digest conflict' USING ERRCODE='23505'; END IF;
   RETURN existing.result;
 END IF;
 IF p_decision NOT IN ('explained','unresolved','data_error','dismissed') OR length(coalesce(p_private_comment,''))>2000 THEN
   RAISE EXCEPTION 'invalid anomaly review'; END IF;
 SELECT publication_id,finding_key INTO publication,key FROM analytics.publication_anomaly_finding WHERE id=p_finding_id;
 IF publication IS NULL THEN RAISE EXCEPTION 'anomaly finding not found' USING ERRCODE='P0002'; END IF;
 review:=gen_random_uuid();
 INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason) VALUES(publication,'review') RETURNING id INTO revision;
 INSERT INTO analytics.publication_anomaly_review(id,publication_id,finding_key,finding_id,analysis_revision_id,reviewer_subject,decision,private_comment)
 VALUES(review,publication,key,p_finding_id,revision,p_subject,p_decision::analytics.review_decision,p_private_comment);
 UPDATE analytics.publication_analysis_state SET analysis_revision_id=revision WHERE publication_id=publication;
 result:=jsonb_build_object('reviewId',review,'findingId',p_finding_id,'analysisRevision',revision,'decision',p_decision);
 INSERT INTO ops_and_admin.anomaly_command_receipt VALUES(p_subject,'review',p_idempotency_key,p_request_digest,result,transaction_timestamp());
 INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,after_state,outcome)
 VALUES(p_subject,'anomaly.review.append','publication_anomaly_finding',p_finding_id,p_correlation_id,
        jsonb_build_object('decision',p_decision),'succeeded');
 RETURN result;
END $function$;

INSERT INTO analytics.metric_semantic_definition(metric_key,version,unit,metric_kind,aggregation_policy,reset_policy,missing_policy,effective_from,source_hash)
SELECT metric::analytics.metric_key,1,'count','cumulative',
       '{"derivative":"time_normalized"}'::jsonb,'{"negative":"break_segment","suspected_reset":"mask"}'::jsonb,
       '{"null":"unavailable","zero":"measured"}'::jsonb,'2026-09-08T00:00:00Z'::timestamptz,
       source_hash
FROM (VALUES
 ('views','2cd498c42d6538a8d2e6a3ad5f477b604ad5c48ffa7a0fc31aa497e5e3ccbff7'),
 ('reactions','b531bfc56188283edfa9fd28f464727ebad8bd5024317a8a7df718001db3c515'),
 ('comments','2b3badea72204712fe3c7e7b5534e81dd92f3b473331f813b9e597833c04dc1a'),
 ('shares','4d6830cfffae526fe3f53b73ebaefd9b598dad62a9137931d2a43ae2feb467bd')
) semantic(metric,source_hash)
ON CONFLICT(metric_key,version) DO NOTHING;

INSERT INTO analytics.platform_metric_capability(platform,metric_key,capability_version,semantic_version,supported,notes,effective_from)
SELECT platform::catalog.platform_code,metric::analytics.metric_key,1,1,supported,notes,'2026-09-08T00:00:00Z'::timestamptz
FROM (VALUES
 ('telegram','views',true,NULL),('telegram','reactions',true,NULL),('telegram','comments',true,'available when discussion access exposes the counter'),('telegram','shares',false,'provider does not expose publication shares'),
 ('vk','views',true,NULL),('vk','reactions',true,NULL),('vk','comments',true,NULL),('vk','shares',true,NULL),
 ('max','views',true,NULL),('max','reactions',true,NULL),('max','comments',true,'nullable when discussion counter is unavailable'),('max','shares',true,'nullable when provider omits repost count'),
 ('rutube','views',true,NULL),('rutube','reactions',true,NULL),('rutube','comments',true,NULL),('rutube','shares',false,'public API does not expose publication shares')
) capability(platform,metric,supported,notes)
ON CONFLICT(platform,metric_key,capability_version) DO NOTHING;

REVOKE ALL ON FUNCTION ops_and_admin.mark_anomaly_candidate(),ops_and_admin.seed_anomaly_backfill(integer,text),
 ops_and_admin.record_anomaly_attempt_tombstone(uuid,uuid,text),
 analytics.latest_fully_published_dataset_revision(),ops_and_admin.pin_latest_anomaly_source_revision(),
 ops_and_admin.claim_anomaly_candidates(integer,integer,uuid),
 analytics.anomaly_operational_metrics(),
 analytics.extract_publication_history_as_of(uuid[],bigint,integer),ops_and_admin.complete_anomaly_noop(uuid,uuid,bigint),
 analytics.anomaly_input_is_unchanged(uuid,text,text),
 analytics.publish_anomaly_success(uuid,uuid,bigint,uuid,bigint,text,text,text,text,integer,integer,timestamptz,text,numeric,text,jsonb),
 analytics.publish_anomaly_failure(uuid,uuid,bigint,uuid,bigint,text,text,text,integer,integer,timestamptz,text,integer),
 analytics.create_manual_anomaly_signal(uuid,text,text,text,timestamptz,timestamptz,jsonb,text,uuid,uuid,text),
 analytics.append_anomaly_review(uuid,text,text,text,uuid,uuid,text) FROM PUBLIC;

GRANT USAGE ON SCHEMA analytics TO api_read;
GRANT SELECT ON analytics.publication_analysis_state_public,analytics.publication_anomaly_finding_public TO api_read;

GRANT USAGE ON SCHEMA analytics,ops_and_admin TO api_write_admin;
GRANT EXECUTE ON FUNCTION analytics.create_manual_anomaly_signal(uuid,text,text,text,timestamptz,timestamptz,jsonb,text,uuid,uuid,text),
 analytics.append_anomaly_review(uuid,text,text,text,uuid,uuid,text) TO api_write_admin;

GRANT USAGE ON SCHEMA catalog,ingest,analytics,ops_and_admin TO analytics_worker;
GRANT EXECUTE ON FUNCTION analytics.latest_fully_published_dataset_revision(),
 ops_and_admin.pin_latest_anomaly_source_revision(),
 analytics.anomaly_operational_metrics(),
 ops_and_admin.claim_anomaly_candidates(integer,integer,uuid),
 analytics.extract_publication_history_as_of(uuid[],bigint,integer),
 analytics.anomaly_input_is_unchanged(uuid,text,text),
 ops_and_admin.complete_anomaly_noop(uuid,uuid,bigint),
 ops_and_admin.seed_anomaly_backfill(integer,text),
 analytics.publish_anomaly_success(uuid,uuid,bigint,uuid,bigint,text,text,text,text,integer,integer,timestamptz,text,numeric,text,jsonb),
 analytics.publish_anomaly_failure(uuid,uuid,bigint,uuid,bigint,text,text,text,integer,integer,timestamptz,text,integer)
TO analytics_worker;

GRANT EXECUTE ON FUNCTION analytics.anomaly_operational_metrics() TO maintenance;

REVOKE ALL ON ingest.publication_metric_snapshot,ingest.publication,analytics.projection_state,
 analytics.dataset_revision,analytics.anomaly_source_revision,analytics.publication_analysis_attempt,analytics.publication_analysis_state,
 analytics.publication_anomaly_finding,analytics.publication_anomaly_review,
 ops_and_admin.anomaly_analysis_candidate FROM analytics_worker;

RESET ROLE;

SET ROLE migration_owner;

CREATE OR REPLACE VIEW ops_and_admin.schema_contract AS
SELECT 'storage-publisher-final-2026-09-08-r3'::text AS contract_id;

COMMENT ON VIEW ops_and_admin.schema_contract IS
'Single runtime database contract. Services validate this identifier; historical migration metadata is not a runtime input.';

REVOKE ALL ON ops_and_admin.schema_contract FROM PUBLIC;
GRANT SELECT ON ops_and_admin.schema_contract
    TO api_read, api_write_admin, collector_ingest, maintenance;

RESET ROLE;
-- r3-delta:end

COMMIT;
