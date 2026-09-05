\set ON_ERROR_STOP on

-- Deterministic semantic proof for V5. Run as the local bootstrap role after
-- Flyway has applied V1 through V5. Every fixture write is rolled back.

BEGIN;
SET LOCAL ROLE migration_owner;

INSERT INTO catalog.institution (id, canonical_name, short_name)
VALUES
    (
        '55555555-5555-4555-8555-555555555501',
        'Period activity golden university',
        'Period golden'
    ),
    (
        '55555555-5555-4555-8555-555555555502',
        'Period activity no-account university',
        'Period no account'
    );

INSERT INTO catalog.legacy_entity_alias (
    entity_type, legacy_id, target_uuid, legacy_route
) VALUES
    (
        'institutions', 955555555501,
        '55555555-5555-4555-8555-555555555501',
        '/institutions/955555555501'
    ),
    (
        'institutions', 955555555502,
        '55555555-5555-4555-8555-555555555502',
        '/institutions/955555555502'
    ),
    (
        'channels', 955555555511,
        '55555555-5555-4555-8555-555555555511',
        '/channels/955555555511'
    ),
    (
        'platform_accounts', 955555555512,
        '55555555-5555-4555-8555-555555555512',
        '/platform-accounts/955555555512'
    ),
    (
        'platform_accounts', 955555555513,
        '55555555-5555-4555-8555-555555555513',
        '/platform-accounts/955555555513'
    );

INSERT INTO catalog.platform_account (
    id, institution_id, platform, canonical_external_id, current_title,
    current_url, access_mode, enabled
) VALUES
    (
        '55555555-5555-4555-8555-555555555511',
        '55555555-5555-4555-8555-555555555501',
        'telegram', 'period-golden-telegram', 'Period golden Telegram',
        'https://t.me/period_golden', 'public_web', true
    ),
    (
        '55555555-5555-4555-8555-555555555512',
        '55555555-5555-4555-8555-555555555501',
        'vk', 'period-golden-vk', 'Period golden VK',
        'https://vk.com/period_golden', 'official_api', true
    ),
    (
        '55555555-5555-4555-8555-555555555513',
        '55555555-5555-4555-8555-555555555501',
        'max', 'period-golden-max', 'Period golden MAX',
        'https://max.ru/period_golden', 'user_session', true
    );

INSERT INTO ingest.collection_run (
    id, platform, partition_key, collector_version, scheduled_at, started_at,
    completed_at, status, correlation_id
) VALUES
    (
        '55555555-5555-4555-8555-555555555521',
        'telegram', 'period-golden', 'period-golden-v1',
        '2026-09-03T11:58:00Z', '2026-09-03T11:59:00Z',
        '2026-09-03T12:00:00Z', 'succeeded',
        '55555555-5555-4555-8555-555555555531'
    ),
    (
        '55555555-5555-4555-8555-555555555522',
        'vk', 'period-golden', 'period-golden-v1',
        '2026-09-03T11:58:00Z', '2026-09-03T11:59:00Z',
        '2026-09-03T12:00:00Z', 'succeeded',
        '55555555-5555-4555-8555-555555555532'
    ),
    (
        '55555555-5555-4555-8555-555555555523',
        'telegram', 'period-golden-future', 'period-golden-v1',
        '2026-09-03T11:54:00Z', '2026-09-03T11:55:00Z',
        '2026-09-03T13:00:00Z', 'failed',
        '55555555-5555-4555-8555-555555555534'
    );

INSERT INTO ingest.collection_account_result (
    collection_run_id, platform_account_id, started_at, completed_at,
    status, sanitized_error_code
) VALUES (
    '55555555-5555-4555-8555-555555555523',
    '55555555-5555-4555-8555-555555555511',
    '2026-09-03T11:55:00Z', '2026-09-03T13:00:00Z',
    'failed', 'future_failure_must_not_leak'
);

INSERT INTO ingest.account_metric_snapshot (
    platform_account_id, collection_run_id, observed_at, collected_at,
    subscriber_count, subscriber_display, quality, source_fingerprint, created_at
) VALUES
    (
        '55555555-5555-4555-8555-555555555511',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-03T11:00:00Z', '2026-09-03T11:01:00Z',
        100, '100', 'exact', repeat('e', 64), '2026-09-03T11:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555511',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-03T11:30:00Z', '2026-09-03T11:31:00Z',
        999, '999', 'invalid', repeat('f', 64), '2026-09-03T11:31:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555511',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-03T11:45:00Z', '2026-09-03T12:30:00Z',
        888, '888', 'exact', repeat('0', 64), '2026-09-03T12:30:00Z'
    );

INSERT INTO ops_and_admin.operational_checkpoint (
    id, checkpoint_key, scope_type, scope_id, value, source_observed_at, updated_at
) VALUES (
    '55555555-5555-4555-8555-555555555524', 'last_checked_at', 'account',
    '55555555-5555-4555-8555-555555555511',
    '"2026-09-03T11:50:00Z"', '2026-09-03T11:50:00Z', '2026-09-03T11:50:00Z'
);

INSERT INTO rating.official_rating_observation (
    id, institution_id, category, period, rank, score,
    source_url, source_hash, fetched_at
) VALUES
    (
        '55555555-5555-4555-8555-555555555525',
        '55555555-5555-4555-8555-555555555501',
        'telegram', '2026', 7, 91.5,
        'https://example.test/rating/telegram', repeat('a', 64),
        '2026-09-03T11:40:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555526',
        '55555555-5555-4555-8555-555555555501',
        'social', '2026', 3, 97.5,
        'https://example.test/rating/social', repeat('b', 64),
        '2026-09-03T11:40:00Z'
    );

-- Telegram fixtures:
--   541: old publication with an observation exactly at the left boundary;
--   542: new publication whose explicit zero baseline is allowed;
--   543: old publication with only one point (not a measurable interval);
--   544: old publication with a real negative views delta;
--   545: new publication without baseline permission (one point is excluded).
-- VK fixture 546 proves that its legacy completeness gate, rather than the
-- Telegram-only explicit flag, permits a publication-time zero baseline; 547
-- proves forced-incomplete history cannot use that baseline.
INSERT INTO ingest.publication (
    id, primary_account_id, published_at, discovered_at,
    first_observation_age_seconds, publication_type, history_completeness,
    synthetic_baseline_allowed, quality_flags, created_at
) VALUES
    (
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555511',
        '2026-08-20T12:00:00Z', '2026-08-20T12:01:00Z', 60,
        'post', 'complete', true, '{"fixture":"old-open-left"}',
        '2026-08-20T12:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555542',
        '55555555-5555-4555-8555-555555555511',
        '2026-09-02T14:00:00Z', '2026-09-02T14:01:00Z', 60,
        'post', 'complete', true, '{"fixture":"new-zero-baseline"}',
        '2026-09-02T14:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555543',
        '55555555-5555-4555-8555-555555555511',
        '2026-08-20T12:00:00Z', '2026-08-20T12:01:00Z', 60,
        'post', 'complete', true, '{"fixture":"old-one-point"}',
        '2026-08-20T12:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555544',
        '55555555-5555-4555-8555-555555555511',
        '2026-08-20T12:00:00Z', '2026-08-20T12:01:00Z', 60,
        'post', 'complete', true, '{"fixture":"negative-delta"}',
        '2026-08-20T12:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555545',
        '55555555-5555-4555-8555-555555555511',
        '2026-09-02T16:00:00Z', '2026-09-02T16:01:00Z', 60,
        'post', 'complete', false, '{"fixture":"baseline-denied"}',
        '2026-09-02T16:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555546',
        '55555555-5555-4555-8555-555555555512',
        '2026-09-02T17:00:00Z', '2026-09-02T17:01:00Z', 60,
        'post', 'complete', false, '{"fixture":"platform-completeness"}',
        '2026-09-02T17:01:00Z'
    ),
    (
        '55555555-5555-4555-8555-555555555547',
        '55555555-5555-4555-8555-555555555512',
        '2026-09-02T19:00:00Z', '2026-09-02T20:00:00Z', 3600,
        'post', 'forced_incomplete', false,
        '{"fixture":"platform-forced-incomplete"}',
        '2026-09-02T20:00:00Z'
    );

SELECT ops_and_admin.ensure_publication_metric_partition('2026-08-01'::date);
SELECT ops_and_admin.ensure_publication_metric_partition('2026-09-01'::date);

INSERT INTO ingest.publication_metric_snapshot (
    published_month, id, publication_id, collection_run_id, observed_at,
    collected_at, age_seconds, sampling_bucket, views_count, reactions_count,
    comments_count, shares_count, quality, interval_uncertain, synthetic,
    metric_semantics_version, capability_version, source_fingerprint, created_at
) VALUES
    -- Previous-window observations make the fixture capable of detecting an
    -- accidental cumulative/current-vs-previous calculation.
    ('2026-08-01', 955555555501,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-01T13:00:00Z', '2026-09-01T13:01:00Z', 1040400, 1,
        500, 50, NULL, 0, 'exact', false, false, 1, 1,
        repeat('1', 64), '2026-09-01T13:01:00Z'),
    -- Exactly at 1d.window_start: excluded by the open-left contract.
    ('2026-08-01', 955555555502,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T12:00:00Z', '2026-09-02T12:01:00Z', 1123200, 2,
        960, 96, NULL, 1, 'exact', false, false, 1, 1,
        repeat('2', 64), '2026-09-02T12:01:00Z'),
    ('2026-08-01', 955555555503,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T13:00:00Z', '2026-09-02T13:01:00Z', 1126800, 3,
        100, 100, NULL, 1, 'exact', false, false, 1, 1,
        repeat('3', 64), '2026-09-02T13:01:00Z'),
    ('2026-08-01', 955555555504,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-03T11:00:00Z', '2026-09-03T11:01:00Z', 1206000, 4,
        140, 104, NULL, 2, 'exact', false, false, 1, 1,
        repeat('4', 64), '2026-09-03T11:01:00Z'),
    -- Neither a synthetic point nor an invalid real point may become a
    -- period endpoint.
    ('2026-08-01', 955555555511,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T12:30:00Z', '2026-09-02T12:31:00Z', 0, -11,
        9999, 9999, NULL, 9999, 'exact', false, true, 1, 1,
        repeat('b', 64), '2026-09-02T12:31:00Z'),
    ('2026-08-01', 955555555512,
        '55555555-5555-4555-8555-555555555541',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-03T11:30:00Z', '2026-09-03T11:31:00Z', 1207800, 12,
        8888, 8888, NULL, 8888, 'invalid', false, false, 1, 1,
        repeat('c', 64), '2026-09-03T11:31:00Z'),
    -- One real point plus an explicit zero baseline: reactions delta = 1.
    ('2026-09-01', 955555555505,
        '55555555-5555-4555-8555-555555555542',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T15:00:00Z', '2026-09-02T15:01:00Z', 3600, 5,
        NULL, 1, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('5', 64), '2026-09-02T15:01:00Z'),
    -- Old one-point publications have no interval and must not contribute 999.
    ('2026-08-01', 955555555506,
        '55555555-5555-4555-8555-555555555543',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T16:00:00Z', '2026-09-02T16:01:00Z', 1137600, 6,
        999, 999, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('6', 64), '2026-09-02T16:01:00Z'),
    ('2026-08-01', 955555555507,
        '55555555-5555-4555-8555-555555555544',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T17:00:00Z', '2026-09-02T17:01:00Z', 1141200, 7,
        20, NULL, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('7', 64), '2026-09-02T17:01:00Z'),
    ('2026-08-01', 955555555508,
        '55555555-5555-4555-8555-555555555544',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T18:00:00Z', '2026-09-02T18:01:00Z', 1144800, 8,
        15, NULL, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('8', 64), '2026-09-02T18:01:00Z'),
    -- Complete is not enough for Telegram without explicit baseline permission.
    ('2026-09-01', 955555555509,
        '55555555-5555-4555-8555-555555555545',
        '55555555-5555-4555-8555-555555555521',
        '2026-09-02T17:00:00Z', '2026-09-02T17:01:00Z', 3600, 9,
        777, 777, NULL, NULL, 'exact', false, false, 1, 1,
        repeat('9', 64), '2026-09-02T17:01:00Z'),
    -- Non-Telegram legacy collectors encode their first-age gate as complete.
    ('2026-09-01', 955555555510,
        '55555555-5555-4555-8555-555555555546',
        '55555555-5555-4555-8555-555555555522',
        '2026-09-02T18:00:00Z', '2026-09-02T18:01:00Z', 3600, 10,
        70, 7, NULL, 2, 'exact', false, false, 1, 1,
        repeat('a', 64), '2026-09-02T18:01:00Z'),
    ('2026-09-01', 955555555513,
        '55555555-5555-4555-8555-555555555547',
        '55555555-5555-4555-8555-555555555522',
        '2026-09-02T20:00:00Z', '2026-09-02T20:01:00Z', 3600, 13,
        700, 70, NULL, 20, 'exact', false, false, 1, 1,
        repeat('d', 64), '2026-09-02T20:01:00Z');

INSERT INTO analytics.dataset_revision (
    committed_at, cause, correlation_id, source_run_id, metadata
) VALUES (
    '2026-09-03T12:00:00Z', 'analytics',
    '55555555-5555-4555-8555-555555555533',
    '55555555-5555-4555-8555-555555555521',
    '{"fixture":"period-activity-golden"}'
) RETURNING id AS revision_id
\gset period_golden_

DO $golden$
DECLARE
    golden_revision_id bigint;
    first_result jsonb;
    second_result jsonb;
    first_rows jsonb;
    second_rows jsonb;
    first_overview_rows jsonb;
    second_overview_rows jsonb;
BEGIN
    SELECT id
      INTO STRICT golden_revision_id
      FROM analytics.dataset_revision
     WHERE correlation_id = '55555555-5555-4555-8555-555555555533';

    first_result := analytics.rebuild_core_projections(
        golden_revision_id
    );

    SELECT jsonb_agg(to_jsonb(metric) - 'id' - 'refreshed_at'
                     ORDER BY metric.platform NULLS LAST, metric.period_key,
                              metric.metric_key, metric.aggregation)
      INTO first_rows
      FROM analytics.institution_period_metrics AS metric
     WHERE metric.institution_id = '55555555-5555-4555-8555-555555555501';

    SELECT jsonb_build_object(
               'cards', (
                   SELECT jsonb_agg(to_jsonb(card) - 'refreshed_at'
                                    ORDER BY card.platform, card.period_key, card.entity_id)
                     FROM analytics.legacy_overview_card AS card
                    WHERE card.institution_id = '55555555-5555-4555-8555-555555555501'
               ),
               'accounts', (
                   SELECT jsonb_agg(to_jsonb(account)
                                    ORDER BY account.platform, account.entity_id, account.position)
                     FROM analytics.legacy_overview_account AS account
                    WHERE account.account_id IN (
                        '55555555-5555-4555-8555-555555555511',
                        '55555555-5555-4555-8555-555555555512',
                        '55555555-5555-4555-8555-555555555513'
                    )
               )
           )
      INTO first_overview_rows;

    second_result := analytics.rebuild_core_projections(
        golden_revision_id
    );

    SELECT jsonb_agg(to_jsonb(metric) - 'id' - 'refreshed_at'
                     ORDER BY metric.platform NULLS LAST, metric.period_key,
                              metric.metric_key, metric.aggregation)
      INTO second_rows
      FROM analytics.institution_period_metrics AS metric
     WHERE metric.institution_id = '55555555-5555-4555-8555-555555555501';

    SELECT jsonb_build_object(
               'cards', (
                   SELECT jsonb_agg(to_jsonb(card) - 'refreshed_at'
                                    ORDER BY card.platform, card.period_key, card.entity_id)
                     FROM analytics.legacy_overview_card AS card
                    WHERE card.institution_id = '55555555-5555-4555-8555-555555555501'
               ),
               'accounts', (
                   SELECT jsonb_agg(to_jsonb(account)
                                    ORDER BY account.platform, account.entity_id, account.position)
                     FROM analytics.legacy_overview_account AS account
                    WHERE account.account_id IN (
                        '55555555-5555-4555-8555-555555555511',
                        '55555555-5555-4555-8555-555555555512',
                        '55555555-5555-4555-8555-555555555513'
                    )
               )
           )
      INTO second_overview_rows;

    IF first_result->>'institution_period_semantics_version' <> '2'
       OR second_result->>'institution_period_semantics_version' <> '2' THEN
        RAISE EXCEPTION 'V5 rebuild did not identify period semantics version 2';
    END IF;
    IF first_rows IS DISTINCT FROM second_rows THEN
        RAISE EXCEPTION 'V5 period rebuild is not idempotent';
    END IF;
    IF first_result->>'legacy_overview_semantics_version' <> '1'
       OR second_result->>'legacy_overview_semantics_version' <> '1' THEN
        RAISE EXCEPTION 'V8 rebuild did not identify overview semantics version 1';
    END IF;
    IF first_overview_rows IS DISTINCT FROM second_overview_rows THEN
        RAISE EXCEPTION 'V8 overview rebuild is not idempotent';
    END IF;
END
$golden$;

DO $assertions$
DECLARE
    golden_revision_id bigint;
    golden_institution_id uuid := '55555555-5555-4555-8555-555555555501';
BEGIN
    SELECT id
      INTO STRICT golden_revision_id
      FROM analytics.dataset_revision
     WHERE correlation_id = '55555555-5555-4555-8555-555555555533';

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'telegram' AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'sum'
           AND window_start = '2026-09-02T12:00:00Z'
           AND window_end = '2026-09-03T12:00:00Z'
           AND value = 5 AND sample_size = 2 AND coverage = 0.4
           AND quality = 'exact' AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'activity window, boundary, synthetic/invalid exclusion, one-point exclusion, or baseline gate failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'telegram' AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'median'
           AND value = 3 AND sample_size = 2 AND coverage = 0.4
           AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'even median did not use Python floor(median + 0.5)';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'telegram' AND period_key = '1d'
           AND metric_key = 'views' AND aggregation = 'sum'
           AND value = 35 AND sample_size = 2 AND coverage = 0.4
           AND dataset_revision_id = golden_revision_id
    ) OR NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'telegram' AND period_key = '1d'
           AND metric_key = 'views' AND aggregation = 'median'
           AND value = 18 AND sample_size = 2 AND coverage = 0.4
           AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'negative deltas or exact half-up median failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'telegram' AND period_key = '1d'
           AND metric_key = 'comments' AND aggregation = 'sum'
           AND value IS NULL AND sample_size = 0 AND coverage = 0
           AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'NULL metric was converted to zero';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'vk' AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'sum'
           AND value = 7 AND sample_size = 1 AND coverage = 0.5
           AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'non-Telegram complete/forced-incomplete baseline gates failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform = 'max' AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'sum'
           AND value IS NULL AND sample_size = 0 AND coverage = 0
           AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'empty platform sum was converted to zero';
    END IF;

    IF EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform IS NULL AND value IS NOT NULL
           AND dataset_revision_id = golden_revision_id
    ) OR NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_period_metrics.institution_id = golden_institution_id
           AND platform IS NULL AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'sum'
           AND value IS NULL AND sample_size = 0 AND coverage = 0.75
           AND quality = 'unknown' AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'all-platform rows combined counters, mislabeled accounts as metric samples, or lost platform coverage';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM analytics.institution_period_metrics
         WHERE institution_id = '55555555-5555-4555-8555-555555555502'
           AND platform IS NULL AND period_key = '1d'
           AND metric_key = 'reactions' AND aggregation = 'sum'
           AND value IS NULL AND sample_size = 0 AND coverage = 0
           AND quality = 'unknown' AND dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'active institution without accounts disappeared from all-platform coverage';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM analytics.legacy_overview_card AS card
         WHERE card.dataset_revision_id = golden_revision_id
           AND card.platform = 'telegram'
           AND card.period_key = '1d'
           AND card.entity_id = '55555555-5555-4555-8555-555555555511'
           AND card.entity_type = 'channels'
           AND card.legacy_id = 955555555511
           AND card.institution_legacy_id = 955555555501
           AND card.account_count = 1
           AND card.enabled_account_count = 1
           AND card.subscriber_count = 100
           AND card.last_checked_at = '2026-09-03T11:55:00Z'
           AND card.last_error_code IS NULL
           AND card.status_code = 'polling'
           AND card.rating_rank = 7
           AND card.total_publication_count = 5
           AND card.activity_publication_count = 3
           AND card.new_publication_count = 2
           AND card.total_reactions = 5
           AND card.median_reactions = 3
           AND card.previous_total_reactions = 46
           AND card.previous_median_reactions = 46
           AND card.delta_total_reactions = -41
           AND card.delta_median_reactions = -43
           AND card.total_views = 35
           AND card.median_views = 18
           AND card.previous_total_views = 460
           AND card.previous_median_views = 460
           AND card.delta_total_views = -425
           AND card.delta_median_views = -442
    ) THEN
        RAISE EXCEPTION 'V8 Telegram card lost exact current/previous activity, aliases, rating, or revision-pinned account state';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM analytics.legacy_overview_account AS account
         WHERE account.dataset_revision_id = golden_revision_id
           AND account.platform = 'telegram'
           AND account.entity_id = '55555555-5555-4555-8555-555555555511'
           AND account.account_id = '55555555-5555-4555-8555-555555555511'
           AND account.legacy_id = 955555555511
           AND account.subscriber_count = 100
           AND account.subscriber_observed_at = '2026-09-03T11:00:00Z'
           AND account.latest_poll_started_at = '2026-09-03T11:55:00Z'
           AND account.latest_poll_completed_at IS NULL
           AND account.latest_poll_status = 'running'
           AND account.latest_error_code IS NULL
    ) THEN
        RAISE EXCEPTION 'V8 account card leaked an invalid/late-collected metric or future collection completion';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM analytics.legacy_overview_card AS card
         WHERE card.dataset_revision_id = golden_revision_id
           AND card.platform = 'all'
           AND card.period_key = '1d'
           AND card.institution_id = golden_institution_id
           AND card.account_count = 3
           AND card.enabled_account_count = 3
           AND card.connected_platform_count = 3
           AND card.rating_rank = 3
           AND card.status_code = 'connected'
           AND card.total_reactions IS NULL
           AND card.total_views IS NULL
    ) OR NOT EXISTS (
        SELECT 1
          FROM analytics.legacy_overview_card AS card
         WHERE card.dataset_revision_id = golden_revision_id
           AND card.platform = 'all'
           AND card.period_key = '1d'
           AND card.institution_id = '55555555-5555-4555-8555-555555555502'
           AND card.account_count = 0
           AND card.connected_platform_count = 0
           AND card.status_code = 'no_account'
    ) THEN
        RAISE EXCEPTION 'V8 all-platform coverage/rating/no-account semantics failed';
    END IF;

    IF (SELECT count(*) FROM analytics.legacy_overview_card
         WHERE dataset_revision_id = golden_revision_id) <> 36
       OR (SELECT count(*) FROM analytics.legacy_overview_account
            WHERE dataset_revision_id = golden_revision_id) <> 6 THEN
        RAISE EXCEPTION 'V8 overview cardinality is not one card per dimension/period or one account per dimension';
    END IF;

    IF (SELECT count(*) FROM analytics.projection_state) <> 6
       OR (SELECT count(*) FROM analytics.projection_state
            WHERE dataset_revision_id = golden_revision_id AND status = 'ready') <> 6 THEN
        RAISE EXCEPTION 'V8 changed the six-state core projection contract';
    END IF;

    IF NOT has_table_privilege('api_read', 'analytics.legacy_overview_card', 'SELECT')
       OR NOT has_table_privilege('api_read', 'analytics.legacy_overview_account', 'SELECT') THEN
        RAISE EXCEPTION 'api_read cannot read the V8 overview model';
    END IF;

    IF (
        SELECT row_count FROM analytics.projection_state
         WHERE projection_name = 'institution_period_metrics'
           AND dataset_revision_id = golden_revision_id AND status = 'ready'
    ) IS DISTINCT FROM (
        SELECT count(*) FROM analytics.institution_period_metrics
         WHERE dataset_revision_id = golden_revision_id
    ) THEN
        RAISE EXCEPTION 'period projection state row count is stale';
    END IF;

    IF has_function_privilege(
        'migration_bridge', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'maintenance', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) OR has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections_v2(bigint)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'runtime role can bypass the corrected V5 wrapper';
    END IF;

    IF NOT has_function_privilege(
        'migration_bridge', 'analytics.rebuild_core_projections(bigint)', 'EXECUTE'
    ) OR NOT has_function_privilege(
        'maintenance', 'analytics.rebuild_core_projections(bigint)', 'EXECUTE'
    ) OR NOT has_function_privilege(
        'api_write_admin', 'analytics.rebuild_core_projections(bigint)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'corrected V5 wrapper is unavailable to an intended caller';
    END IF;
END
$assertions$;

ROLLBACK;

\echo 'M-Ranked V5 period activity and V8 overview golden assertions passed.'
