-- Deterministic, transactionally published rebuilds for the API-facing core
-- projections.  The caller supplies the dataset revision that defines as_of.

SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';
SET client_min_messages = warning;

CREATE OR REPLACE FUNCTION analytics.observation_quality_rank(p_quality ingest.observation_quality)
RETURNS smallint
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = pg_catalog, ingest, analytics
AS $function$
    SELECT CASE p_quality
        WHEN 'exact' THEN 0
        WHEN 'rounded' THEN 1
        WHEN 'estimated' THEN 2
        WHEN 'unknown' THEN 3
        WHEN 'degraded' THEN 4
        WHEN 'suspected_reset' THEN 5
        WHEN 'invalid' THEN 6
    END::smallint
$function$;

CREATE OR REPLACE FUNCTION analytics.observation_quality_from_rank(p_rank integer)
RETURNS ingest.observation_quality
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog, ingest, analytics
AS $function$
    SELECT CASE coalesce(p_rank, 3)
        WHEN 0 THEN 'exact'
        WHEN 1 THEN 'rounded'
        WHEN 2 THEN 'estimated'
        WHEN 3 THEN 'unknown'
        WHEN 4 THEN 'degraded'
        WHEN 5 THEN 'suspected_reset'
        ELSE 'invalid'
    END::ingest.observation_quality
$function$;

CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    revision_as_of timestamptz;
    newest_revision_id bigint;
    publication_latest_rows bigint;
    publication_hourly_rows bigint;
    institution_daily_rows bigint;
    institution_monthly_rows bigint;
    institution_period_rows bigint;
    comparison_rows bigint;
    publication_hot_days integer;
    publication_hot_hours integer;
BEGIN
    IF p_dataset_revision_id IS NULL THEN
        RAISE EXCEPTION 'dataset revision must not be NULL';
    END IF;

    -- One writer publishes these tables at a time.  The SHARE table lock also
    -- prevents a newer revision from being inserted between the max(id) check
    -- and the final ready-state publication.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('analytics.rebuild_core_projections', 0)
    );
    LOCK TABLE analytics.dataset_revision IN SHARE MODE;

    SELECT committed_at
      INTO revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'dataset revision % does not exist', p_dataset_revision_id;
    END IF;

    SELECT max(id) INTO newest_revision_id FROM analytics.dataset_revision;
    IF newest_revision_id IS DISTINCT FROM p_dataset_revision_id THEN
        RAISE EXCEPTION 'refusing to publish stale revision %; newest revision is %',
            p_dataset_revision_id, newest_revision_id;
    END IF;

    SELECT hot_days
      INTO publication_hot_days
      FROM ops_and_admin.retention_policy
     WHERE data_class = 'publication_metric_snapshot';
    IF publication_hot_days IS NULL OR publication_hot_days < 70 THEN
        RAISE EXCEPTION 'publication hot retention must be at least 70 days during parity';
    END IF;
    publication_hot_hours := publication_hot_days * 24;

    INSERT INTO analytics.projection_state AS state (
        projection_name, dataset_revision_id, status, refreshed_at, row_count, error_code
    )
    SELECT projection_name, p_dataset_revision_id, 'rebuilding',
           transaction_timestamp(), 0, NULL
      FROM unnest(ARRAY[
          'publication_latest',
          'publication_hourly',
          'institution_daily_metrics',
          'institution_monthly_metrics',
          'institution_period_metrics',
          'comparison'
      ]::text[]) AS requested(projection_name)
    ON CONFLICT (projection_name) DO UPDATE SET
        dataset_revision_id = excluded.dataset_revision_id,
        status = excluded.status,
        refreshed_at = excluded.refreshed_at,
        row_count = excluded.row_count,
        error_code = NULL;

    -- publication_latest deliberately ignores synthetic and invalid rows.
    -- Each metric is selected independently, so a newer unsupported/NULL MAX
    -- comments observation cannot erase the last usable comments observation.
    DELETE FROM analytics.publication_latest;

    INSERT INTO analytics.publication_latest (
        publication_id, institution_id, platform_account_id, platform, observed_at,
        views_count, views_observed_at, views_quality,
        reactions_count, reactions_observed_at, reactions_quality,
        comments_count, comments_observed_at, comments_quality,
        shares_count, shares_observed_at, shares_quality,
        quality, interval_uncertain, synthetic, history_completeness,
        source_snapshot_refs, dataset_revision_id, refreshed_at
    )
    SELECT
        publication.id,
        account.institution_id,
        publication.primary_account_id,
        account.platform,
        latest_snapshot.observed_at,
        latest_views.metric_value,
        latest_views.observed_at,
        latest_views.quality,
        latest_reactions.metric_value,
        latest_reactions.observed_at,
        latest_reactions.quality,
        latest_comments.metric_value,
        latest_comments.observed_at,
        latest_comments.quality,
        latest_shares.metric_value,
        latest_shares.observed_at,
        latest_shares.quality,
        latest_snapshot.quality,
        latest_snapshot.interval_uncertain,
        latest_snapshot.synthetic,
        publication.history_completeness,
        jsonb_strip_nulls(jsonb_build_object(
            'latest', latest_snapshot.id,
            'views', latest_views.snapshot_id,
            'reactions', latest_reactions.snapshot_id,
            'comments', latest_comments.snapshot_id,
            'shares', latest_shares.snapshot_id
        )),
        p_dataset_revision_id,
        transaction_timestamp()
    FROM ingest.publication AS publication
    JOIN catalog.platform_account AS account
      ON account.id = publication.primary_account_id
    JOIN LATERAL (
        SELECT snapshot.id, snapshot.observed_at, snapshot.quality,
               snapshot.interval_uncertain, snapshot.synthetic
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_snapshot ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.views_count AS metric_value,
               snapshot.observed_at, snapshot.quality
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.views_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_views ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.reactions_count AS metric_value,
               snapshot.observed_at, snapshot.quality
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.reactions_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_reactions ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.comments_count AS metric_value,
               snapshot.observed_at, snapshot.quality
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.comments_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_comments ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.shares_count AS metric_value,
               snapshot.observed_at, snapshot.quality
          FROM ingest.publication_metric_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.shares_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_shares ON true
    WHERE publication.published_at <= revision_as_of;

    GET DIAGNOSTICS publication_latest_rows = ROW_COUNT;

    DELETE FROM analytics.publication_hourly;

    -- Hour offsets are relative to the publication timestamp, matching the
    -- legacy calculation exactly.  A point only sees observations at or
    -- before that target hour. Complete histories may carry the latest known
    -- value forward only through the last real observation and within the
    -- 70-day hot window; no history is extrapolated past collected coverage.
    WITH publication_limits AS (
        SELECT publication.id AS publication_id,
               publication.primary_account_id AS platform_account_id,
               account.institution_id,
               account.platform,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               least(
                   publication_hot_hours,
                   floor(extract(epoch FROM (revision_as_of - publication.published_at)) / 3600)::integer,
                   coalesce(
                       floor(last_real.max_age_seconds::numeric / 3600)::integer,
                       -1
                   )
               ) AS max_hour
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
          LEFT JOIN LATERAL (
              SELECT max(snapshot.age_seconds) AS max_age_seconds
                FROM ingest.publication_metric_snapshot AS snapshot
               WHERE snapshot.publication_id = publication.id
                 AND snapshot.observed_at <= revision_as_of
                 AND NOT snapshot.synthetic
                 AND snapshot.quality <> 'invalid'
          ) AS last_real ON true
         WHERE publication.published_at <= revision_as_of
           AND publication.published_at >
               revision_as_of - make_interval(days => publication_hot_days)
    )
    INSERT INTO analytics.publication_hourly (
        publication_id, hour_offset, hour, institution_id, platform_account_id,
        platform, observed_at, views_count, reactions_count, comments_count,
        shares_count, quality, synthetic, history_completeness,
        interval_uncertain, dataset_revision_id
    )
    SELECT limits.publication_id,
           series.hour_offset,
           limits.published_at + series.hour_offset * interval '1 hour',
           limits.institution_id,
           limits.platform_account_id,
           limits.platform,
           point.observed_at,
           point.views_count,
           point.reactions_count,
           point.comments_count,
           point.shares_count,
           point.quality,
           point.synthetic,
           limits.history_completeness,
           point.interval_uncertain,
           p_dataset_revision_id
      FROM publication_limits AS limits
     CROSS JOIN LATERAL generate_series(0, limits.max_hour) AS series(hour_offset)
      JOIN LATERAL (
          SELECT snapshot.observed_at,
                 snapshot.views_count,
                 snapshot.reactions_count,
                 snapshot.comments_count,
                 snapshot.shares_count,
                 snapshot.quality,
                 snapshot.synthetic,
                 snapshot.interval_uncertain
            FROM ingest.publication_metric_snapshot AS snapshot
           WHERE snapshot.publication_id = limits.publication_id
             AND snapshot.age_seconds <= series.hour_offset * 3600
             AND snapshot.observed_at <=
                 limits.published_at + series.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND (NOT snapshot.synthetic OR limits.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS point ON true;

    GET DIAGNOSTICS publication_hourly_rows = ROW_COUNT;

    DELETE FROM analytics.institution_daily_metrics;

    WITH metric_facts AS (
        SELECT latest.institution_id,
               latest.platform::text::analytics.platform_scope AS platform,
               (publication.published_at AT TIME ZONE 'UTC')::date AS metric_day,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, metric_day, metric_key, metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, 'all'::analytics.platform_scope, metric_day,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT institution_id, platform, metric_day, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM scoped_facts
         GROUP BY institution_id, platform, metric_day, metric_key
    )
    INSERT INTO analytics.institution_daily_metrics (
        institution_id, platform, metric_key, aggregation, metric_day,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id
    )
    SELECT grouped.institution_id,
           grouped.platform,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.metric_day,
           grouped.metric_day::timestamp AT TIME ZONE 'UTC',
           least(
               (grouped.metric_day + 1)::timestamp AT TIME ZONE 'UTC',
               revision_as_of
           ),
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS institution_daily_rows = ROW_COUNT;

    DELETE FROM analytics.institution_monthly_metrics;

    WITH metric_facts AS (
        SELECT latest.institution_id,
               latest.platform::text::analytics.platform_scope AS platform,
               date_trunc('month', publication.published_at AT TIME ZONE 'UTC')::date
                   AS metric_month,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, metric_month, metric_key,
               metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, 'all'::analytics.platform_scope, metric_month,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT institution_id, platform, metric_month, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM scoped_facts
         GROUP BY institution_id, platform, metric_month, metric_key
    )
    INSERT INTO analytics.institution_monthly_metrics (
        institution_id, platform, metric_key, aggregation, metric_month,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id
    )
    SELECT grouped.institution_id,
           grouped.platform,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.metric_month,
           grouped.metric_month::timestamp AT TIME ZONE 'UTC',
           least(
               (grouped.metric_month + interval '1 month')::timestamp AT TIME ZONE 'UTC',
               revision_as_of
           ),
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS institution_monthly_rows = ROW_COUNT;

    DELETE FROM analytics.institution_period_metrics;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), dimensions AS (
        SELECT DISTINCT account.institution_id, account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
        UNION
        SELECT DISTINCT account.institution_id, NULL::catalog.platform_code
          FROM catalog.platform_account AS account
         WHERE account.enabled
    ), metric_keys(metric_key) AS (VALUES
        ('views'::analytics.metric_key),
        ('reactions'::analytics.metric_key),
        ('comments'::analytics.metric_key),
        ('shares'::analytics.metric_key)
    ), aggregations(aggregation) AS (VALUES
        ('sum'::analytics.aggregation_code),
        ('median'::analytics.aggregation_code)
    ), metric_facts AS (
        SELECT latest.institution_id,
               latest.platform,
               publication.published_at,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, published_at,
               metric_key, metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, NULL::catalog.platform_code, published_at,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT fact.institution_id,
               fact.platform,
               period.period_key,
               fact.metric_key,
               count(*) AS publication_count,
               count(fact.metric_value) AS sample_size,
               sum(fact.metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY fact.metric_value)
                   FILTER (WHERE fact.metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(fact.metric_quality))
                   FILTER (WHERE fact.metric_value IS NOT NULL) AS worst_quality_rank
          FROM periods AS period
          JOIN scoped_facts AS fact
            ON fact.published_at > revision_as_of - period.duration
           AND fact.published_at <= revision_as_of
         GROUP BY fact.institution_id, fact.platform, period.period_key, fact.metric_key
    )
    INSERT INTO analytics.institution_period_metrics (
        institution_id, platform, period_key, metric_key, aggregation,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id, refreshed_at
    )
    SELECT dimension.institution_id,
           dimension.platform,
           period.period_key,
           metric_key.metric_key,
           aggregation.aggregation,
           revision_as_of - period.duration,
           revision_as_of,
           CASE
               WHEN coalesce(grouped.publication_count, 0) = 0
                    AND aggregation.aggregation = 'sum' THEN 0::numeric
               WHEN coalesce(grouped.sample_size, 0) = 0 THEN NULL
               WHEN aggregation.aggregation = 'sum' THEN grouped.sum_value
               ELSE round(grouped.median_value, 0)
           END,
           coalesce(grouped.sample_size, 0)::integer,
           CASE
               WHEN coalesce(grouped.publication_count, 0) = 0 THEN 0::numeric
               ELSE round(grouped.sample_size::numeric / grouped.publication_count, 6)
           END,
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM dimensions AS dimension
     CROSS JOIN periods AS period
     CROSS JOIN metric_keys AS metric_key
     CROSS JOIN aggregations AS aggregation
      LEFT JOIN grouped
        ON grouped.institution_id = dimension.institution_id
       AND grouped.platform IS NOT DISTINCT FROM dimension.platform
       AND grouped.period_key = period.period_key
       AND grouped.metric_key = metric_key.metric_key;

    GET DIAGNOSTICS institution_period_rows = ROW_COUNT;

    DELETE FROM analytics.comparison_cohort;

    -- The five legacy UI horizons get immutable fixed cohorts. Cohort UUIDs
    -- are stable for a revision/platform/horizon, which makes rebuild output
    -- deterministic and keeps retries free of duplicate logical cohorts.
    WITH horizons(horizon_hours) AS (VALUES (24), (48), (72), (168), (336)),
    variants(include_partial, required_start_hour) AS (
        VALUES (false, 0), (true, 1)
    ),
    platforms(platform) AS (
        SELECT DISTINCT account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
    )
    INSERT INTO analytics.comparison_cohort (
        id, platform, horizon_seconds, as_of, filter_definition,
        sample_size, dataset_revision_id, created_at
    )
    SELECT md5(
               'comparison|' || p_dataset_revision_id::text || '|' ||
               platform.platform::text || '|' || horizon.horizon_hours::text || '|' ||
               variant.include_partial::text
           )::uuid,
           platform.platform,
           horizon.horizon_hours * 3600,
           revision_as_of,
           jsonb_build_object(
               'fixed_cohort', true,
               'include_partial', variant.include_partial,
               'required_start_hour', variant.required_start_hour,
               'required_end_hour', horizon.horizon_hours,
               'hourly_hot_days', publication_hot_days
           ),
           0,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM platforms AS platform
     CROSS JOIN horizons AS horizon
     CROSS JOIN variants AS variant;

    INSERT INTO analytics.comparison_cohort_member (
        cohort_id, publication_id, institution_id
    )
    SELECT cohort.id,
           start_point.publication_id,
           start_point.institution_id
      FROM analytics.comparison_cohort AS cohort
      JOIN analytics.publication_hourly AS start_point
        ON start_point.platform = cohort.platform
       AND start_point.dataset_revision_id = cohort.dataset_revision_id
       AND start_point.hour_offset =
           (cohort.filter_definition->>'required_start_hour')::integer
       AND (
           (cohort.filter_definition->>'include_partial')::boolean
           OR start_point.history_completeness = 'complete'
       )
      JOIN analytics.publication_hourly AS end_point
        ON end_point.publication_id = start_point.publication_id
       AND end_point.dataset_revision_id = start_point.dataset_revision_id
       AND end_point.hour_offset = cohort.horizon_seconds / 3600
     WHERE cohort.dataset_revision_id = p_dataset_revision_id;

    UPDATE analytics.comparison_cohort AS cohort
       SET sample_size = member_count.sample_size
      FROM (
          SELECT member.cohort_id, count(*)::integer AS sample_size
            FROM analytics.comparison_cohort_member AS member
            JOIN analytics.comparison_cohort AS selected
              ON selected.id = member.cohort_id
             AND selected.dataset_revision_id = p_dataset_revision_id
           GROUP BY member.cohort_id
      ) AS member_count
     WHERE cohort.id = member_count.cohort_id;

    WITH metric_facts AS (
        SELECT member.cohort_id,
               member.institution_id,
               hourly.hour_offset,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_cohort AS cohort ON cohort.id = member.cohort_id
          JOIN analytics.publication_hourly AS hourly
           ON hourly.publication_id = member.publication_id
           AND hourly.dataset_revision_id = cohort.dataset_revision_id
           AND hourly.hour_offset >=
               (cohort.filter_definition->>'required_start_hour')::integer
           AND hourly.hour_offset <= cohort.horizon_seconds / 3600
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, hourly.views_count, hourly.quality),
             ('reactions'::analytics.metric_key, hourly.reactions_count, hourly.quality),
             ('comments'::analytics.metric_key, hourly.comments_count, hourly.quality),
             ('shares'::analytics.metric_key, hourly.shares_count, hourly.quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE cohort.dataset_revision_id = p_dataset_revision_id
    ), grouped AS (
        SELECT cohort_id, institution_id, hour_offset, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM metric_facts
         GROUP BY cohort_id, institution_id, hour_offset, metric_key
    )
    INSERT INTO analytics.comparison_metric_point (
        cohort_id, institution_id, metric_key, aggregation, hour_offset,
        value, sample_size, coverage, quality
    )
    SELECT grouped.cohort_id,
           grouped.institution_id,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.hour_offset,
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank)
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS comparison_rows = ROW_COUNT;

    INSERT INTO analytics.projection_state AS state (
        projection_name, dataset_revision_id, status, refreshed_at, row_count, error_code
    ) VALUES
        ('publication_latest', p_dataset_revision_id, 'ready', transaction_timestamp(),
            publication_latest_rows, NULL),
        ('publication_hourly', p_dataset_revision_id, 'ready', transaction_timestamp(),
            publication_hourly_rows, NULL),
        ('institution_daily_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_daily_rows, NULL),
        ('institution_monthly_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_monthly_rows, NULL),
        ('institution_period_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_period_rows, NULL),
        ('comparison', p_dataset_revision_id, 'ready', transaction_timestamp(),
            comparison_rows, NULL)
    ON CONFLICT (projection_name) DO UPDATE SET
        dataset_revision_id = excluded.dataset_revision_id,
        status = excluded.status,
        refreshed_at = excluded.refreshed_at,
        row_count = excluded.row_count,
        error_code = NULL;

    RETURN jsonb_build_object(
        'dataset_revision_id', p_dataset_revision_id,
        'publication_latest', publication_latest_rows,
        'publication_hourly', publication_hourly_rows,
        'institution_daily_metrics', institution_daily_rows,
        'institution_monthly_metrics', institution_monthly_rows,
        'institution_period_metrics', institution_period_rows,
        'comparison', comparison_rows
    );
END
$function$;

REVOKE ALL ON FUNCTION analytics.observation_quality_rank(ingest.observation_quality)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics.observation_quality_from_rank(integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO migration_bridge, maintenance;

RESET ROLE;
