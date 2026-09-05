\set ON_ERROR_STOP on

-- Run as the local bootstrap role after Flyway has applied V1 through V8. The script is
-- read-only except for a transaction that is always rolled back.

DO $assertions$
DECLARE
    missing_schemas text[];
    missing_relations text[];
    role_name text;
BEGIN
    IF current_setting('server_version_num')::integer <> 180006 THEN
        RAISE EXCEPTION 'expected PostgreSQL 18.6 (180006), got % (%)',
            current_setting('server_version'), current_setting('server_version_num');
    END IF;

    SELECT array_agg(required.name ORDER BY required.name)
      INTO missing_schemas
      FROM (VALUES
          ('catalog'), ('ingest'), ('analytics'), ('rating'),
          ('ops_and_admin'), ('migration'), ('flyway')
      ) AS required(name)
     WHERE to_regnamespace(required.name) IS NULL;
    IF missing_schemas IS NOT NULL THEN
        RAISE EXCEPTION 'missing schemas: %', missing_schemas;
    END IF;

    SELECT array_agg(required.name ORDER BY required.name)
      INTO missing_relations
      FROM (VALUES
          ('catalog.institution'),
          ('catalog.platform_account'),
          ('catalog.account_external_identity'),
          ('catalog.legacy_entity_alias'),
          ('ingest.collection_run'),
          ('ingest.publication'),
          ('ingest.publication_metric_snapshot'),
          ('ingest.publication_metric_snapshot_default'),
          ('ingest.reaction_breakdown_default'),
          ('analytics.dataset_revision'),
          ('analytics.publication_latest'),
          ('analytics.publication_hourly'),
          ('analytics.institution_daily_metrics'),
          ('analytics.institution_monthly_metrics'),
          ('analytics.institution_period_metrics'),
          ('analytics.comparison_publication_hourly'),
          ('analytics.legacy_overview_card'),
          ('analytics.legacy_overview_account'),
          ('ops_and_admin.outbox_event'),
          ('ops_and_admin.operational_checkpoint'),
          ('ops_and_admin.recovery_policy'),
          ('migration.import_batch'),
          ('migration.legacy_identity_map'),
          ('migration.checkpoint'),
          ('migration.legacy_evidence'),
          ('migration.reconciliation_result')
      ) AS required(name)
     WHERE to_regclass(required.name) IS NULL;
    IF missing_relations IS NOT NULL THEN
        RAISE EXCEPTION 'missing relations: %', missing_relations;
    END IF;

    FOREACH role_name IN ARRAY ARRAY[
        'migration_owner', 'api_read', 'api_write_admin', 'collector_ingest',
        'backup', 'migration_bridge', 'maintenance'
    ] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            RAISE EXCEPTION 'missing database role: %', role_name;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM pg_roles
         WHERE rolname IN (
             'migration_owner', 'api_read', 'api_write_admin', 'collector_ingest',
             'migration_bridge', 'maintenance'
         )
           AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication)
    ) THEN
        RAISE EXCEPTION 'an application role has elevated cluster privileges';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'ingest'
           AND c.relname = 'publication_metric_snapshot'
           AND c.relkind = 'p'
    ) THEN
        RAISE EXCEPTION 'publication_metric_snapshot is not partitioned';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'ingest'
           AND c.relname = 'publication_metric_snapshot'
           AND a.attname = 'comments_count'
           AND NOT a.attnotnull
           AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'comments_count must stay nullable, including for MAX';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'analytics'
           AND c.relname = 'institution_period_metrics'
           AND a.attname = 'platform'
           AND NOT a.attnotnull
           AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'institution_period_metrics.platform must be nullable for platform=all';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'analytics'
           AND c.relname = 'publication_hourly'
           AND a.attname = 'hour_offset'
           AND a.attnotnull
           AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'publication_hourly must expose a non-null publication-relative hour_offset';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'ingest'
           AND c.relname = 'collection_run'
           AND a.attname = 'scheduled_at'
           AND a.attnotnull
           AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'collection_run.scheduled_at must be present and non-null';
    END IF;

    IF EXISTS (
        SELECT required.relation
          FROM (VALUES
              ('ingest.account_metric_snapshot'::regclass),
              ('ingest.publication_metric_snapshot'::regclass)
          ) AS required(relation)
         WHERE NOT EXISTS (
             SELECT 1
               FROM pg_attribute a
              WHERE a.attrelid = required.relation
                AND a.attname = 'collected_at'
                AND a.attnotnull
                AND NOT a.attisdropped
         )
    ) THEN
        RAISE EXCEPTION 'snapshot collected_at columns must be present and non-null';
    END IF;

    IF (SELECT hot_days FROM ops_and_admin.retention_policy
         WHERE data_class = 'publication_metric_snapshot') < 70 THEN
        RAISE EXCEPTION 'publication hot retention is below the 70-day parity floor';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM ops_and_admin.recovery_policy
         WHERE policy_name = 'primary'
           AND target_rpo = interval '15 minutes'
           AND target_rto = interval '2 hours'
           AND daily_base_backup_points = 14
           AND weekly_backup_points = 8
           AND monthly_backup_points = 12
           AND encrypted_off_primary_copy_required
    ) THEN
        RAISE EXCEPTION 'RPO/RTO or backup retention policy drifted';
    END IF;

    IF has_schema_privilege('collector_ingest', 'ingest', 'CREATE') THEN
        RAISE EXCEPTION 'collector_ingest must not own DDL';
    END IF;
    IF NOT has_table_privilege('collector_ingest', 'ingest.publication_metric_snapshot', 'INSERT') THEN
        RAISE EXCEPTION 'collector_ingest cannot append publication snapshots';
    END IF;
    IF has_table_privilege('collector_ingest', 'ingest.publication_metric_snapshot', 'UPDATE')
       OR has_table_privilege('collector_ingest', 'ingest.publication_metric_snapshot', 'DELETE') THEN
        RAISE EXCEPTION 'collector_ingest can mutate append-only publication snapshots';
    END IF;
    IF NOT has_table_privilege(
        'collector_ingest', 'catalog.account_identity_history', 'INSERT'
    ) OR NOT has_table_privilege(
        'collector_ingest', 'catalog.account_external_identity', 'INSERT'
    ) OR NOT has_sequence_privilege(
        'collector_ingest', 'catalog.account_identity_history_id_seq', 'USAGE'
    ) OR NOT has_sequence_privilege(
        'collector_ingest', 'catalog.account_external_identity_id_seq', 'USAGE'
    ) THEN
        RAISE EXCEPTION 'collector_ingest is missing required identity append privileges';
    END IF;
    IF NOT has_column_privilege(
        'collector_ingest', 'catalog.account_identity_history', 'valid_to', 'UPDATE'
    ) OR NOT has_column_privilege(
        'collector_ingest', 'catalog.account_external_identity', 'valid_to', 'UPDATE'
    ) OR NOT has_column_privilege(
        'collector_ingest', 'catalog.platform_account', 'current_title', 'UPDATE'
    ) THEN
        RAISE EXCEPTION 'collector_ingest is missing required narrow identity update privileges';
    END IF;
    IF has_table_privilege(
        'collector_ingest', 'catalog.platform_account', 'UPDATE'
    ) OR has_column_privilege(
        'collector_ingest', 'catalog.platform_account', 'institution_id', 'UPDATE'
    ) OR has_column_privilege(
        'collector_ingest', 'catalog.platform_account', 'enabled', 'UPDATE'
    ) THEN
        RAISE EXCEPTION 'collector_ingest can mutate administrative account fields';
    END IF;
    IF has_table_privilege('api_read', 'ingest.raw_payload', 'SELECT') THEN
        RAISE EXCEPTION 'api_read can read restricted raw payload';
    END IF;
    IF has_table_privilege('api_read', 'ingest.collection_run', 'SELECT')
       OR has_table_privilege('api_read', 'ingest.collection_account_result', 'SELECT') THEN
        RAISE EXCEPTION 'api_read can inspect administrative collection run status';
    END IF;
    IF has_table_privilege(
        'api_read', 'ingest.publication_metric_snapshot', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'api_read can bypass projections and scan raw publication snapshots';
    END IF;
    IF NOT has_table_privilege(
        'api_read', 'analytics.comparison_publication_hourly', 'SELECT'
    ) OR NOT has_table_privilege(
        'api_read', 'analytics.legacy_overview_card', 'SELECT'
    ) OR NOT has_table_privilege(
        'api_read', 'analytics.legacy_overview_account', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'api_read is missing a V6/V8 materialized read model';
    END IF;
    IF has_table_privilege('api_read', 'ops_and_admin.audit_log', 'SELECT') THEN
        RAISE EXCEPTION 'api_read can read administrative audit rows';
    END IF;
    IF has_schema_privilege('api_read', 'migration', 'USAGE') THEN
        RAISE EXCEPTION 'api_read can access migration evidence';
    END IF;
    IF NOT has_schema_privilege('api_write_admin', 'ingest', 'USAGE')
       OR NOT has_table_privilege('api_write_admin', 'ingest.collection_run', 'SELECT')
       OR NOT has_table_privilege(
           'api_write_admin', 'ingest.collection_account_result', 'SELECT'
       ) THEN
        RAISE EXCEPTION 'api_write_admin is missing narrow collection run-status reads';
    END IF;
    IF NOT has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections(bigint)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'api_write_admin cannot atomically publish configuration projections';
    END IF;
    IF has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'migration_bridge', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'maintenance', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections_v5(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'migration_bridge', 'analytics.rebuild_core_projections_v5(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'maintenance', 'analytics.rebuild_core_projections_v5(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections_v6(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'migration_bridge', 'analytics.rebuild_core_projections_v6(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'maintenance', 'analytics.rebuild_core_projections_v6(bigint)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'a runtime role can bypass the current V8 projection wrapper';
    END IF;
    IF has_table_privilege('api_write_admin', 'ingest.raw_payload', 'SELECT')
       OR has_table_privilege(
           'api_write_admin', 'ingest.publication_metric_snapshot', 'SELECT'
       ) OR has_table_privilege('api_write_admin', 'ingest.deletion_observation', 'SELECT') THEN
        RAISE EXCEPTION 'api_write_admin can inspect restricted ingestion evidence';
    END IF;
    IF has_schema_privilege('migration_bridge', 'ingest', 'CREATE') THEN
        RAISE EXCEPTION 'migration_bridge must not own DDL';
    END IF;
    IF NOT has_table_privilege(
        'migration_bridge', 'ingest.account_metric_snapshot', 'UPDATE'
    ) OR NOT has_table_privilege(
        'migration_bridge', 'analytics.projection_state', 'INSERT'
    ) OR NOT has_table_privilege(
        'migration_bridge', 'analytics.projection_state', 'UPDATE'
    ) OR NOT has_table_privilege(
        'migration_bridge', 'ingest.publication_metric_snapshot_default', 'SELECT'
    ) OR NOT has_table_privilege(
        'migration_bridge', 'ingest.reaction_breakdown_default', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'migration_bridge is missing a required import/reconciliation privilege';
    END IF;
END
$assertions$;

BEGIN;
SET LOCAL ROLE migration_bridge;

SELECT
    gen_random_uuid() AS institution_id,
    gen_random_uuid() AS account_id,
    gen_random_uuid() AS run_id,
    gen_random_uuid() AS publication_id,
    gen_random_uuid() AS comparison_publication_id,
    gen_random_uuid() AS revision_correlation_id
\gset smoke_

INSERT INTO catalog.institution (id, canonical_name, short_name)
VALUES (:'smoke_institution_id', 'Schema smoke university', 'Smoke');

INSERT INTO catalog.platform_account (
    id, institution_id, platform, canonical_external_id, current_title,
    current_url, access_mode
)
VALUES (
    :'smoke_account_id', :'smoke_institution_id', 'max', 'schema-smoke-max',
    'Schema smoke MAX', 'https://max.ru/schema-smoke-max', 'user_session'
);

INSERT INTO ingest.collection_run (
    id, platform, partition_key, collector_version, started_at, status,
    correlation_id
)
VALUES (
    :'smoke_run_id', 'max', 'smoke', 'schema-smoke', now(), 'running',
    :'smoke_revision_correlation_id'
);

INSERT INTO ingest.account_metric_snapshot (
    id, platform_account_id, collection_run_id, observed_at,
    subscriber_count, subscriber_display, quality, source_fingerprint
)
VALUES (
    900000000000000010, :'smoke_account_id', :'smoke_run_id', now(),
    100, '100', 'exact', repeat('e', 64)
)
ON CONFLICT (id) DO UPDATE SET
    subscriber_count = excluded.subscriber_count,
    subscriber_display = excluded.subscriber_display;

INSERT INTO ingest.account_metric_snapshot (
    id, platform_account_id, collection_run_id, observed_at,
    subscriber_count, subscriber_display, quality, source_fingerprint
)
VALUES (
    900000000000000010, :'smoke_account_id', :'smoke_run_id', now(),
    101, '101', 'exact', repeat('e', 64)
)
ON CONFLICT (id) DO UPDATE SET
    subscriber_count = excluded.subscriber_count,
    subscriber_display = excluded.subscriber_display;

INSERT INTO ingest.publication (
    id, primary_account_id, published_at, discovered_at,
    first_observation_age_seconds, publication_type, history_completeness,
    synthetic_baseline_allowed, quality_flags
)
VALUES (
    :'smoke_publication_id', :'smoke_account_id', now() - interval '1 hour',
    now() - interval '59 minutes', 60, 'post', 'complete', true,
    '{"album_ambiguity": false}'::jsonb
);

INSERT INTO ingest.publication (
    id, primary_account_id, published_at, discovered_at,
    first_observation_age_seconds, publication_type, history_completeness,
    synthetic_baseline_allowed, quality_flags
)
VALUES (
    :'smoke_comparison_publication_id', :'smoke_account_id', now() - interval '25 hours',
    now() - interval '25 hours', 0, 'post', 'complete', true,
    '{"synthetic_baseline_source": "legacy"}'::jsonb
);

INSERT INTO analytics.dataset_revision (cause, correlation_id, source_run_id)
VALUES ('migration', :'smoke_revision_correlation_id', :'smoke_run_id')
RETURNING id AS revision_id
\gset smoke_

SELECT ops_and_admin.ensure_publication_metric_partition(
    date_trunc('month', (now() - interval '1 hour') AT TIME ZONE 'UTC')::date
);
SELECT ops_and_admin.ensure_publication_metric_partition(
    date_trunc('month', (now() - interval '25 hours') AT TIME ZONE 'UTC')::date
);

INSERT INTO ingest.publication_metric_snapshot (
    published_month, id, publication_id, collection_run_id, observed_at,
    age_seconds, sampling_bucket, views_count, reactions_count, comments_count,
    shares_count, quality, source_fingerprint
)
VALUES (
    date_trunc('month', (now() - interval '1 hour') AT TIME ZONE 'UTC')::date,
    900000000000000000, :'smoke_publication_id', :'smoke_run_id', now(),
    3600, extract(epoch FROM now())::bigint / 300, 10, 2, NULL, NULL,
    'exact', repeat('a', 64)
);

INSERT INTO ingest.publication_metric_snapshot (
    published_month, id, publication_id, collection_run_id, observed_at,
    age_seconds, sampling_bucket, views_count, reactions_count, comments_count,
    shares_count, quality, synthetic, source_fingerprint
)
VALUES
(
    date_trunc('month', (now() - interval '25 hours') AT TIME ZONE 'UTC')::date,
    900000000000000001, :'smoke_comparison_publication_id', :'smoke_run_id',
    now() - interval '25 hours', 0, -900000000000000001,
    0, 0, NULL, 0, 'exact', true, repeat('b', 64)
),
(
    date_trunc('month', (now() - interval '25 hours') AT TIME ZONE 'UTC')::date,
    900000000000000002, :'smoke_comparison_publication_id', :'smoke_run_id',
    now() - interval '1 hour', 86400, 288,
    100, 20, NULL, 5, 'exact', false, repeat('c', 64)
);

INSERT INTO catalog.legacy_entity_alias (entity_type, legacy_id, target_uuid)
VALUES ('platform_posts', 900000000000000000, :'smoke_publication_id');

SELECT analytics.rebuild_core_projections(:'smoke_revision_id');
SELECT analytics.rebuild_core_projections(:'smoke_revision_id');

INSERT INTO ops_and_admin.operational_checkpoint (
    checkpoint_key, scope_type, scope_id, platform, value
)
VALUES ('smoke_state', 'system', NULL, NULL, '{"pass": 1}'::jsonb)
ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
DO UPDATE SET value = excluded.value, updated_at = transaction_timestamp();

INSERT INTO ops_and_admin.operational_checkpoint (
    checkpoint_key, scope_type, scope_id, platform, value
)
VALUES ('smoke_state', 'system', NULL, NULL, '{"pass": 2}'::jsonb)
ON CONFLICT (checkpoint_key, scope_type, scope_id, platform)
DO UPDATE SET value = excluded.value, updated_at = transaction_timestamp();

INSERT INTO migration.import_batch (
    source_name, source_file_name, source_size_bytes, source_sha256,
    source_schema_version, snapshot_kind, tool_version, status, dry_run
)
VALUES
    ('smoke-a', 'same.sqlite3', 1, repeat('d', 64), 15, 'fixture', 'smoke', 'dry_run', true),
    ('smoke-b', 'same.sqlite3', 1, repeat('d', 64), 15, 'fixture', 'smoke', 'dry_run', true);

-- Assertions below intentionally run as the owner after all importer writes,
-- conflict inference and the SECURITY DEFINER rebuild have run as the bridge.
SET LOCAL ROLE migration_owner;

DO $data_assertion$
DECLARE
    smoke_revision bigint;
    smoke_institution uuid;
BEGIN
    SELECT latest.dataset_revision_id, latest.institution_id
      INTO STRICT smoke_revision, smoke_institution
      FROM analytics.publication_latest AS latest
      JOIN catalog.legacy_entity_alias AS alias
        ON alias.target_uuid = latest.publication_id
       AND alias.entity_type = 'platform_posts'
       AND alias.legacy_id = 900000000000000000;

    IF NOT EXISTS (
        SELECT 1
          FROM ingest.publication_metric_snapshot
         WHERE id = 900000000000000000
           AND comments_count IS NULL
    ) THEN
        RAISE EXCEPTION 'explicit legacy snapshot id or nullable MAX comment smoke failed';
    END IF;
    IF (SELECT subscriber_count FROM ingest.account_metric_snapshot
         WHERE id = 900000000000000010) <> 101 THEN
        RAISE EXCEPTION 'migration_bridge account snapshot stable-id upsert failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.publication_latest
         WHERE publication_id = (
             SELECT target_uuid
               FROM catalog.legacy_entity_alias
              WHERE entity_type = 'platform_posts'
                AND legacy_id = 900000000000000000
         )
           AND comments_count IS NULL
    ) THEN
        RAISE EXCEPTION 'publication_latest nullable metric smoke failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ingest.publication_metric_snapshot_default
    ) THEN
        RAISE EXCEPTION 'current-month snapshot unexpectedly landed in the default partition';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.id = 900000000000000000
           AND has_table_privilege('migration_bridge', snapshot.tableoid, 'SELECT')
    ) THEN
        RAISE EXCEPTION 'monthly partition lacks direct bridge reconciliation read grant';
    END IF;
    IF (
        SELECT count(*)
          FROM analytics.projection_state
         WHERE projection_name IN (
             'publication_latest', 'publication_hourly',
             'institution_daily_metrics', 'institution_monthly_metrics',
             'institution_period_metrics', 'comparison'
         )
           AND dataset_revision_id = smoke_revision
           AND status = 'ready'
           AND error_code IS NULL
    ) <> 6 THEN
        RAISE EXCEPTION 'all projections were not atomically published ready at one revision';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.institution_period_metrics
         WHERE institution_id = smoke_institution
           AND platform = 'max'
           AND period_key = '3h'
           AND metric_key = 'views'
           AND aggregation = 'sum'
           AND value = 10
           AND sample_size = 1
           AND coverage = 0.5
           AND dataset_revision_id = smoke_revision
    ) THEN
        RAISE EXCEPTION 'platform period projection smoke failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.institution_period_metrics
         WHERE institution_id = smoke_institution
           AND platform IS NULL
           AND period_key = '3h'
           AND metric_key = 'views'
           AND aggregation = 'median'
           AND value IS NULL
           AND sample_size = 0
           AND coverage = 0.25
           AND quality = 'unknown'
           AND dataset_revision_id = smoke_revision
    ) THEN
        RAISE EXCEPTION 'all-platform coverage-only projection smoke failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.institution_period_metrics
         WHERE institution_id = smoke_institution
           AND platform = 'max'
           AND period_key = '3h'
           AND metric_key = 'comments'
           AND aggregation = 'sum'
           AND value IS NULL
           AND sample_size = 0
           AND dataset_revision_id = smoke_revision
    ) THEN
        RAISE EXCEPTION 'unsupported MAX comments were converted to zero';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.institution_daily_metrics
         WHERE institution_id = smoke_institution
           AND platform = 'max'
           AND metric_key = 'views'
           AND aggregation = 'sum'
           AND value = 10
           AND dataset_revision_id = smoke_revision
    ) OR coalesce((
        SELECT sum(value)
          FROM analytics.institution_monthly_metrics
         WHERE institution_id = smoke_institution
           AND platform = 'max'
           AND metric_key = 'views'
           AND aggregation = 'sum'
           AND dataset_revision_id = smoke_revision
    ), -1) <> 110 THEN
        RAISE EXCEPTION 'daily/monthly projection rebuild smoke failed';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM analytics.publication_hourly
         WHERE publication_id = (
             SELECT target_uuid
               FROM catalog.legacy_entity_alias
              WHERE entity_type = 'platform_posts'
                AND legacy_id = 900000000000000000
         )
           AND hour_offset = 0
           AND dataset_revision_id = smoke_revision
    ) OR NOT EXISTS (
        SELECT 1
          FROM analytics.publication_hourly
         WHERE publication_id = (
             SELECT target_uuid
               FROM catalog.legacy_entity_alias
              WHERE entity_type = 'platform_posts'
                AND legacy_id = 900000000000000000
         )
           AND hour_offset = 1
           AND views_count = 10
           AND dataset_revision_id = smoke_revision
    ) THEN
        RAISE EXCEPTION 'hourly projection used a future observation or missed its target hour';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM analytics.comparison_cohort AS cohort
          JOIN analytics.comparison_metric_point AS point ON point.cohort_id = cohort.id
         WHERE cohort.platform = 'max'
           AND cohort.horizon_seconds = 86400
           AND cohort.sample_size = 1
           AND cohort.dataset_revision_id = smoke_revision
           AND point.institution_id = smoke_institution
           AND point.metric_key = 'reactions'
           AND point.aggregation = 'median'
           AND point.hour_offset = 24
           AND point.value = 20
           AND point.sample_size = 1
           AND point.coverage = 1
    ) THEN
        RAISE EXCEPTION 'fixed-cohort comparison projection smoke failed';
    END IF;
    IF (SELECT value->>'pass'
          FROM ops_and_admin.operational_checkpoint
         WHERE checkpoint_key = 'smoke_state'
           AND scope_type = 'system'
           AND scope_id IS NULL
           AND platform IS NULL) <> '2' THEN
        RAISE EXCEPTION 'NULLS NOT DISTINCT checkpoint ON CONFLICT inference failed';
    END IF;
    IF (SELECT count(*) FROM migration.import_batch
         WHERE source_sha256 = repeat('d', 64)
           AND snapshot_kind = 'fixture'
           AND tool_version = 'smoke'
           AND dry_run) <> 2 THEN
        RAISE EXCEPTION 'import batch replay key collided across source_name';
    END IF;
END
$data_assertion$;

ROLLBACK;

\echo 'M-Ranked PostgreSQL 18.6 schema smoke assertions passed.'
