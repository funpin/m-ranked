\set ON_ERROR_STOP on
\set VERBOSITY terse

BEGIN;

-- The exact database-name check is the primary blast-radius guard.  The script
-- additionally refuses an incomplete Flyway baseline or unrelated source data.
DO $guard$
DECLARE
    applied_versions text[];
BEGIN
    IF current_database() <> 'mranked_ui_rehearsal' THEN
        RAISE EXCEPTION
            'refusing UI rehearsal fixture in database %; expected mranked_ui_rehearsal',
            current_database();
    END IF;

    SELECT array_agg(version ORDER BY installed_rank)
      INTO applied_versions
      FROM flyway.flyway_schema_history
     WHERE success
       AND version IS NOT NULL;

    IF applied_versions IS DISTINCT FROM ARRAY['1', '2', '3', '4', '5']::text[] THEN
        RAISE EXCEPTION
            'expected exactly successful Flyway versions {1,2,3,4,5}; found %',
            applied_versions;
    END IF;

    IF (SELECT count(*) FROM flyway.flyway_schema_history) <> 5
       OR EXISTS (
           SELECT 1
             FROM (VALUES
                 ('1', 'target baseline', -1636077697),
                 ('2', 'rebuild core projections', 839607018),
                 ('3', 'collector observation times and identity grants', -1456658399),
                 ('4', 'admin collection run status grants', 1318350062),
                 ('5', 'legacy activity period projection', -1313754193)
             ) AS expected(version, description, checksum)
             FULL JOIN flyway.flyway_schema_history AS history
               ON history.version = expected.version
            WHERE expected.version IS NULL
               OR history.version IS NULL
               OR history.description IS DISTINCT FROM expected.description
               OR history.type IS DISTINCT FROM 'SQL'
               OR history.checksum IS DISTINCT FROM expected.checksum
               OR history.installed_by IS DISTINCT FROM 'migration_owner'
               OR NOT coalesce(history.success, false)
       ) THEN
        RAISE EXCEPTION
            'refusing fixture because the exact Flyway V1--V5 history/checksums differ';
    END IF;

    IF NOT has_table_privilege(
        'api_write_admin', 'ingest.collection_run', 'SELECT'
    ) OR NOT has_table_privilege(
        'api_write_admin', 'ingest.collection_account_result', 'SELECT'
    ) OR NOT has_function_privilege(
        'api_write_admin',
        'analytics.rebuild_core_projections(bigint)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION
            'refusing fixture because the expected V4/V5 admin grants are incomplete';
    END IF;

    IF to_regprocedure('analytics.rebuild_core_projections_v2(bigint)') IS NULL
       OR has_function_privilege(
           'api_write_admin',
           'analytics.rebuild_core_projections_v2(bigint)',
           'EXECUTE'
       )
       OR has_function_privilege(
           'migration_bridge',
           'analytics.rebuild_core_projections_v2(bigint)',
           'EXECUTE'
       )
       OR has_function_privilege(
           'maintenance',
           'analytics.rebuild_core_projections_v2(bigint)',
           'EXECUTE'
       ) THEN
        RAISE EXCEPTION
            'refusing fixture because the V5 private publisher boundary is incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM catalog.institution
         WHERE id NOT IN (
             '11111111-1111-4111-8111-111111111101'::uuid,
             '11111111-1111-4111-8111-111111111102'::uuid
         )
    ) OR EXISTS (
        SELECT 1
          FROM catalog.platform_account
         WHERE id NOT IN (
             '22222222-2222-4222-8222-222222222201'::uuid,
             '22222222-2222-4222-8222-222222222202'::uuid
         )
    ) OR EXISTS (
        SELECT 1
          FROM ingest.publication
         WHERE id NOT IN (
             '33333333-3333-4333-8333-333333333301'::uuid,
             '33333333-3333-4333-8333-333333333302'::uuid
         )
    ) OR EXISTS (
        SELECT 1
          FROM ingest.collection_run
         WHERE id <> '44444444-4444-4444-8444-444444444401'::uuid
    ) OR EXISTS (
        SELECT 1
          FROM analytics.dataset_revision
         WHERE id <> 9003001
    ) OR EXISTS (
        SELECT 1
          FROM rating.formula_definition
         WHERE id <> '66666666-6666-4666-8666-666666666601'::uuid
    ) OR EXISTS (
        SELECT 1
          FROM rating.rating_run
         WHERE id <> '88888888-8888-4888-8888-888888888801'::uuid
    ) THEN
        RAISE EXCEPTION
            'refusing fixture because the dedicated database contains unrelated source rows';
    END IF;
END
$guard$;

SET LOCAL ROLE migration_owner;
SET LOCAL timezone = 'UTC';
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '2min';

INSERT INTO catalog.institution (
    id, canonical_name, short_name, status, created_at, updated_at, row_version
) VALUES
    (
        '11111111-1111-4111-8111-111111111101',
        'Альфа Институт',
        'Альфа',
        'active',
        '2026-09-01T09:00:00Z',
        '2026-09-01T09:00:00Z',
        0
    ),
    (
        '11111111-1111-4111-8111-111111111102',
        'Бета Академия',
        'Бета',
        'active',
        '2026-09-01T09:00:00Z',
        '2026-09-01T09:00:00Z',
        0
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO catalog.platform_account (
    id, institution_id, platform, canonical_external_id, current_username,
    current_title, current_url, access_mode, enabled, created_at, updated_at,
    row_version
) VALUES
    (
        '22222222-2222-4222-8222-222222222201',
        '11111111-1111-4111-8111-111111111101',
        'telegram',
        '-100900300101',
        'alpha_rehearsal',
        'Альфа — Telegram',
        'https://t.me/alpha_rehearsal',
        'mtproto',
        true,
        '2026-09-01T09:05:00Z',
        '2026-09-01T09:05:00Z',
        0
    ),
    (
        '22222222-2222-4222-8222-222222222202',
        '11111111-1111-4111-8111-111111111102',
        'telegram',
        '-100900300102',
        'beta_rehearsal',
        'Бета — Telegram',
        'https://t.me/beta_rehearsal',
        'mtproto',
        true,
        '2026-09-01T09:05:00Z',
        '2026-09-01T09:05:00Z',
        0
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO catalog.legacy_entity_alias (
    entity_type, legacy_id, target_uuid, legacy_route, source_hash, created_at
) VALUES
    (
        'institutions', 910001,
        '11111111-1111-4111-8111-111111111101',
        '/institutions/910001', repeat('a', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'institutions', 910002,
        '11111111-1111-4111-8111-111111111102',
        '/institutions/910002', repeat('b', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'channels', 920001,
        '22222222-2222-4222-8222-222222222201',
        '/channels/920001', repeat('c', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'channels', 920002,
        '22222222-2222-4222-8222-222222222202',
        '/channels/920002', repeat('d', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'platform_accounts', 930001,
        '22222222-2222-4222-8222-222222222201',
        '/platform-accounts/930001', repeat('e', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'platform_accounts', 930002,
        '22222222-2222-4222-8222-222222222202',
        '/platform-accounts/930002', repeat('f', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'posts', 940001,
        '33333333-3333-4333-8333-333333333301',
        '/posts/940001', repeat('1', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'posts', 940002,
        '33333333-3333-4333-8333-333333333302',
        '/posts/940002', repeat('2', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'platform_posts', 950001,
        '33333333-3333-4333-8333-333333333301',
        '/platform-posts/950001', repeat('3', 64), '2026-09-01T09:10:00Z'
    ),
    (
        'platform_posts', 950002,
        '33333333-3333-4333-8333-333333333302',
        '/platform-posts/950002', repeat('4', 64), '2026-09-01T09:10:00Z'
    )
ON CONFLICT (entity_type, legacy_id) DO NOTHING;

INSERT INTO ingest.collection_run (
    id, platform, partition_key, collector_version, scheduled_at, started_at,
    completed_at, status, account_count, error_count, correlation_id
) VALUES (
    '44444444-4444-4444-8444-444444444401',
    'telegram',
    'ui-rehearsal',
    'ui-rehearsal-v1',
    '2026-09-02T11:55:00Z',
    '2026-09-02T11:56:00Z',
    '2026-09-03T12:02:00Z',
    'succeeded',
    2,
    0,
    '55555555-5555-4555-8555-555555555501'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO ingest.collection_account_result (
    collection_run_id, platform_account_id, started_at, completed_at, status,
    discovered_count, snapshot_count, sanitized_error_code
) VALUES
    (
        '44444444-4444-4444-8444-444444444401',
        '22222222-2222-4222-8222-222222222201',
        '2026-09-02T11:56:00Z', '2026-09-03T12:01:00Z',
        'succeeded', 1, 25, NULL
    ),
    (
        '44444444-4444-4444-8444-444444444401',
        '22222222-2222-4222-8222-222222222202',
        '2026-09-02T11:56:00Z', '2026-09-03T12:01:00Z',
        'succeeded', 1, 25, NULL
    )
ON CONFLICT (collection_run_id, platform_account_id) DO NOTHING;

INSERT INTO ingest.publication (
    id, primary_account_id, published_at, discovered_at,
    first_observation_age_seconds, publication_type, is_repost,
    history_completeness, synthetic_baseline_allowed, quality_flags,
    created_at
) VALUES
    (
        '33333333-3333-4333-8333-333333333301',
        '22222222-2222-4222-8222-222222222201',
        '2026-09-02T12:00:00Z',
        '2026-09-02T12:00:00Z',
        0, 'post', false, 'complete', false,
        '{"fixture":"positive-ui","series":"alpha"}',
        '2026-09-02T12:00:00Z'
    ),
    (
        '33333333-3333-4333-8333-333333333302',
        '22222222-2222-4222-8222-222222222202',
        '2026-09-02T12:00:00Z',
        '2026-09-02T12:00:00Z',
        0, 'post', false, 'complete', false,
        '{"fixture":"positive-ui","series":"beta"}',
        '2026-09-02T12:00:00Z'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO ingest.publication_identity (
    publication_id, platform_account_id, external_id, source_external_id,
    role, public_url
) VALUES
    (
        '33333333-3333-4333-8333-333333333301',
        '22222222-2222-4222-8222-222222222201',
        '900300101', NULL, 'primary',
        'https://t.me/alpha_rehearsal/900300101'
    ),
    (
        '33333333-3333-4333-8333-333333333302',
        '22222222-2222-4222-8222-222222222202',
        '900300102', NULL, 'primary',
        'https://t.me/beta_rehearsal/900300102'
    )
ON CONFLICT (platform_account_id, external_id) DO NOTHING;

SELECT ops_and_admin.ensure_publication_metric_partition('2026-09-01'::date);

WITH fixture_series AS (
    SELECT
        fixture.publication_id,
        fixture.series_number,
        hour_offset
      FROM (VALUES
          ('33333333-3333-4333-8333-333333333301'::uuid, 1),
          ('33333333-3333-4333-8333-333333333302'::uuid, 2)
      ) AS fixture(publication_id, series_number)
     CROSS JOIN generate_series(0, 24) AS hours(hour_offset)
)
INSERT INTO ingest.publication_metric_snapshot (
    published_month, publication_id, collection_run_id, observed_at,
    collected_at, age_seconds, sampling_bucket, views_count, reactions_count,
    comments_count, shares_count, quality, interval_uncertain, synthetic,
    metric_semantics_version, capability_version, source_fingerprint, created_at
)
SELECT
    '2026-09-01'::date,
    fixture.publication_id,
    '44444444-4444-4444-8444-444444444401'::uuid,
    '2026-09-02T12:00:00Z'::timestamptz + fixture.hour_offset * interval '1 hour',
    '2026-09-02T12:01:00Z'::timestamptz + fixture.hour_offset * interval '1 hour',
    fixture.hour_offset * 3600,
    fixture.hour_offset,
    CASE fixture.series_number
        WHEN 1 THEN 100 + fixture.hour_offset * 40
        ELSE 80 + fixture.hour_offset * 30
    END,
    CASE fixture.series_number
        WHEN 1 THEN 10 + fixture.hour_offset * 5
        ELSE 8 + fixture.hour_offset * 3
    END,
    CASE fixture.series_number
        WHEN 1 THEN 2 + fixture.hour_offset
        ELSE 1 + fixture.hour_offset / 2
    END,
    CASE fixture.series_number
        WHEN 1 THEN 1 + fixture.hour_offset / 2
        ELSE fixture.hour_offset / 3
    END,
    'exact',
    false,
    false,
    1,
    1,
    format('ui-rehearsal-series-%s-hour-%s', fixture.series_number, fixture.hour_offset),
    '2026-09-02T12:01:00Z'::timestamptz + fixture.hour_offset * interval '1 hour'
  FROM fixture_series AS fixture
ON CONFLICT (published_month, publication_id, sampling_bucket) DO NOTHING;

INSERT INTO analytics.dataset_revision (
    id, committed_at, cause, correlation_id, source_run_id, metadata
) VALUES (
    9003001,
    '2026-09-03T12:05:00Z',
    'ingestion',
    '55555555-5555-4555-8555-555555555501',
    '44444444-4444-4444-8444-444444444401',
    '{"fixture":"positive-ui","deterministic":true,"horizon_hours":24}'
)
ON CONFLICT (id) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('analytics.dataset_revision', 'id'),
    9003001,
    true
);

DO $projection_replay$
DECLARE
    first_result jsonb;
    second_result jsonb;
    first_period_rows jsonb;
    second_period_rows jsonb;
BEGIN
    first_result := analytics.rebuild_core_projections(9003001);

    SELECT jsonb_agg(
               to_jsonb(metric) - 'id' - 'refreshed_at'
               ORDER BY metric.institution_id, metric.platform NULLS LAST,
                        metric.period_key, metric.metric_key, metric.aggregation
           )
      INTO first_period_rows
      FROM analytics.institution_period_metrics AS metric
     WHERE metric.dataset_revision_id = 9003001;

    second_result := analytics.rebuild_core_projections(9003001);

    SELECT jsonb_agg(
               to_jsonb(metric) - 'id' - 'refreshed_at'
               ORDER BY metric.institution_id, metric.platform NULLS LAST,
                        metric.period_key, metric.metric_key, metric.aggregation
           )
      INTO second_period_rows
      FROM analytics.institution_period_metrics AS metric
     WHERE metric.dataset_revision_id = 9003001;

    IF first_result->>'institution_period_semantics_version' <> '2'
       OR second_result->>'institution_period_semantics_version' <> '2' THEN
        RAISE EXCEPTION
            'expected the V5 publisher to report period semantics version 2';
    END IF;

    IF first_result->>'institution_period_metrics' <> '128'
       OR second_result->>'institution_period_metrics' <> '128' THEN
        RAISE EXCEPTION
            'expected 128 V5 period rows; first %, second %',
            first_result->>'institution_period_metrics',
            second_result->>'institution_period_metrics';
    END IF;

    IF first_period_rows IS DISTINCT FROM second_period_rows THEN
        RAISE EXCEPTION 'V5 period projection is not idempotent';
    END IF;
END
$projection_replay$;

INSERT INTO rating.formula_definition (
    id, formula_key, version, status, effective_from, definition,
    source_hash, created_at, published_at
) VALUES (
    '66666666-6666-4666-8666-666666666601',
    'm-ranked-rehearsal',
    1,
    'draft',
    '2026-09-01T00:00:00Z',
    '{"name":"M-Ranked deterministic UI rehearsal","window":"24h","scale":"0..100"}',
    repeat('6', 64),
    '2026-09-01T00:00:00Z',
    NULL
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO rating.formula_component (
    id, formula_definition_id, component_code, numerator_metric,
    denominator_key, weight, normalization, missing_policy, minimum_quality
)
SELECT
    '77777777-7777-4777-8777-777777777701'::uuid,
    '66666666-6666-4666-8666-666666666601'::uuid,
    'reaction_velocity_24h',
    'reactions'::analytics.metric_key,
    NULL,
    1,
    'fixture-linear-0-100',
    'exclude',
    'exact'::ingest.observation_quality
WHERE NOT EXISTS (
    SELECT 1
      FROM rating.formula_component
     WHERE id = '77777777-7777-4777-8777-777777777701'
)
ON CONFLICT (id) DO NOTHING;

UPDATE rating.formula_definition
   SET status = 'published',
       published_at = '2026-09-03T12:04:00Z'
 WHERE id = '66666666-6666-4666-8666-666666666601'
   AND status = 'draft';

INSERT INTO rating.rating_run (
    id, formula_definition_id, dataset_revision_id, as_of, window_start,
    window_end, status, started_at, completed_at, input_hash
) VALUES (
    '88888888-8888-4888-8888-888888888801',
    '66666666-6666-4666-8666-666666666601',
    9003001,
    '2026-09-03T12:05:00Z',
    '2026-09-02T12:05:00Z',
    '2026-09-03T12:05:00Z',
    'succeeded',
    '2026-09-03T12:05:10Z',
    '2026-09-03T12:05:11Z',
    repeat('8', 64)
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO rating.rating_result (
    id, rating_run_id, institution_id, score, rank, quality, explanation
) VALUES
    (
        '99999999-9999-4999-8999-999999999901',
        '88888888-8888-4888-8888-888888888801',
        '11111111-1111-4111-8111-111111111101',
        87.50,
        1,
        'exact',
        '{"fixture":true,"reaction_count_at_24h":130}'
    ),
    (
        '99999999-9999-4999-8999-999999999902',
        '88888888-8888-4888-8888-888888888801',
        '11111111-1111-4111-8111-111111111102',
        72.25,
        2,
        'exact',
        '{"fixture":true,"reaction_count_at_24h":80}'
    )
ON CONFLICT (id) DO NOTHING;

WITH result_ids AS (
    SELECT id, institution_id
      FROM rating.rating_result
     WHERE rating_run_id = '88888888-8888-4888-8888-888888888801'
)
INSERT INTO rating.rating_component_result (
    rating_result_id, formula_component_id, numerator, denominator,
    normalized_value, weighted_value, warnings
)
SELECT
    result.id,
    '77777777-7777-4777-8777-777777777701',
    CASE result.institution_id
        WHEN '11111111-1111-4111-8111-111111111101'::uuid THEN 130
        ELSE 80
    END,
    NULL,
    CASE result.institution_id
        WHEN '11111111-1111-4111-8111-111111111101'::uuid THEN 87.50
        ELSE 72.25
    END,
    CASE result.institution_id
        WHEN '11111111-1111-4111-8111-111111111101'::uuid THEN 87.50
        ELSE 72.25
    END,
    '[]'
  FROM result_ids AS result
ON CONFLICT (rating_result_id, formula_component_id) DO NOTHING;

DO $assertions$
DECLARE
    actual_count bigint;
    actual_numeric numeric;
    actual_text text;
BEGIN
    SELECT count(*) INTO actual_count
      FROM ingest.publication_metric_snapshot
     WHERE publication_id IN (
         '33333333-3333-4333-8333-333333333301'::uuid,
         '33333333-3333-4333-8333-333333333302'::uuid
     );
    IF actual_count <> 50 THEN
        RAISE EXCEPTION 'expected 50 source snapshots; found %', actual_count;
    END IF;

    SELECT count(*) INTO actual_count
      FROM analytics.publication_hourly
     WHERE dataset_revision_id = 9003001;
    IF actual_count <> 50 THEN
        RAISE EXCEPTION 'expected 50 hourly projection rows; found %', actual_count;
    END IF;

    SELECT count(*) INTO actual_count
      FROM analytics.institution_period_metrics
     WHERE dataset_revision_id = 9003001;
    IF actual_count <> 128 THEN
        RAISE EXCEPTION 'expected 128 V5 period projection rows; found %', actual_count;
    END IF;

    SELECT value INTO actual_numeric
      FROM analytics.institution_period_metrics
     WHERE dataset_revision_id = 9003001
       AND institution_id = '11111111-1111-4111-8111-111111111101'
       AND platform = 'telegram'
       AND period_key = '1d'
       AND metric_key = 'reactions'
       AND aggregation = 'sum';
    IF actual_numeric IS DISTINCT FROM 115 THEN
        RAISE EXCEPTION
            'expected Alpha open-left 1d reaction activity 115; found %',
            actual_numeric;
    END IF;

    SELECT value INTO actual_numeric
      FROM analytics.institution_period_metrics
     WHERE dataset_revision_id = 9003001
       AND institution_id = '11111111-1111-4111-8111-111111111102'
       AND platform = 'telegram'
       AND period_key = '1d'
       AND metric_key = 'reactions'
       AND aggregation = 'median';
    IF actual_numeric IS DISTINCT FROM 69 THEN
        RAISE EXCEPTION
            'expected Beta open-left 1d reaction median 69; found %',
            actual_numeric;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM analytics.institution_period_metrics
         WHERE dataset_revision_id = 9003001
           AND platform IS NULL
           AND (value IS NOT NULL OR sample_size <> 0 OR coverage <> 0.25
                OR quality <> 'unknown')
    ) THEN
        RAISE EXCEPTION
            'expected V5 all-platform rows to be coverage-only with no metric sample';
    END IF;

    SELECT sample_size INTO actual_count
      FROM analytics.comparison_cohort
     WHERE dataset_revision_id = 9003001
       AND platform = 'telegram'
       AND horizon_seconds = 86400
       AND filter_definition->>'include_partial' = 'false';
    IF actual_count IS DISTINCT FROM 2 THEN
        RAISE EXCEPTION 'expected complete 24h comparison cohort size 2; found %', actual_count;
    END IF;

    SELECT count(*) INTO actual_count
      FROM analytics.comparison_metric_point AS point
      JOIN analytics.comparison_cohort AS cohort ON cohort.id = point.cohort_id
     WHERE cohort.dataset_revision_id = 9003001
       AND cohort.platform = 'telegram'
       AND cohort.horizon_seconds = 86400
       AND cohort.filter_definition->>'include_partial' = 'false'
       AND point.metric_key = 'reactions'
       AND point.aggregation = 'median';
    IF actual_count <> 50 THEN
        RAISE EXCEPTION 'expected 50 positive reaction comparison points; found %', actual_count;
    END IF;

    SELECT point.value INTO actual_numeric
      FROM analytics.comparison_metric_point AS point
      JOIN analytics.comparison_cohort AS cohort ON cohort.id = point.cohort_id
     WHERE cohort.dataset_revision_id = 9003001
       AND cohort.horizon_seconds = 86400
       AND cohort.filter_definition->>'include_partial' = 'false'
       AND point.institution_id = '11111111-1111-4111-8111-111111111101'
       AND point.metric_key = 'reactions'
       AND point.aggregation = 'median'
       AND point.hour_offset = 24;
    IF actual_numeric IS DISTINCT FROM 130 THEN
        RAISE EXCEPTION 'expected Alpha reaction value 130 at hour 24; found %', actual_numeric;
    END IF;

    SELECT string_agg(format('%s:%s:%s', rank, score, legacy_id), ',' ORDER BY rank)
      INTO actual_text
      FROM rating.rating_result AS result
      JOIN rating.rating_run AS run ON run.id = result.rating_run_id
      JOIN catalog.legacy_entity_alias AS alias
        ON alias.target_uuid = result.institution_id
       AND alias.entity_type = 'institutions'
     WHERE run.dataset_revision_id = 9003001
       AND run.status = 'succeeded';
    IF actual_text IS DISTINCT FROM '1:87.50:910001,2:72.25:910002' THEN
        RAISE EXCEPTION 'unexpected positive rating payload signature: %', actual_text;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM analytics.projection_state
         WHERE dataset_revision_id <> 9003001
            OR status <> 'ready'
    ) OR (SELECT count(*) FROM analytics.projection_state) <> 6 THEN
        RAISE EXCEPTION 'expected exactly six ready projection states for revision 9003001';
    END IF;
END
$assertions$;

COMMIT;

SELECT jsonb_build_object(
           'database', current_database(),
           'dataset_revision', 9003001,
           'institutions', count(DISTINCT point.institution_id),
           'reaction_median_points_24h', count(*),
           'first_hour', min(point.hour_offset),
           'last_hour', max(point.hour_offset)
       ) AS comparison_fixture
  FROM analytics.comparison_metric_point AS point
  JOIN analytics.comparison_cohort AS cohort ON cohort.id = point.cohort_id
 WHERE cohort.dataset_revision_id = 9003001
   AND cohort.platform = 'telegram'
   AND cohort.horizon_seconds = 86400
   AND cohort.filter_definition->>'include_partial' = 'false'
   AND point.metric_key = 'reactions'
   AND point.aggregation = 'median';

SELECT jsonb_agg(
           jsonb_build_object(
               'legacy_id', alias.legacy_id,
               'name', institution.canonical_name,
               'rank', result.rank,
               'score', result.score,
               'quality', result.quality
           ) ORDER BY result.rank
       ) AS rating_fixture
  FROM rating.rating_result AS result
  JOIN rating.rating_run AS run ON run.id = result.rating_run_id
  JOIN catalog.institution AS institution ON institution.id = result.institution_id
  JOIN catalog.legacy_entity_alias AS alias
    ON alias.target_uuid = institution.id
   AND alias.entity_type = 'institutions'
 WHERE run.dataset_revision_id = 9003001
   AND run.status = 'succeeded';

SELECT jsonb_agg(
           jsonb_build_object(
               'institution_legacy_id', alias.legacy_id,
               'channel_legacy_id', channel_alias.legacy_id,
               'reaction_activity_1d', metric.value,
               'sample_size', metric.sample_size,
               'coverage', metric.coverage
           ) ORDER BY alias.legacy_id
       ) AS period_fixture
  FROM analytics.institution_period_metrics AS metric
  JOIN catalog.legacy_entity_alias AS alias
    ON alias.target_uuid = metric.institution_id
   AND alias.entity_type = 'institutions'
  JOIN catalog.platform_account AS account
    ON account.institution_id = metric.institution_id
   AND account.platform = 'telegram'
  JOIN catalog.legacy_entity_alias AS channel_alias
    ON channel_alias.target_uuid = account.id
   AND channel_alias.entity_type = 'channels'
 WHERE metric.dataset_revision_id = 9003001
   AND metric.platform = 'telegram'
   AND metric.period_key = '1d'
   AND metric.metric_key = 'reactions'
   AND metric.aggregation = 'sum';
