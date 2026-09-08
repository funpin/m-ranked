package org.mranked.query.infrastructure;

/**
 * Bounded overview read over canonical facts. It deliberately avoids rebuilding the
 * publisher's historical deltas: source mode reports the latest counters for publications
 * created in the requested period and leaves the previous window empty.
 */
final class SourceOverviewSql {
    private SourceOverviewSql() {}

    static final String SQL = """
            WITH params AS (
                SELECT CAST(:asOf AS timestamptz) AS as_of,
                       CASE :period WHEN '3h' THEN interval '3 hours'
                           WHEN '1d' THEN interval '1 day'
                           WHEN '7d' THEN interval '7 days'
                           ELSE interval '30 days' END AS duration
            ), account_fact AS (
                SELECT account.id,account.institution_id,account.platform,
                       account.canonical_external_id,account.current_username,account.current_title,
                       account.current_url,account.access_mode,account.enabled,
                       channel_alias.legacy_id AS channel_legacy_id,
                       channel_alias.legacy_route AS channel_legacy_route,
                       platform_alias.legacy_id AS platform_legacy_id,
                       platform_alias.legacy_route AS platform_legacy_route,
                       metric.subscriber_count,metric.subscriber_display,
                       metric.observed_at AS subscriber_observed_at,
                       result.started_at AS latest_poll_started_at,
                       result.completed_at AS latest_poll_completed_at,
                       result.status AS latest_poll_status,
                       CASE WHEN result.status IN ('failed','partial')
                           THEN coalesce(result.sanitized_error_code,'collection_failed')
                           ELSE result.sanitized_error_code END AS latest_error_code,
                       greatest(result.completed_at,result.started_at,metric.observed_at) AS last_checked_at
                  FROM catalog.visible_platform_account account
                 CROSS JOIN params
                  LEFT JOIN LATERAL (
                      SELECT alias.legacy_id,alias.legacy_route
                        FROM catalog.legacy_entity_alias alias
                       WHERE alias.target_uuid=account.id AND alias.entity_type='channels'
                       ORDER BY alias.legacy_id LIMIT 1
                  ) channel_alias ON true
                  LEFT JOIN LATERAL (
                      SELECT alias.legacy_id,alias.legacy_route
                        FROM catalog.legacy_entity_alias alias
                       WHERE alias.target_uuid=account.id AND alias.entity_type='platform_accounts'
                       ORDER BY alias.legacy_id LIMIT 1
                  ) platform_alias ON true
                  LEFT JOIN LATERAL (
                      SELECT snapshot.subscriber_count,snapshot.subscriber_display,snapshot.observed_at
                        FROM ingest.account_metric_snapshot_active snapshot
                       WHERE snapshot.platform_account_id=account.id
                         AND snapshot.observed_at<=params.as_of AND snapshot.collected_at<=params.as_of
                         AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1
                  ) metric ON true
                  LEFT JOIN LATERAL (
                      SELECT observation.started_at,
                             CASE WHEN observation.completed_at<=params.as_of THEN observation.completed_at END AS completed_at,
                             CASE WHEN observation.completed_at IS NULL OR observation.completed_at>params.as_of
                                 THEN 'running'::ingest.run_status ELSE observation.status END AS status,
                             observation.sanitized_error_code
                        FROM ingest.collection_account_result observation
                       WHERE observation.platform_account_id=account.id AND observation.started_at<=params.as_of
                       ORDER BY observation.started_at DESC,observation.id DESC LIMIT 1
                  ) result ON true
            ), dimensions AS (
                SELECT 'telegram'::text AS scope_platform,account.id AS entity_id,
                       'channels'::text AS entity_type,account.channel_legacy_id AS legacy_id,
                       account.channel_legacy_route AS legacy_route,account.institution_id
                  FROM account_fact account
                 WHERE :platform='telegram' AND account.platform='telegram'
                   AND account.enabled AND account.channel_legacy_id IS NOT NULL
                UNION ALL
                SELECT :platform,institution.id,'institutions',alias.legacy_id,alias.legacy_route,institution.id
                  FROM catalog.visible_institution institution
                  JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
                 WHERE :platform IN ('all','vk','max','rutube')
            ), selected_accounts AS (
                SELECT dimension.scope_platform,dimension.entity_id,account.*,
                       CASE WHEN dimension.scope_platform='telegram' THEN account.channel_legacy_id
                           ELSE coalesce(account.platform_legacy_id,account.channel_legacy_id) END AS selected_legacy_id,
                       CASE WHEN dimension.scope_platform='telegram' THEN account.channel_legacy_route
                           ELSE coalesce(account.platform_legacy_route,account.channel_legacy_route) END AS selected_legacy_route
                  FROM dimensions dimension
                  JOIN account_fact account ON account.institution_id=dimension.institution_id
                   AND ((dimension.scope_platform='telegram' AND account.id=dimension.entity_id)
                     OR dimension.scope_platform='all' OR account.platform::text=dimension.scope_platform)
            ), publication_fact AS (
                SELECT selected.scope_platform,selected.entity_id,publication.id,
                       latest.views_count,latest.reactions_count,latest.comments_count,latest.shares_count
                  FROM selected_accounts selected
                  JOIN ingest.visible_publication publication ON publication.primary_account_id=selected.id
                 CROSS JOIN params
                  LEFT JOIN LATERAL (
                      SELECT snapshot.views_count,snapshot.reactions_count,
                             snapshot.comments_count,snapshot.shares_count
                        FROM analytics.usable_publication_snapshot snapshot
                       WHERE snapshot.publication_id=publication.id
                         AND snapshot.published_month=date_trunc('month',publication.published_at AT TIME ZONE 'UTC')::date
                         AND snapshot.observed_at<=params.as_of AND snapshot.collected_at<=params.as_of
                         AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC LIMIT 1
                  ) latest ON true
                 WHERE publication.published_at>params.as_of-params.duration
                   AND publication.published_at<=params.as_of AND publication.created_at<=params.as_of
            ), metric_summary AS (
                SELECT scope_platform,entity_id,count(*)::bigint AS publication_count,
                       count(*) FILTER (WHERE views_count IS NOT NULL)::integer AS views_samples,
                       sum(views_count)::numeric AS total_views,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY views_count)
                           FILTER(WHERE views_count IS NOT NULL)::numeric,0) AS median_views,
                       count(*) FILTER (WHERE reactions_count IS NOT NULL)::integer AS reactions_samples,
                       sum(reactions_count)::numeric AS total_reactions,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY reactions_count)
                           FILTER(WHERE reactions_count IS NOT NULL)::numeric,0) AS median_reactions,
                       count(*) FILTER (WHERE comments_count IS NOT NULL)::integer AS comments_samples,
                       sum(comments_count)::numeric AS total_comments,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY comments_count)
                           FILTER(WHERE comments_count IS NOT NULL)::numeric,0) AS median_comments,
                       count(*) FILTER (WHERE shares_count IS NOT NULL)::integer AS shares_samples,
                       sum(shares_count)::numeric AS total_shares,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY shares_count)
                           FILTER(WHERE shares_count IS NOT NULL)::numeric,0) AS median_shares
                  FROM publication_fact GROUP BY scope_platform,entity_id
            ), account_summary AS (
                SELECT scope_platform,entity_id,count(*)::integer AS account_count,
                       count(*) FILTER(WHERE enabled)::integer AS enabled_account_count,
                       count(DISTINCT platform) FILTER(WHERE enabled)::integer AS connected_platform_count,
                       sum(subscriber_count)::bigint AS subscriber_count,max(last_checked_at) AS last_checked_at,
                       min(latest_error_code) FILTER(WHERE latest_error_code IS NOT NULL) AS last_error_code
                  FROM selected_accounts GROUP BY scope_platform,entity_id
            ), card_source AS (
                SELECT dimension.scope_platform AS platform,:period AS period_key,dimension.entity_type,
                       dimension.entity_id,dimension.legacy_id,dimension.legacy_route,
                       institution.id AS institution_id,institution_alias.legacy_id AS institution_legacy_id,
                       institution.canonical_name,institution.short_name,
                       lower(coalesce(nullif(institution.short_name,''),institution.canonical_name,'')) AS sort_name,
                       lower(concat_ws(' ',institution.short_name,institution.canonical_name,telegram.current_title)) AS search_text,
                       coalesce(summary.account_count,0) AS account_count,
                       coalesce(summary.enabled_account_count,0) AS enabled_account_count,
                       coalesce(summary.connected_platform_count,0) AS connected_platform_count,
                       summary.subscriber_count,summary.last_checked_at,summary.last_error_code,
                       CASE WHEN coalesce(summary.account_count,0)=0 THEN 'no_account'
                           WHEN coalesce(summary.enabled_account_count,0)=0 THEN 'all_accounts_disabled'
                           WHEN summary.last_error_code IS NOT NULL THEN 'last_poll_failed'
                           WHEN dimension.scope_platform='all' THEN 'connected'
                           WHEN summary.last_checked_at IS NOT NULL THEN 'polling' ELSE 'awaiting_first_poll' END AS status_code,
                       rating.rank AS rating_rank,rating.score AS rating_score,
                       rating.period AS rating_period,rating.fetched_at AS rating_fetched_at,
                       metrics.publication_count AS total_publication_count,
                       metrics.publication_count AS activity_publication_count,
                       metrics.publication_count AS new_publication_count,
                       metrics.total_views,metrics.median_views,NULL::numeric AS previous_total_views,NULL::numeric AS previous_median_views,
                       metrics.total_reactions,metrics.median_reactions,NULL::numeric AS previous_total_reactions,NULL::numeric AS previous_median_reactions,
                       metrics.total_comments,metrics.median_comments,NULL::numeric AS previous_total_comments,NULL::numeric AS previous_median_comments,
                       metrics.total_shares,metrics.median_shares,NULL::numeric AS previous_total_shares,NULL::numeric AS previous_median_shares,
                       jsonb_build_object(
                           'views:0',jsonb_build_object('sampleSize',coalesce(metrics.views_samples,0),'coverage',metrics.views_samples::numeric/nullif(metrics.publication_count,0),'quality','unknown','asOf',params.as_of,'datasetRevision',:revision),
                           'reactions:0',jsonb_build_object('sampleSize',coalesce(metrics.reactions_samples,0),'coverage',metrics.reactions_samples::numeric/nullif(metrics.publication_count,0),'quality','unknown','asOf',params.as_of,'datasetRevision',:revision),
                           'comments:0',jsonb_build_object('sampleSize',coalesce(metrics.comments_samples,0),'coverage',metrics.comments_samples::numeric/nullif(metrics.publication_count,0),'quality','unknown','asOf',params.as_of,'datasetRevision',:revision),
                           'shares:0',jsonb_build_object('sampleSize',coalesce(metrics.shares_samples,0),'coverage',metrics.shares_samples::numeric/nullif(metrics.publication_count,0),'quality','unknown','asOf',params.as_of,'datasetRevision',:revision)
                       ) AS aggregate_metadata,params.as_of
                  FROM dimensions dimension CROSS JOIN params
                  JOIN catalog.visible_institution institution ON institution.id=dimension.institution_id
                  JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid=institution.id AND institution_alias.entity_type='institutions'
                  LEFT JOIN selected_accounts telegram ON dimension.scope_platform='telegram'
                    AND telegram.entity_id=dimension.entity_id AND telegram.platform='telegram'
                  LEFT JOIN account_summary summary ON summary.scope_platform=dimension.scope_platform
                    AND summary.entity_id=dimension.entity_id
                  LEFT JOIN metric_summary metrics ON metrics.scope_platform=dimension.scope_platform
                    AND metrics.entity_id=dimension.entity_id
                  LEFT JOIN LATERAL (
                      SELECT observation.rank,observation.score,observation.period,observation.fetched_at
                        FROM rating.official_institution_rating_observation observation
                       WHERE observation.institution_id=dimension.institution_id
                         AND observation.category=CASE dimension.scope_platform WHEN 'all' THEN 'social' ELSE dimension.scope_platform END
                         AND observation.fetched_at<=params.as_of
                       ORDER BY observation.fetched_at DESC,observation.id DESC LIMIT 1
                  ) rating ON true
            ), filtered AS (
                SELECT card.*,row_number() OVER(ORDER BY
                    CASE WHEN :sort='name' AND :direction='asc' THEN card.sort_name END ASC NULLS LAST,
                    CASE WHEN :sort='name' AND :direction='desc' THEN card.sort_name END DESC NULLS LAST,
                    CASE WHEN :sort<>'name' AND :direction='asc' THEN CASE :sort
                        WHEN 'm_rating' THEN card.rating_rank::numeric WHEN 'coverage' THEN card.connected_platform_count::numeric
                        WHEN 'accounts' THEN card.account_count::numeric WHEN 'subscribers' THEN card.subscriber_count::numeric
                        WHEN 'posts' THEN card.new_publication_count::numeric WHEN 'views' THEN card.total_views
                        WHEN 'reactions' THEN card.total_reactions ELSE card.median_reactions END END ASC NULLS LAST,
                    CASE WHEN :sort<>'name' AND :direction='desc' THEN CASE :sort
                        WHEN 'm_rating' THEN card.rating_rank::numeric WHEN 'coverage' THEN card.connected_platform_count::numeric
                        WHEN 'accounts' THEN card.account_count::numeric WHEN 'subscribers' THEN card.subscriber_count::numeric
                        WHEN 'posts' THEN card.new_publication_count::numeric WHEN 'views' THEN card.total_views
                        WHEN 'reactions' THEN card.total_reactions ELSE card.median_reactions END END DESC NULLS LAST,
                    card.sort_name,card.entity_id) AS page_position
                  FROM card_source card WHERE :search='' OR card.search_text LIKE '%'||lower(:search)||'%'
            ), page AS (
                SELECT * FROM filtered WHERE CAST(:afterId AS uuid) IS NULL OR page_position>(
                    SELECT page_position FROM filtered WHERE entity_id=CAST(:afterId AS uuid))
                 ORDER BY page_position LIMIT :fetchLimit
            )
            SELECT page.*,:revision AS dataset_revision_id,
                   NULL::numeric AS delta_total_views,NULL::numeric AS delta_median_views,
                   NULL::numeric AS delta_total_reactions,NULL::numeric AS delta_median_reactions,
                   NULL::numeric AS delta_total_comments,NULL::numeric AS delta_median_comments,
                   NULL::numeric AS delta_total_shares,NULL::numeric AS delta_median_shares,
                   account.id AS account_id,account.selected_legacy_id AS account_legacy_id,
                   account.selected_legacy_route AS account_legacy_route,account.platform::text AS account_platform,
                   account.canonical_external_id AS account_external_id,account.current_username AS account_username,
                   account.current_title AS account_title,account.current_url AS account_url,
                   account.access_mode::text AS account_access_mode,account.enabled AS account_enabled,
                   account.subscriber_count AS account_subscriber_count,account.subscriber_display AS account_subscriber_display,
                   account.subscriber_observed_at AS account_subscriber_observed_at,
                   account.latest_poll_started_at AS account_latest_poll_started_at,
                   account.latest_poll_completed_at AS account_latest_poll_completed_at,
                   account.latest_poll_status::text AS account_latest_poll_status,
                   account.latest_error_code AS account_latest_error_code
              FROM page LEFT JOIN selected_accounts account
                ON account.scope_platform=page.platform AND account.entity_id=page.entity_id
             ORDER BY page.page_position,account.platform,
                      lower(coalesce(account.current_title,account.current_username,account.canonical_external_id))
            """;
}
