-- Restore the legacy overview meaning of a period: activity observed inside
-- the open-left window, not the latest cumulative value of publications that
-- happened to be published inside that window. V1--V4 are immutable.

SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';
SET client_min_messages = warning;

-- Keep the V2 implementation as the private publisher for every other core
-- projection. Runtime roles must only be able to call the corrected wrapper
-- recreated below; otherwise they could publish the obsolete period rows.
ALTER FUNCTION analytics.rebuild_core_projections(bigint)
    RENAME TO rebuild_core_projections_v2;

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v2(bigint)
    FROM PUBLIC, migration_bridge, maintenance, api_write_admin;

CREATE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    institution_period_rows bigint;
BEGIN
    -- V2 validates the newest revision, takes the transaction-scoped publisher
    -- lock, and rebuilds the other five projections. Its lock remains held
    -- while this wrapper replaces the obsolete period projection.
    base_result := analytics.rebuild_core_projections_v2(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.institution_period_metrics;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), metric_keys(metric_key) AS (VALUES
        ('views'::analytics.metric_key),
        ('reactions'::analytics.metric_key),
        ('comments'::analytics.metric_key),
        ('shares'::analytics.metric_key)
    ), aggregations(aggregation) AS (VALUES
        ('sum'::analytics.aggregation_code),
        ('median'::analytics.aggregation_code)
    ), platform_dimensions AS (
        SELECT DISTINCT account.institution_id, account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
    ), all_dimensions AS (
        -- platform IS NULL is catalog coverage only. Cross-platform counters
        -- are intentionally never summed or ranked as comparable quantities,
        -- and metric sample_size must not be overloaded with account count.
        SELECT institution.id AS institution_id,
               round(
                   count(DISTINCT account.platform)::numeric /
                   cardinality(enum_range(NULL::catalog.platform_code)),
                   6
               ) AS platform_coverage
          FROM catalog.institution AS institution
          LEFT JOIN catalog.platform_account AS account
            ON account.institution_id = institution.id
           AND account.enabled
         WHERE institution.status = 'active'
         GROUP BY institution.id
    ), window_observations AS (
        SELECT period.period_key,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end,
               account.institution_id,
               account.platform,
               publication.id AS publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               snapshot.published_month AS snapshot_month,
               snapshot.id AS snapshot_id,
               snapshot.views_count,
               snapshot.reactions_count,
               snapshot.comments_count,
               snapshot.shares_count,
               analytics.observation_quality_rank(snapshot.quality) AS quality_rank,
               row_number() OVER (
                   PARTITION BY period.period_key, publication.id
                   ORDER BY snapshot.observed_at, snapshot.published_month, snapshot.id
               ) AS first_position,
               row_number() OVER (
                   PARTITION BY period.period_key, publication.id
                   ORDER BY snapshot.observed_at DESC,
                            snapshot.published_month DESC, snapshot.id DESC
               ) AS latest_position,
               count(*) OVER (
                   PARTITION BY period.period_key, publication.id
               ) AS observation_count
          FROM periods AS period
          JOIN ingest.publication AS publication
            ON publication.published_at <= revision_as_of
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
           AND account.enabled
          JOIN ingest.publication_metric_snapshot AS snapshot
            ON snapshot.publication_id = publication.id
           AND snapshot.observed_at > revision_as_of - period.duration
           AND snapshot.observed_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
    ), publication_bounds AS (
        SELECT observation.period_key,
               observation.window_start,
               observation.window_end,
               observation.institution_id,
               observation.platform,
               observation.publication_id,
               observation.published_at,
               observation.history_completeness,
               observation.synthetic_baseline_allowed,
               max(observation.observation_count) AS observation_count,
               max(observation.views_count)
                   FILTER (WHERE observation.first_position = 1) AS first_views,
               max(observation.views_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_views,
               max(observation.reactions_count)
                   FILTER (WHERE observation.first_position = 1) AS first_reactions,
               max(observation.reactions_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_reactions,
               max(observation.comments_count)
                   FILTER (WHERE observation.first_position = 1) AS first_comments,
               max(observation.comments_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_comments,
               max(observation.shares_count)
                   FILTER (WHERE observation.first_position = 1) AS first_shares,
               max(observation.shares_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_shares,
               max(observation.quality_rank)
                   FILTER (WHERE observation.first_position = 1) AS first_quality_rank,
               max(observation.quality_rank)
                   FILTER (WHERE observation.latest_position = 1) AS latest_quality_rank
          FROM window_observations AS observation
         GROUP BY observation.period_key, observation.window_start,
                  observation.window_end, observation.institution_id,
                  observation.platform, observation.publication_id,
                  observation.published_at, observation.history_completeness,
                  observation.synthetic_baseline_allowed
    ), publication_metric_delta AS (
        SELECT bounds.period_key,
               bounds.window_start,
               bounds.window_end,
               bounds.institution_id,
               bounds.platform,
               bounds.publication_id,
               metric.metric_key,
               CASE
                   WHEN metric.latest_value IS NULL THEN NULL
                   -- Telegram carried an explicit legacy
                   -- baseline_from_publication decision. The other legacy
                   -- collectors represented the same age/completeness gate in
                   -- history_completeness instead of a baseline column.
                   WHEN bounds.published_at >= bounds.window_start
                        AND (
                            (bounds.platform = 'telegram'
                             AND bounds.synthetic_baseline_allowed)
                            OR
                            (bounds.platform <> 'telegram'
                             AND bounds.history_completeness = 'complete')
                        )
                       THEN metric.latest_value::numeric
                   WHEN bounds.observation_count >= 2
                        AND metric.first_value IS NOT NULL
                       THEN metric.latest_value::numeric - metric.first_value::numeric
                   ELSE NULL
               END AS delta_value,
               greatest(bounds.first_quality_rank, bounds.latest_quality_rank)
                   AS delta_quality_rank
          FROM publication_bounds AS bounds
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key,
                 bounds.first_views, bounds.latest_views),
             ('reactions'::analytics.metric_key,
                 bounds.first_reactions, bounds.latest_reactions),
             ('comments'::analytics.metric_key,
                 bounds.first_comments, bounds.latest_comments),
             ('shares'::analytics.metric_key,
                 bounds.first_shares, bounds.latest_shares)
         ) AS metric(metric_key, first_value, latest_value)
    ), candidates AS (
        SELECT bounds.institution_id,
               bounds.platform,
               bounds.period_key,
               count(*)::integer AS publication_count
          FROM publication_bounds AS bounds
         GROUP BY bounds.institution_id, bounds.platform, bounds.period_key
    ), ranked_delta AS (
        SELECT delta.*,
               row_number() OVER (
                   PARTITION BY delta.institution_id, delta.platform,
                                delta.period_key, delta.metric_key
                   ORDER BY delta.delta_value, delta.publication_id
               ) AS rank_position,
               count(*) OVER (
                   PARTITION BY delta.institution_id, delta.platform,
                                delta.period_key, delta.metric_key
               ) AS sample_size
          FROM publication_metric_delta AS delta
         WHERE delta.delta_value IS NOT NULL
    ), grouped AS (
        SELECT delta.institution_id,
               delta.platform,
               delta.period_key,
               delta.metric_key,
               max(delta.sample_size)::integer AS sample_size,
               sum(delta.delta_value) AS sum_value,
               floor(
                   avg(delta.delta_value) FILTER (
                       WHERE delta.rank_position IN (
                           (delta.sample_size + 1) / 2,
                           (delta.sample_size + 2) / 2
                       )
                   ) + 0.5
               ) AS median_value,
               max(delta.delta_quality_rank) AS worst_quality_rank
          FROM ranked_delta AS delta
         GROUP BY delta.institution_id, delta.platform,
                  delta.period_key, delta.metric_key
    ), replacement_rows AS (
        SELECT dimension.institution_id,
               dimension.platform,
               period.period_key,
               metric.metric_key,
               aggregation.aggregation,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end,
               CASE aggregation.aggregation
                   WHEN 'sum' THEN grouped.sum_value
                   ELSE grouped.median_value
               END AS value,
               coalesce(grouped.sample_size, 0) AS sample_size,
               CASE
                   WHEN coalesce(candidate.publication_count, 0) = 0 THEN 0::numeric
                   ELSE round(
                       coalesce(grouped.sample_size, 0)::numeric /
                       candidate.publication_count,
                       6
                   )
               END AS coverage,
               analytics.observation_quality_from_rank(grouped.worst_quality_rank)
                   AS quality
          FROM platform_dimensions AS dimension
         CROSS JOIN periods AS period
         CROSS JOIN metric_keys AS metric
         CROSS JOIN aggregations AS aggregation
          LEFT JOIN candidates AS candidate
            ON candidate.institution_id = dimension.institution_id
           AND candidate.platform = dimension.platform
           AND candidate.period_key = period.period_key
          LEFT JOIN grouped
            ON grouped.institution_id = dimension.institution_id
           AND grouped.platform = dimension.platform
           AND grouped.period_key = period.period_key
           AND grouped.metric_key = metric.metric_key

        UNION ALL

        SELECT dimension.institution_id,
               NULL::catalog.platform_code,
               period.period_key,
               metric.metric_key,
               aggregation.aggregation,
               revision_as_of - period.duration,
               revision_as_of,
               NULL::numeric,
               0,
               dimension.platform_coverage,
               'unknown'::ingest.observation_quality
          FROM all_dimensions AS dimension
         CROSS JOIN periods AS period
         CROSS JOIN metric_keys AS metric
         CROSS JOIN aggregations AS aggregation
    )
    INSERT INTO analytics.institution_period_metrics (
        institution_id, platform, period_key, metric_key, aggregation,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id, refreshed_at
    )
    SELECT row.institution_id,
           row.platform,
           row.period_key,
           row.metric_key,
           row.aggregation,
           row.window_start,
           row.window_end,
           row.value,
           row.sample_size,
           row.coverage,
           row.quality,
           revision_as_of,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM replacement_rows AS row;

    GET DIAGNOSTICS institution_period_rows = ROW_COUNT;

    UPDATE analytics.projection_state
       SET dataset_revision_id = p_dataset_revision_id,
           status = 'ready',
           refreshed_at = transaction_timestamp(),
           row_count = institution_period_rows,
           error_code = NULL
     WHERE projection_name = 'institution_period_metrics';

    RETURN base_result || jsonb_build_object(
        'institution_period_metrics', institution_period_rows,
        'institution_period_semantics_version', 2
    );
END
$function$;

COMMENT ON FUNCTION analytics.rebuild_core_projections(bigint) IS
    'Publishes core projections; period semantics v2 uses per-publication deltas from non-synthetic observations in (window_start, window_end].';

REVOKE ALL ON FUNCTION analytics.rebuild_core_projections(bigint) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
    TO migration_bridge, maintenance, api_write_admin;

RESET ROLE;
