WITH selected_cohort AS (
    SELECT cohort.id,
           cohort.platform,
           cohort.horizon_seconds,
           cohort.as_of,
           cohort.sample_size,
           cohort.dataset_revision_id,
           (cohort.filter_definition->>'required_start_hour')::integer
               AS required_start_hour
    FROM analytics.comparison_cohort cohort
    JOIN analytics.projection_state state
      ON state.projection_name = 'comparison'
     AND state.status = 'ready'
     AND state.dataset_revision_id = cohort.dataset_revision_id
    WHERE cohort.dataset_revision_id = :revision
      AND cohort.platform::text = :platform
      AND cohort.horizon_seconds = :horizonSeconds
      AND (cohort.filter_definition->>'include_partial')::boolean = :includePartial
    ORDER BY cohort.as_of DESC, cohort.id
    LIMIT 1
), requested_legacy_ids AS (
    SELECT requested.value::bigint AS legacy_id,
           requested.ordinality::integer AS selection_order
    FROM jsonb_array_elements_text(
        CAST(:selectionLegacyIdsJson AS jsonb)
    ) WITH ORDINALITY AS requested(value, ordinality)
), default_institutions AS (
    SELECT account.institution_id,
           min(lower(institution.canonical_name)) AS sort_name
    FROM selected_cohort cohort
    JOIN catalog.platform_account account
      ON account.platform = cohort.platform
     AND account.enabled
    JOIN catalog.institution institution ON institution.id = account.institution_id
    WHERE NOT EXISTS (SELECT 1 FROM requested_legacy_ids)
    GROUP BY account.institution_id
    ORDER BY sort_name, account.institution_id
    LIMIT :institutionLimit
), selected_institutions AS (
    SELECT requested.legacy_id,
           requested.selection_order,
           alias.target_uuid AS institution_id
    FROM requested_legacy_ids requested
    LEFT JOIN catalog.legacy_entity_alias alias
      ON alias.entity_type = 'institutions'
     AND alias.legacy_id = requested.legacy_id
     AND EXISTS (
         SELECT 1
         FROM catalog.platform_account selected_account
         WHERE selected_account.institution_id = alias.target_uuid
           AND selected_account.platform::text = :platform
           AND selected_account.enabled
     )
    UNION ALL
    SELECT alias.legacy_id,
           (row_number() OVER (
               ORDER BY selected.sort_name, selected.institution_id
           ))::integer AS selection_order,
           selected.institution_id
    FROM default_institutions selected
    JOIN catalog.legacy_entity_alias alias
      ON alias.entity_type = 'institutions'
     AND alias.target_uuid = selected.institution_id
), entity_hourly AS (
    SELECT member.institution_id AS selection_id,
           hourly.publication_id,
           hourly.hour_offset,
           cohort.required_start_hour AS primary_start_hour,
           CASE WHEN cohort.platform::text = 'telegram'
               THEN greatest(cohort.required_start_hour, 1)
               ELSE cohort.required_start_hour
           END AS engagement_start_hour,
           cohort.horizon_seconds / 3600 AS horizon_hour,
           CASE :metric
               WHEN 'views' THEN hourly.views_count
               WHEN 'reactions' THEN hourly.reactions_count
               WHEN 'comments' THEN hourly.comments_count
               WHEN 'shares' THEN hourly.shares_count
           END AS metric_value,
           CASE :metric
               WHEN 'views' THEN CASE hourly.views_quality::text
                   WHEN 'exact' THEN 0 WHEN 'rounded' THEN 1
                   WHEN 'estimated' THEN 2 WHEN 'unknown' THEN 3
                   WHEN 'degraded' THEN 4 WHEN 'suspected_reset' THEN 5
                   ELSE 6 END
               WHEN 'reactions' THEN CASE hourly.reactions_quality::text
                   WHEN 'exact' THEN 0 WHEN 'rounded' THEN 1
                   WHEN 'estimated' THEN 2 WHEN 'unknown' THEN 3
                   WHEN 'degraded' THEN 4 WHEN 'suspected_reset' THEN 5
                   ELSE 6 END
               WHEN 'comments' THEN CASE hourly.comments_quality::text
                   WHEN 'exact' THEN 0 WHEN 'rounded' THEN 1
                   WHEN 'estimated' THEN 2 WHEN 'unknown' THEN 3
                   WHEN 'degraded' THEN 4 WHEN 'suspected_reset' THEN 5
                   ELSE 6 END
               WHEN 'shares' THEN CASE hourly.shares_quality::text
                   WHEN 'exact' THEN 0 WHEN 'rounded' THEN 1
                   WHEN 'estimated' THEN 2 WHEN 'unknown' THEN 3
                   WHEN 'degraded' THEN 4 WHEN 'suspected_reset' THEN 5
                   ELSE 6 END
           END AS metric_quality_rank,
           CASE WHEN hourly.hour_offset < CASE
                        WHEN cohort.platform::text = 'telegram'
                            THEN greatest(cohort.required_start_hour, 1)
                        ELSE cohort.required_start_hour
                    END
               THEN NULL
               ELSE hourly.engagement_percent
           END AS engagement_value,
           CASE hourly.engagement_quality::text
               WHEN 'exact' THEN 0
               WHEN 'rounded' THEN 1
               WHEN 'estimated' THEN 2
               WHEN 'unknown' THEN 3
               WHEN 'degraded' THEN 4
               WHEN 'suspected_reset' THEN 5
               ELSE 6
           END AS engagement_quality_rank
    FROM selected_cohort cohort
    JOIN analytics.comparison_cohort_member member
      ON member.cohort_id = cohort.id
    JOIN selected_institutions selected
      ON selected.institution_id = member.institution_id
    JOIN analytics.comparison_publication_hourly hourly
      ON hourly.publication_id = member.publication_id
     AND hourly.dataset_revision_id = cohort.dataset_revision_id
     AND hourly.hour_offset >= cohort.required_start_hour
     AND hourly.hour_offset <= cohort.horizon_seconds / 3600
), primary_members AS (
    SELECT hourly.selection_id, hourly.publication_id
    FROM entity_hourly hourly
    GROUP BY hourly.selection_id, hourly.publication_id
    HAVING bool_or(
               hourly.hour_offset = hourly.primary_start_hour
               AND hourly.metric_value IS NOT NULL
           )
       AND bool_or(
               hourly.hour_offset = hourly.horizon_hour
               AND hourly.metric_value IS NOT NULL
           )
), engagement_members AS (
    SELECT hourly.selection_id, hourly.publication_id
    FROM entity_hourly hourly
    GROUP BY hourly.selection_id, hourly.publication_id
    HAVING bool_or(
               hourly.hour_offset = hourly.engagement_start_hour
               AND hourly.engagement_value IS NOT NULL
           )
       AND bool_or(
               hourly.hour_offset = hourly.horizon_hour
               AND hourly.engagement_value IS NOT NULL
           )
), primary_sizes AS (
    SELECT member.selection_id,
           count(*)::integer AS primary_cohort_size
    FROM primary_members member
    GROUP BY member.selection_id
), engagement_sizes AS (
    SELECT member.selection_id,
           count(*)::integer AS engagement_cohort_size
    FROM engagement_members member
    GROUP BY member.selection_id
), primary_grouped AS (
    SELECT hourly.selection_id,
           hourly.hour_offset,
           count(hourly.metric_value)::integer AS sample_size,
           sum(hourly.metric_value)::numeric AS sum_value,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY hourly.metric_value)
               FILTER (WHERE hourly.metric_value IS NOT NULL)::numeric
               AS median_value,
           max(hourly.metric_quality_rank)
               FILTER (WHERE hourly.metric_value IS NOT NULL) AS worst_quality
    FROM entity_hourly hourly
    JOIN primary_members member
      ON member.selection_id = hourly.selection_id
     AND member.publication_id = hourly.publication_id
    GROUP BY hourly.selection_id, hourly.hour_offset
), engagement_grouped AS (
    SELECT hourly.selection_id,
           hourly.hour_offset,
           count(hourly.engagement_value)::integer AS sample_size,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY hourly.engagement_value)
               FILTER (WHERE hourly.engagement_value IS NOT NULL)::numeric AS value,
           max(hourly.engagement_quality_rank)
               FILTER (WHERE hourly.engagement_value IS NOT NULL) AS worst_quality
    FROM entity_hourly hourly
    JOIN engagement_members member
      ON member.selection_id = hourly.selection_id
     AND member.publication_id = hourly.publication_id
    GROUP BY hourly.selection_id, hourly.hour_offset
), available_hours AS (
    SELECT primary_point.selection_id, primary_point.hour_offset
    FROM primary_grouped primary_point
    UNION
    SELECT engagement_point.selection_id, engagement_point.hour_offset
    FROM engagement_grouped engagement_point
)
SELECT cohort.id AS cohort_id,
       cohort.platform::text AS platform,
       cohort.horizon_seconds,
       cohort.as_of,
       cohort.sample_size AS cohort_sample_size,
       cohort.dataset_revision_id,
       institution.id AS selection_id,
       'institutions' AS selection_type,
       selected.legacy_id AS selection_legacy_id,
       coalesce(institution.short_name, institution.canonical_name) AS selection_label,
       institution.id AS institution_id,
       selected.legacy_id,
       institution.canonical_name,
       institution.short_name,
       coalesce(primary_size.primary_cohort_size, 0) AS primary_cohort_size,
       coalesce(engagement_size.engagement_cohort_size, 0)
           AS engagement_cohort_size,
       hour.hour_offset,
       CASE :aggregation
           WHEN 'sum' THEN primary_point.sum_value
           ELSE primary_point.median_value
       END AS value,
       coalesce(primary_point.sample_size, 0) AS sample_size,
       CASE WHEN coalesce(primary_size.primary_cohort_size, 0) = 0 THEN 0::numeric
            ELSE round(
                primary_point.sample_size::numeric
                / primary_size.primary_cohort_size,
                6
            )
       END AS coverage,
       CASE primary_point.worst_quality
           WHEN 0 THEN 'exact'
           WHEN 1 THEN 'rounded'
           WHEN 2 THEN 'estimated'
           WHEN 3 THEN 'unknown'
           WHEN 4 THEN 'degraded'
           WHEN 5 THEN 'suspected_reset'
           WHEN 6 THEN 'invalid'
           ELSE 'unknown'
       END AS quality,
       engagement_point.value AS engagement_value,
       coalesce(engagement_point.sample_size, 0) AS engagement_sample_size,
       CASE WHEN coalesce(engagement_size.engagement_cohort_size, 0) = 0
               THEN 0::numeric
            ELSE round(
                engagement_point.sample_size::numeric
                / engagement_size.engagement_cohort_size,
                6
            )
       END AS engagement_coverage,
       CASE engagement_point.worst_quality
           WHEN 0 THEN 'exact'
           WHEN 1 THEN 'rounded'
           WHEN 2 THEN 'estimated'
           WHEN 3 THEN 'unknown'
           WHEN 4 THEN 'degraded'
           WHEN 5 THEN 'suspected_reset'
           WHEN 6 THEN 'invalid'
           ELSE 'unknown'
       END AS engagement_quality
FROM selected_institutions selected
LEFT JOIN selected_cohort cohort ON true
LEFT JOIN catalog.institution institution ON institution.id = selected.institution_id
LEFT JOIN primary_sizes primary_size
  ON primary_size.selection_id = selected.institution_id
LEFT JOIN engagement_sizes engagement_size
  ON engagement_size.selection_id = selected.institution_id
LEFT JOIN available_hours hour ON hour.selection_id = selected.institution_id
LEFT JOIN primary_grouped primary_point
  ON primary_point.selection_id = selected.institution_id
 AND primary_point.hour_offset = hour.hour_offset
LEFT JOIN engagement_grouped engagement_point
  ON engagement_point.selection_id = selected.institution_id
 AND engagement_point.hour_offset = hour.hour_offset
ORDER BY selected.selection_order, hour.hour_offset
