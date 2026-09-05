\set ON_ERROR_STOP on

-- Deterministic semantic proof for the V6 comparison read model and the
-- metric-specific fixed cohorts consumed by /api/v1/compare. Every fixture
-- write is rolled back.

BEGIN;
SET LOCAL ROLE migration_owner;

INSERT INTO catalog.institution (id, canonical_name, short_name)
VALUES (
    '66666666-6666-4666-8666-666666666601',
    'Comparison golden university', 'Comparison golden'
);

INSERT INTO catalog.legacy_entity_alias (
    entity_type, legacy_id, target_uuid, legacy_route
) VALUES
    (
        'institutions', 966666666601,
        '66666666-6666-4666-8666-666666666601',
        '/institutions/966666666601'
    ),
    (
        'channels', 966666666611,
        '66666666-6666-4666-8666-666666666611',
        '/channels/966666666611'
    );

INSERT INTO catalog.platform_account (
    id, institution_id, platform, canonical_external_id, current_username,
    current_title, current_url, access_mode, enabled, created_at, updated_at
) VALUES (
    '66666666-6666-4666-8666-666666666611',
    '66666666-6666-4666-8666-666666666601',
    'telegram', 'comparison-golden-telegram', 'comparison_golden',
    'Comparison golden Telegram', 'https://t.me/comparison_golden',
    'public_web', true, '2026-09-01T11:00:00Z', '2026-09-01T11:00:00Z'
);

INSERT INTO ingest.collection_run (
    id, platform, partition_key, collector_version, scheduled_at, started_at,
    completed_at, status, correlation_id
) VALUES
    (
        '66666666-6666-4666-8666-666666666621',
        'telegram', 'comparison-golden', 'comparison-golden-v1',
        '2026-09-01T11:58:00Z', '2026-09-01T11:59:00Z',
        '2026-09-02T12:01:00Z', 'succeeded',
        '66666666-6666-4666-8666-666666666631'
    ),
    (
        '66666666-6666-4666-8666-666666666622',
        'telegram', 'comparison-golden-late', 'comparison-golden-v1',
        '2026-09-04T11:58:00Z', '2026-09-04T11:59:00Z',
        '2026-09-04T12:01:00Z', 'succeeded',
        '66666666-6666-4666-8666-666666666632'
    );

-- 641/642 are complete and carry reactions; 643 is partial and starts after
-- publication; 644 is a generic complete member whose reactions/engagement
-- are unavailable, proving the HTTP query must derive metric-specific cohorts.
INSERT INTO ingest.publication (
    id, primary_account_id, published_at, discovered_at,
    first_observation_age_seconds, publication_type, history_completeness,
    synthetic_baseline_allowed, quality_flags, created_at
) VALUES
    (
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666611',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:10Z', 0,
        'post', 'complete', true, '{"fixture":"complete-a"}',
        '2026-09-01T12:00:10Z'
    ),
    (
        '66666666-6666-4666-8666-666666666642',
        '66666666-6666-4666-8666-666666666611',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:10Z', 0,
        'post', 'complete', true, '{"fixture":"complete-b"}',
        '2026-09-01T12:00:10Z'
    ),
    (
        '66666666-6666-4666-8666-666666666643',
        '66666666-6666-4666-8666-666666666611',
        '2026-09-01T12:00:00Z', '2026-09-01T12:20:00Z', 1200,
        'post', 'incomplete', false, '{"fixture":"partial"}',
        '2026-09-01T12:20:00Z'
    ),
    (
        '66666666-6666-4666-8666-666666666644',
        '66666666-6666-4666-8666-666666666611',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:10Z', 0,
        'post', 'complete', true, '{"fixture":"views-only"}',
        '2026-09-01T12:00:10Z'
    );

SELECT ops_and_admin.ensure_publication_metric_partition('2026-09-01'::date);

INSERT INTO ingest.publication_metric_snapshot (
    published_month, id, publication_id, collection_run_id, observed_at,
    collected_at, age_seconds, sampling_bucket, views_count, reactions_count,
    comments_count, shares_count, quality, interval_uncertain, synthetic,
    metric_semantics_version, capability_version, source_fingerprint, created_at
) VALUES
    -- Complete A: the 50-minute NULL row must not erase the valid 20-minute
    -- values at hour 1. The still later 58-minute row was collected after the
    -- revision and the invalid 59-minute row must also be invisible.
    ('2026-09-01', 966666666601,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:00Z', 0, 1,
        0, 0, NULL, NULL, 'exact', false, true, 1, 1,
        repeat('1', 64), '2026-09-01T12:00:00Z'),
    ('2026-09-01', 966666666602,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:20:00Z', '2026-09-01T12:20:10Z', 1200, 2,
        100, 10, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('2', 64), '2026-09-01T12:20:10Z'),
    ('2026-09-01', 966666666603,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:50:00Z', '2026-09-01T12:50:10Z', 3000, 3,
        NULL, NULL, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('3', 64), '2026-09-01T12:50:10Z'),
    ('2026-09-01', 966666666604,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666622',
        '2026-09-01T12:58:00Z', '2026-09-04T12:00:00Z', 3480, 4,
        999, 999, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('4', 64), '2026-09-04T12:00:00Z'),
    ('2026-09-01', 966666666605,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:59:00Z', '2026-09-01T12:59:10Z', 3540, 5,
        777, 777, NULL, NULL, 'invalid', false, false, 1, 1,
        repeat('5', 64), '2026-09-01T12:59:10Z'),
    ('2026-09-01', 966666666606,
        '66666666-6666-4666-8666-666666666641',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-02T12:00:00Z', '2026-09-02T12:00:10Z', 86400, 6,
        200, 20, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('6', 64), '2026-09-02T12:00:10Z'),

    -- Complete B yields a primary median of 10.5 and engagement 5.5% at h1.
    ('2026-09-01', 966666666611,
        '66666666-6666-4666-8666-666666666642',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:00Z', 0, 11,
        0, 0, NULL, NULL, 'exact', false, true, 1, 1,
        repeat('a', 64), '2026-09-01T12:00:00Z'),
    ('2026-09-01', 966666666612,
        '66666666-6666-4666-8666-666666666642',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:20:00Z', '2026-09-01T12:20:10Z', 1200, 12,
        200, 11, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('b', 64), '2026-09-01T12:20:10Z'),
    ('2026-09-01', 966666666613,
        '66666666-6666-4666-8666-666666666642',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:50:00Z', '2026-09-01T12:50:10Z', 3000, 13,
        NULL, NULL, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('c', 64), '2026-09-01T12:50:10Z'),
    ('2026-09-01', 966666666614,
        '66666666-6666-4666-8666-666666666642',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-02T12:00:00Z', '2026-09-02T12:00:10Z', 86400, 14,
        400, 21, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('d', 64), '2026-09-02T12:00:10Z'),

    -- Partial C has no h0 input but is complete from h1 through h24.
    ('2026-09-01', 966666666621,
        '66666666-6666-4666-8666-666666666643',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:20:00Z', '2026-09-01T12:20:10Z', 1200, 21,
        300, 12, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('e', 64), '2026-09-01T12:20:10Z'),
    ('2026-09-01', 966666666622,
        '66666666-6666-4666-8666-666666666643',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-02T12:00:00Z', '2026-09-02T12:00:10Z', 86400, 22,
        600, 30, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('f', 64), '2026-09-02T12:00:10Z'),

    -- Complete D is a views-only generic cohort member.
    ('2026-09-01', 966666666631,
        '66666666-6666-4666-8666-666666666644',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-01T12:00:00Z', '2026-09-01T12:00:00Z', 0, 31,
        0, NULL, NULL, NULL, 'exact', false, true, 1, 1,
        repeat('7', 64), '2026-09-01T12:00:00Z'),
    ('2026-09-01', 966666666632,
        '66666666-6666-4666-8666-666666666644',
        '66666666-6666-4666-8666-666666666621',
        '2026-09-02T12:00:00Z', '2026-09-02T12:00:10Z', 86400, 32,
        50, NULL, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('8', 64), '2026-09-02T12:00:10Z');

INSERT INTO analytics.dataset_revision (
    committed_at, cause, correlation_id, source_run_id, metadata
) VALUES (
    '2026-09-03T12:00:00Z', 'analytics',
    '66666666-6666-4666-8666-666666666633',
    '66666666-6666-4666-8666-666666666621',
    '{"fixture":"comparison-golden"}'
) RETURNING id AS revision_id
\gset comparison_golden_

DO $golden$
DECLARE
    golden_revision_id bigint;
    complete_cohort_id uuid;
    partial_cohort_id uuid;
    first_result jsonb;
    second_result jsonb;
    first_rows jsonb;
    second_rows jsonb;
    primary_size integer;
    engagement_size integer;
    primary_median numeric;
    engagement_median numeric;
BEGIN
    SELECT id INTO STRICT golden_revision_id
      FROM analytics.dataset_revision
     WHERE correlation_id = '66666666-6666-4666-8666-666666666633';

    first_result := analytics.rebuild_core_projections(golden_revision_id);

    SELECT jsonb_agg(to_jsonb(hourly)
                     ORDER BY hourly.publication_id, hourly.hour_offset)
      INTO first_rows
      FROM analytics.comparison_publication_hourly AS hourly
     WHERE hourly.dataset_revision_id = golden_revision_id;

    second_result := analytics.rebuild_core_projections(golden_revision_id);

    SELECT jsonb_agg(to_jsonb(hourly)
                     ORDER BY hourly.publication_id, hourly.hour_offset)
      INTO second_rows
      FROM analytics.comparison_publication_hourly AS hourly
     WHERE hourly.dataset_revision_id = golden_revision_id;

    IF first_result->>'comparison_semantics_version' <> '2'
       OR second_result->>'comparison_semantics_version' <> '2' THEN
        RAISE EXCEPTION 'V6 rebuild did not identify comparison semantics version 2';
    END IF;
    IF first_rows IS DISTINCT FROM second_rows THEN
        RAISE EXCEPTION 'V6 comparison rebuild is not idempotent';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM analytics.comparison_publication_hourly AS hourly
         WHERE hourly.dataset_revision_id = golden_revision_id
           AND hourly.publication_id = '66666666-6666-4666-8666-666666666641'
           AND hourly.hour_offset = 1
           AND hourly.views_count = 100
           AND hourly.reactions_count = 10
           AND hourly.engagement_percent = 10
           AND hourly.views_quality = 'exact'
           AND hourly.reactions_quality = 'exact'
           AND hourly.engagement_quality = 'exact'
    ) THEN
        RAISE EXCEPTION 'latest valid per-metric h1 value, collected-at cutoff, invalid exclusion, or same-snapshot engagement failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM analytics.comparison_publication_hourly AS hourly
         WHERE hourly.dataset_revision_id = golden_revision_id
           AND hourly.publication_id = '66666666-6666-4666-8666-666666666643'
           AND hourly.hour_offset = 0
           AND hourly.views_count IS NULL
           AND hourly.reactions_count IS NULL
           AND hourly.engagement_percent IS NULL
    ) THEN
        RAISE EXCEPTION 'partial history used a future observation backward at h0';
    END IF;

    SELECT id INTO STRICT complete_cohort_id
      FROM analytics.comparison_cohort
     WHERE dataset_revision_id = golden_revision_id
       AND platform = 'telegram'
       AND horizon_seconds = 86400
       AND (filter_definition->>'include_partial')::boolean = false;
    SELECT id INTO STRICT partial_cohort_id
      FROM analytics.comparison_cohort
     WHERE dataset_revision_id = golden_revision_id
       AND platform = 'telegram'
       AND horizon_seconds = 86400
       AND (filter_definition->>'include_partial')::boolean = true;

    IF (SELECT sample_size FROM analytics.comparison_cohort
         WHERE id = complete_cohort_id) <> 3
       OR (SELECT sample_size FROM analytics.comparison_cohort
            WHERE id = partial_cohort_id) <> 4 THEN
        RAISE EXCEPTION 'generic complete/partial fixed cohort membership changed';
    END IF;

    WITH metric_members AS (
        SELECT member.publication_id
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_publication_hourly AS hourly
            ON hourly.publication_id = member.publication_id
           AND hourly.dataset_revision_id = golden_revision_id
         WHERE member.cohort_id = complete_cohort_id
         GROUP BY member.publication_id
        HAVING bool_or(hourly.hour_offset = 0 AND hourly.reactions_count IS NOT NULL)
           AND bool_or(hourly.hour_offset = 24 AND hourly.reactions_count IS NOT NULL)
    ), engagement_members AS (
        SELECT member.publication_id
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_publication_hourly AS hourly
            ON hourly.publication_id = member.publication_id
           AND hourly.dataset_revision_id = golden_revision_id
         WHERE member.cohort_id = complete_cohort_id
         GROUP BY member.publication_id
        HAVING bool_or(hourly.hour_offset = 1 AND hourly.engagement_percent IS NOT NULL)
           AND bool_or(hourly.hour_offset = 24 AND hourly.engagement_percent IS NOT NULL)
    )
    SELECT (SELECT count(*) FROM metric_members),
           (SELECT count(*) FROM engagement_members),
           (
               SELECT percentile_cont(0.5) WITHIN GROUP (
                          ORDER BY hourly.reactions_count
                      )::numeric
                 FROM analytics.comparison_publication_hourly AS hourly
                 JOIN metric_members AS member USING (publication_id)
                WHERE hourly.dataset_revision_id = golden_revision_id
                  AND hourly.hour_offset = 1
           ),
           (
               SELECT percentile_cont(0.5) WITHIN GROUP (
                          ORDER BY hourly.engagement_percent
                      )::numeric
                 FROM analytics.comparison_publication_hourly AS hourly
                 JOIN engagement_members AS member USING (publication_id)
                WHERE hourly.dataset_revision_id = golden_revision_id
                  AND hourly.hour_offset = 1
           )
      INTO primary_size, engagement_size, primary_median, engagement_median;

    IF primary_size <> 2 OR engagement_size <> 2 THEN
        RAISE EXCEPTION 'metric-specific primary/engagement cohorts did not exclude the views-only generic member';
    END IF;
    IF primary_median <> 10.5 THEN
        RAISE EXCEPTION 'comparison median lost its exact .5 value: %', primary_median;
    END IF;
    IF engagement_median <> 7.75 THEN
        RAISE EXCEPTION 'engagement median was not calculated from same-snapshot ratios: %', engagement_median;
    END IF;

    IF (SELECT count(*) FROM analytics.projection_state) <> 6
       OR (SELECT count(*) FROM analytics.projection_state
            WHERE dataset_revision_id = golden_revision_id AND status = 'ready') <> 6 THEN
        RAISE EXCEPTION 'V6 changed the six-state core projection contract';
    END IF;

    IF NOT has_table_privilege(
        'api_read', 'analytics.comparison_publication_hourly', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'api_read cannot read the V6 comparison input';
    END IF;
END
$golden$;

ROLLBACK;

\echo 'M-Ranked V6 comparison golden assertions passed.'
