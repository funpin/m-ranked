"""Кандидаты и живые почасовые сравнения без материализованных проекций."""
from __future__ import annotations


CANDIDATES = """
WITH candidates AS (
    SELECT account.id AS entity_id,'channels'::text AS entity_type,channel.legacy_id,
           account.institution_id,institution.canonical_name,
           coalesce(nullif(account.current_title,''),CASE WHEN account.current_username IS NOT NULL
             THEN '@'||account.current_username END,institution.short_name,institution.canonical_name) AS label,
           concat(CASE WHEN nullif(account.current_username,'') IS NOT NULL
                       THEN '@'||account.current_username||' · ' ELSE '' END,
             coalesce(metric.subscriber_display,metric.subscriber_count::text,'—'),' подписчиков') AS description
      FROM catalog.visible_platform_account account
      JOIN catalog.visible_institution institution ON institution.id=account.institution_id
      JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=account.id AND channel.entity_type='channels'
      LEFT JOIN LATERAL (SELECT snapshot.subscriber_count,snapshot.subscriber_display
        FROM ingest.account_metric_snapshot_active snapshot
       WHERE snapshot.platform_account_id=account.id AND snapshot.observed_at<=%(as_of)s::timestamptz
         AND snapshot.collected_at<=%(as_of)s::timestamptz AND snapshot.quality<>'invalid'
       ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1) metric ON true
     WHERE %(platform)s='telegram' AND account.platform='telegram' AND account.enabled
    UNION ALL
    SELECT institution.id,'institutions',alias.legacy_id,institution.id,institution.canonical_name,
           coalesce(institution.short_name,institution.canonical_name),
           string_agg(coalesce(nullif(account.current_title,''),CASE WHEN account.current_username IS NOT NULL
             THEN '@'||account.current_username END,account.canonical_external_id),' · ' ORDER BY account.id)
      FROM catalog.visible_institution institution
      JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
      JOIN catalog.visible_platform_account account ON account.institution_id=institution.id
       AND account.platform::text=%(platform)s AND account.enabled
     WHERE %(platform)s<>'telegram'
     GROUP BY institution.id,alias.legacy_id,institution.canonical_name,institution.short_name
), positioned AS (
    SELECT candidates.*,row_number() OVER(ORDER BY lower(label),entity_id) AS position FROM candidates
)
SELECT * FROM positioned
 WHERE %(after_id)s::uuid IS NULL OR position>(SELECT position FROM positioned WHERE entity_id=%(after_id)s::uuid)
 ORDER BY position LIMIT %(fetch_limit)s
"""


COMPARISON = """
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,%(horizon_hours)s::integer AS horizon_hour,
           CASE WHEN %(include_partial)s::boolean THEN 1 ELSE 0 END AS primary_start_hour,
           CASE WHEN %(platform)s='telegram' THEN 1
                WHEN %(include_partial)s::boolean THEN 1 ELSE 0 END AS engagement_start_hour,
           md5('live|'||%(revision)s::text||'|'||%(platform)s||'|'||%(horizon_hours)s::text||'|'||%(include_partial)s::text)::uuid AS cohort_id
), requested AS (
    SELECT value::bigint AS legacy_id,ordinality::integer AS position
      FROM jsonb_array_elements_text(%(selection_ids)s::jsonb) WITH ORDINALITY item(value,ordinality)
), selections AS (
    SELECT requested.position,requested.legacy_id AS requested_legacy_id,
           account.id AS selection_id,'channels'::text AS selection_type,
           coalesce(nullif(account.current_title,''),CASE WHEN account.current_username IS NOT NULL
             THEN '@'||account.current_username END,institution.short_name,institution.canonical_name) AS selection_label,
           institution.id AS institution_id,institution_alias.legacy_id,
           institution.canonical_name,institution.short_name,account.id AS account_id
      FROM requested
      LEFT JOIN catalog.legacy_entity_alias alias ON %(platform)s='telegram'
       AND alias.entity_type='channels' AND alias.legacy_id=requested.legacy_id
      LEFT JOIN catalog.visible_platform_account account ON account.id=alias.target_uuid
       AND account.platform='telegram' AND account.enabled
      LEFT JOIN catalog.visible_institution institution ON institution.id=account.institution_id
      LEFT JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
       AND institution_alias.entity_type='institutions'
     WHERE %(platform)s='telegram'
    UNION ALL
    SELECT requested.position,requested.legacy_id,institution.id,'institutions',
           coalesce(institution.short_name,institution.canonical_name),institution.id,alias.legacy_id,
           institution.canonical_name,institution.short_name,NULL::uuid
      FROM requested
      LEFT JOIN catalog.legacy_entity_alias alias ON alias.entity_type='institutions'
       AND alias.legacy_id=requested.legacy_id
      LEFT JOIN catalog.visible_institution institution ON institution.id=alias.target_uuid
     WHERE %(platform)s<>'telegram'
       AND (institution.id IS NULL OR EXISTS(SELECT 1 FROM catalog.visible_platform_account account
         WHERE account.institution_id=institution.id AND account.platform::text=%(platform)s AND account.enabled))
), publication_candidates AS (
    SELECT selection.*,publication.id AS publication_id,publication.published_at,
           publication.synthetic_baseline_allowed,
           date_trunc('month',publication.published_at AT TIME ZONE 'UTC')::date AS published_month,
           row_number() OVER(PARTITION BY selection.selection_id
                             ORDER BY publication.published_at DESC,publication.id) AS publication_position
      FROM selections selection CROSS JOIN params
      JOIN catalog.visible_platform_account account ON account.enabled AND
           ((%(platform)s='telegram' AND account.id=selection.account_id)
            OR (%(platform)s<>'telegram' AND account.institution_id=selection.institution_id
                AND account.platform::text=%(platform)s))
      JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
       AND publication.published_at>=params.as_of-make_interval(days=>%(hot_days)s)
       AND publication.published_at+params.horizon_hour*interval '1 hour'<=params.as_of
       AND (%(include_partial)s::boolean OR publication.history_completeness='complete')
), publications AS MATERIALIZED (
    SELECT * FROM publication_candidates WHERE publication_position<=20
), snapshot_ranked AS MATERIALIZED (
    SELECT publication.position,publication.requested_legacy_id,publication.selection_id,
           publication.selection_type,publication.selection_label,publication.institution_id,
           publication.legacy_id,publication.canonical_name,publication.short_name,
           publication.published_at,publication.synthetic_baseline_allowed,
           snapshot.*,
           row_number() OVER(PARTITION BY snapshot.publication_id,snapshot.sampling_bucket
                             ORDER BY snapshot.correction_sequence DESC) AS correction_position
      FROM publications publication CROSS JOIN params
      JOIN LATERAL (
          SELECT by_publication.*
            FROM (
                SELECT candidate.*
                  FROM ingest.publication_metric_snapshot candidate
                 WHERE candidate.published_month=publication.published_month
                   AND candidate.publication_id=publication.publication_id
                 OFFSET 0
            ) by_publication
           WHERE by_publication.age_seconds BETWEEN 0 AND params.horizon_hour*3600
             AND by_publication.observed_at<=params.as_of
             AND by_publication.collected_at<=params.as_of
             AND (NOT by_publication.synthetic OR publication.synthetic_baseline_allowed)
             AND by_publication.quality<>'invalid'
      ) snapshot ON true
), snapshots AS MATERIALIZED (
    SELECT * FROM snapshot_ranked WHERE correction_position=1
), metric_events AS (
    SELECT snapshot.*,((snapshot.age_seconds+3599)/3600)::integer AS target_hour,
           metric.metric_value,metric.metric_quality
      FROM snapshots snapshot
     CROSS JOIN LATERAL (VALUES (
       CASE %(metric)s WHEN 'views' THEN snapshot.views_count WHEN 'comments' THEN snapshot.comments_count
                       WHEN 'shares' THEN snapshot.shares_count ELSE snapshot.reactions_count END,
       CASE %(metric)s WHEN 'views' THEN snapshot.views_quality WHEN 'comments' THEN snapshot.comments_quality
                       WHEN 'shares' THEN snapshot.shares_quality ELSE snapshot.reactions_quality END
     )) metric(metric_value,metric_quality)
     WHERE metric.metric_value IS NOT NULL AND metric.metric_quality NOT IN ('invalid','suspected_reset')
), metric_starts AS (
    SELECT DISTINCT ON(publication_id,target_hour) * FROM metric_events
     ORDER BY publication_id,target_hour,age_seconds DESC,observed_at DESC,published_month DESC,id DESC
), metric_intervals AS (
    SELECT metric_starts.*,
           lead(target_hour) OVER(PARTITION BY publication_id ORDER BY target_hour) AS next_hour
      FROM metric_starts CROSS JOIN params WHERE target_hour<=params.horizon_hour
), metric_hourly AS MATERIALIZED (
    SELECT interval.selection_id,interval.publication_id,hour.hour_offset,
           interval.metric_value,interval.metric_quality
      FROM metric_intervals interval CROSS JOIN params
     CROSS JOIN LATERAL generate_series(greatest(interval.target_hour,params.primary_start_hour),
       least(params.horizon_hour,coalesce(interval.next_hour-1,params.horizon_hour))) hour(hour_offset)
), engagement_events AS (
    SELECT snapshot.*,((snapshot.age_seconds+3599)/3600)::integer AS target_hour,
           CASE WHEN snapshot.views_count<=0 THEN NULL
                WHEN %(platform)s='telegram' AND snapshot.reactions_count IS NOT NULL
                  THEN snapshot.reactions_count::numeric*100/snapshot.views_count
                WHEN %(platform)s<>'telegram' AND (snapshot.reactions_count IS NOT NULL
                     OR snapshot.comments_count IS NOT NULL OR snapshot.shares_count IS NOT NULL)
                  THEN (coalesce(snapshot.reactions_count,0)+coalesce(snapshot.comments_count,0)
                        +coalesce(snapshot.shares_count,0))::numeric*100/snapshot.views_count END AS engagement_value,
           analytics.observation_quality_from_rank(greatest(
             analytics.observation_quality_rank(snapshot.views_quality),
             CASE WHEN snapshot.reactions_count IS NULL THEN 0
                  ELSE analytics.observation_quality_rank(snapshot.reactions_quality) END,
             CASE WHEN %(platform)s='telegram' OR snapshot.comments_count IS NULL THEN 0
                  ELSE analytics.observation_quality_rank(snapshot.comments_quality) END,
             CASE WHEN %(platform)s='telegram' OR snapshot.shares_count IS NULL THEN 0
                  ELSE analytics.observation_quality_rank(snapshot.shares_quality) END
           )) AS engagement_quality
      FROM snapshots snapshot
), engagement_starts AS (
    SELECT DISTINCT ON(publication_id,target_hour) * FROM engagement_events
     WHERE engagement_value IS NOT NULL AND engagement_quality NOT IN ('invalid','suspected_reset')
     ORDER BY publication_id,target_hour,age_seconds DESC,observed_at DESC,published_month DESC,id DESC
), engagement_intervals AS (
    SELECT engagement_starts.*,
           lead(target_hour) OVER(PARTITION BY publication_id ORDER BY target_hour) AS next_hour
      FROM engagement_starts CROSS JOIN params WHERE target_hour<=params.horizon_hour
), engagement_hourly AS MATERIALIZED (
    SELECT interval.selection_id,interval.publication_id,hour.hour_offset,
           interval.engagement_value,interval.engagement_quality
      FROM engagement_intervals interval CROSS JOIN params
     CROSS JOIN LATERAL generate_series(greatest(interval.target_hour,params.engagement_start_hour),
       least(params.horizon_hour,coalesce(interval.next_hour-1,params.horizon_hour))) hour(hour_offset)
), primary_members AS (
    SELECT hourly.selection_id,hourly.publication_id FROM metric_hourly hourly CROSS JOIN params
     GROUP BY hourly.selection_id,hourly.publication_id
    HAVING bool_or(hourly.hour_offset=params.primary_start_hour)
       AND bool_or(hourly.hour_offset=params.horizon_hour)
), engagement_members AS (
    SELECT hourly.selection_id,hourly.publication_id FROM engagement_hourly hourly CROSS JOIN params
     GROUP BY hourly.selection_id,hourly.publication_id
    HAVING bool_or(hourly.hour_offset=params.engagement_start_hour)
       AND bool_or(hourly.hour_offset=params.horizon_hour)
), primary_sizes AS (
    SELECT selection_id,count(*)::integer AS size FROM primary_members GROUP BY selection_id
), engagement_sizes AS (
    SELECT selection_id,count(*)::integer AS size FROM engagement_members GROUP BY selection_id
), primary_grouped AS (
    SELECT hourly.selection_id,hourly.hour_offset,count(*)::integer AS sample_size,
           CASE WHEN %(aggregation)s='sum' THEN sum(hourly.metric_value)::numeric
                ELSE round(percentile_cont(0.5) WITHIN GROUP(ORDER BY hourly.metric_value)::numeric,0) END AS value,
           max(analytics.observation_quality_rank(hourly.metric_quality)) AS quality_rank
      FROM metric_hourly hourly JOIN primary_members member USING(selection_id,publication_id)
     GROUP BY hourly.selection_id,hourly.hour_offset
), engagement_grouped AS (
    SELECT hourly.selection_id,hourly.hour_offset,count(*)::integer AS sample_size,
           round(percentile_cont(0.5) WITHIN GROUP(ORDER BY hourly.engagement_value)::numeric,6) AS value,
           max(analytics.observation_quality_rank(hourly.engagement_quality)) AS quality_rank
      FROM engagement_hourly hourly JOIN engagement_members member USING(selection_id,publication_id)
     GROUP BY hourly.selection_id,hourly.hour_offset
), available_hours AS (
    SELECT selection_id,hour_offset FROM primary_grouped UNION
    SELECT selection_id,hour_offset FROM engagement_grouped
), cohort AS (
    SELECT count(*)::integer AS size
      FROM catalog.visible_platform_account account CROSS JOIN params
      JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
       AND publication.published_at>=params.as_of-make_interval(days=>%(hot_days)s)
       AND publication.published_at+params.horizon_hour*interval '1 hour'<=params.as_of
       AND (%(include_partial)s::boolean OR publication.history_completeness='complete')
     WHERE account.enabled AND account.platform::text=%(platform)s
)
SELECT params.cohort_id,cohort.size AS cohort_sample_size,params.as_of,
       selection.requested_legacy_id AS selection_legacy_id,selection.selection_id,
       selection.selection_type,selection.selection_label,selection.institution_id,
       selection.legacy_id,selection.canonical_name,selection.short_name,
       coalesce(primary_size.size,0) AS primary_cohort_size,
       coalesce(engagement_size.size,0) AS engagement_cohort_size,
       hour.hour_offset,primary_curve.value,coalesce(primary_curve.sample_size,0) AS sample_size,
       CASE WHEN coalesce(primary_size.size,0)=0 THEN 0::numeric
            ELSE primary_curve.sample_size::numeric/primary_size.size END AS coverage,
       analytics.observation_quality_from_rank(primary_curve.quality_rank)::text AS quality,
       engagement.value AS engagement_value,
       coalesce(engagement.sample_size,0) AS engagement_sample_size,
       CASE WHEN coalesce(engagement_size.size,0)=0 THEN 0::numeric
            ELSE engagement.sample_size::numeric/engagement_size.size END AS engagement_coverage,
       analytics.observation_quality_from_rank(engagement.quality_rank)::text AS engagement_quality
  FROM params CROSS JOIN cohort CROSS JOIN selections selection
  LEFT JOIN primary_sizes primary_size ON primary_size.selection_id=selection.selection_id
  LEFT JOIN engagement_sizes engagement_size ON engagement_size.selection_id=selection.selection_id
  LEFT JOIN available_hours hour ON hour.selection_id=selection.selection_id
  LEFT JOIN primary_grouped primary_curve ON primary_curve.selection_id=selection.selection_id AND primary_curve.hour_offset=hour.hour_offset
  LEFT JOIN engagement_grouped engagement ON engagement.selection_id=selection.selection_id AND engagement.hour_offset=hour.hour_offset
 ORDER BY selection.position,hour.hour_offset
"""
