package org.mranked.query.infrastructure;

/** Bounded public reads calculated directly from canonical catalog and ingest facts. */
final class SourceReadSql {
    private SourceReadSql() {}

    static final String OVERVIEW = """
            WITH params AS (
                SELECT CAST(:asOf AS timestamptz) AS as_of,
                       CASE :period
                           WHEN '3h' THEN interval '3 hours'
                           WHEN '1d' THEN interval '1 day'
                           WHEN '7d' THEN interval '7 days'
                           ELSE interval '30 days'
                       END AS duration
            ), account_fact AS (
                SELECT account.id,
                       account.institution_id,
                       account.platform,
                       account.canonical_external_id,
                       account.current_username,
                       account.current_title,
                       account.current_url,
                       account.access_mode,
                       account.enabled,
                       channel_alias.legacy_id AS channel_legacy_id,
                       channel_alias.legacy_route AS channel_legacy_route,
                       platform_alias.legacy_id AS platform_legacy_id,
                       platform_alias.legacy_route AS platform_legacy_route,
                       metric.subscriber_count,
                       metric.subscriber_display,
                       metric.observed_at AS subscriber_observed_at,
                       result.started_at AS latest_poll_started_at,
                       result.completed_at AS latest_poll_completed_at,
                       result.status AS latest_poll_status,
                       CASE WHEN result.status IN ('failed', 'partial')
                            THEN coalesce(result.sanitized_error_code, 'collection_failed')
                            ELSE result.sanitized_error_code END AS latest_error_code,
                       greatest(result.completed_at, result.started_at, metric.observed_at) AS last_checked_at
                  FROM catalog.visible_platform_account account
                 CROSS JOIN params
                  LEFT JOIN catalog.legacy_entity_alias channel_alias
                    ON channel_alias.target_uuid=account.id AND channel_alias.entity_type='channels'
                  LEFT JOIN catalog.legacy_entity_alias platform_alias
                    ON platform_alias.target_uuid=account.id AND platform_alias.entity_type='platform_accounts'
                  LEFT JOIN LATERAL (
                      SELECT snapshot.subscriber_count, snapshot.subscriber_display, snapshot.observed_at
                        FROM ingest.account_metric_snapshot_active snapshot
                       WHERE snapshot.platform_account_id=account.id
                         AND snapshot.observed_at<=params.as_of
                         AND snapshot.collected_at<=params.as_of
                         AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC, snapshot.id DESC LIMIT 1
                  ) metric ON true
                  LEFT JOIN LATERAL (
                      SELECT observation.started_at,
                             CASE WHEN observation.completed_at<=params.as_of THEN observation.completed_at END AS completed_at,
                             CASE WHEN observation.completed_at IS NULL OR observation.completed_at>params.as_of
                                  THEN 'running'::ingest.run_status ELSE observation.status END AS status,
                             observation.sanitized_error_code
                        FROM ingest.collection_account_result observation
                       WHERE observation.platform_account_id=account.id
                         AND observation.started_at<=params.as_of
                       ORDER BY observation.started_at DESC, observation.id DESC LIMIT 1
                  ) result ON true
            ), dimensions AS (
                SELECT 'telegram'::text AS platform, account.id AS entity_id,
                       'channels'::text AS entity_type, account.channel_legacy_id AS legacy_id,
                       account.channel_legacy_route AS legacy_route, account.institution_id
                  FROM account_fact account
                 WHERE :platform='telegram' AND account.platform='telegram'
                   AND account.enabled AND account.channel_legacy_id IS NOT NULL
                UNION ALL
                SELECT :platform, institution.id, 'institutions', alias.legacy_id, alias.legacy_route, institution.id
                  FROM catalog.visible_institution institution
                  JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
                 WHERE :platform IN ('all','vk','max','rutube')
            ), selected_accounts AS (
                SELECT dimension.platform AS scope_platform, dimension.entity_id, account.*,
                       CASE WHEN dimension.platform='telegram' THEN account.channel_legacy_id
                            ELSE coalesce(account.platform_legacy_id,account.channel_legacy_id) END AS selected_legacy_id,
                       CASE WHEN dimension.platform='telegram' THEN account.channel_legacy_route
                            ELSE coalesce(account.platform_legacy_route,account.channel_legacy_route) END AS selected_legacy_route
                  FROM dimensions dimension
                  JOIN account_fact account ON account.institution_id=dimension.institution_id
                   AND ((dimension.platform='telegram' AND account.id=dimension.entity_id)
                     OR dimension.platform='all' OR account.platform::text=dimension.platform)
            ), activity_windows AS (
                SELECT 0 AS window_index, params.as_of-params.duration AS window_start,
                       params.as_of AS window_end FROM params
                UNION ALL
                SELECT 1, params.as_of-params.duration*2, params.as_of-params.duration FROM params
            ), activity_publications AS (
                SELECT selected.scope_platform AS platform, selected.entity_id,
                       publication.id AS publication_id, publication.published_at,
                       publication.history_completeness, publication.synthetic_baseline_allowed
                  FROM selected_accounts selected
                  JOIN ingest.visible_publication publication ON publication.primary_account_id=selected.id
                 CROSS JOIN params
                 WHERE publication.published_at<=params.as_of
                   AND publication.created_at<=params.as_of
                   AND publication.published_at>params.as_of-make_interval(days=>:hotDays)
            ), window_observations AS (
                SELECT activity_window.window_index, activity_window.window_start, activity_window.window_end,
                       publication.platform, publication.entity_id, publication.publication_id,
                       publication.published_at, publication.synthetic_baseline_allowed,
                       snapshot.age_seconds, snapshot.views_count, snapshot.reactions_count,
                       snapshot.comments_count, snapshot.shares_count,
                       snapshot.views_quality, snapshot.reactions_quality,
                       snapshot.comments_quality, snapshot.shares_quality,
                       row_number() OVER (PARTITION BY activity_window.window_index,publication.publication_id
                           ORDER BY snapshot.observed_at,snapshot.published_month,snapshot.id) AS first_position,
                       row_number() OVER (PARTITION BY activity_window.window_index,publication.publication_id
                           ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC) AS latest_position,
                       count(*) OVER (PARTITION BY activity_window.window_index,publication.publication_id) AS observation_count
                  FROM activity_windows activity_window
                  JOIN activity_publications publication ON publication.published_at<=activity_window.window_end
                  JOIN analytics.usable_publication_snapshot snapshot
                    ON snapshot.publication_id=publication.publication_id
                   AND snapshot.observed_at>activity_window.window_start AND snapshot.observed_at<=activity_window.window_end
                 CROSS JOIN params
                 WHERE snapshot.collected_at<=params.as_of AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
            ), publication_bounds AS (
                SELECT observation.window_index, observation.window_start, observation.platform,
                       observation.entity_id, observation.publication_id, observation.published_at,
                       observation.synthetic_baseline_allowed,
                       max(observation.observation_count) AS observation_count,
                       max(observation.age_seconds) FILTER(WHERE first_position=1) AS first_age_seconds,
                       max(observation.views_count) FILTER(WHERE first_position=1) AS first_views,
                       max(observation.views_count) FILTER(WHERE latest_position=1) AS latest_views,
                       max(observation.reactions_count) FILTER(WHERE first_position=1) AS first_reactions,
                       max(observation.reactions_count) FILTER(WHERE latest_position=1) AS latest_reactions,
                       max(observation.comments_count) FILTER(WHERE first_position=1) AS first_comments,
                       max(observation.comments_count) FILTER(WHERE latest_position=1) AS latest_comments,
                       max(observation.shares_count) FILTER(WHERE first_position=1) AS first_shares,
                       max(observation.shares_count) FILTER(WHERE latest_position=1) AS latest_shares,
                       max(analytics.observation_quality_rank(observation.views_quality))
                           FILTER(WHERE (first_position=1 OR latest_position=1) AND views_count IS NOT NULL) AS views_quality_rank,
                       max(analytics.observation_quality_rank(observation.reactions_quality))
                           FILTER(WHERE (first_position=1 OR latest_position=1) AND reactions_count IS NOT NULL) AS reactions_quality_rank,
                       max(analytics.observation_quality_rank(observation.comments_quality))
                           FILTER(WHERE (first_position=1 OR latest_position=1) AND comments_count IS NOT NULL) AS comments_quality_rank,
                       max(analytics.observation_quality_rank(observation.shares_quality))
                           FILTER(WHERE (first_position=1 OR latest_position=1) AND shares_count IS NOT NULL) AS shares_quality_rank
                  FROM window_observations observation
                 GROUP BY observation.window_index,observation.window_start,observation.platform,
                          observation.entity_id,observation.publication_id,observation.published_at,
                          observation.synthetic_baseline_allowed
            ), publication_delta AS (
                SELECT bounds.*,
                       CASE WHEN latest_views IS NULL THEN NULL
                            WHEN published_at>=window_start AND synthetic_baseline_allowed THEN latest_views::numeric
                            WHEN observation_count>=2 AND first_views IS NOT NULL THEN latest_views::numeric-first_views::numeric END AS views_delta,
                       CASE WHEN latest_reactions IS NULL THEN NULL
                            WHEN published_at>=window_start AND synthetic_baseline_allowed THEN latest_reactions::numeric
                            WHEN observation_count>=2 AND first_reactions IS NOT NULL THEN latest_reactions::numeric-first_reactions::numeric END AS reactions_delta,
                       CASE WHEN latest_comments IS NULL THEN NULL
                            WHEN published_at>=window_start AND synthetic_baseline_allowed THEN latest_comments::numeric
                            WHEN observation_count>=2 AND first_comments IS NOT NULL THEN latest_comments::numeric-first_comments::numeric END AS comments_delta,
                       CASE WHEN latest_shares IS NULL THEN NULL
                            WHEN published_at>=window_start AND synthetic_baseline_allowed THEN latest_shares::numeric
                            WHEN observation_count>=2 AND first_shares IS NOT NULL THEN latest_shares::numeric-first_shares::numeric END AS shares_delta
                  FROM publication_bounds bounds
            ), metric_delta AS (
                SELECT delta.window_index,delta.platform,delta.entity_id,delta.publication_id,
                       metric.metric_key,metric.delta_value,metric.quality_rank
                  FROM publication_delta delta
                 CROSS JOIN LATERAL(VALUES
                    ('views',delta.views_delta,delta.views_quality_rank),
                    ('reactions',delta.reactions_delta,delta.reactions_quality_rank),
                    ('comments',delta.comments_delta,delta.comments_quality_rank),
                    ('shares',delta.shares_delta,delta.shares_quality_rank)
                 ) metric(metric_key,delta_value,quality_rank)
                 WHERE metric.delta_value IS NOT NULL
            ), metric_aggregate AS (
                SELECT metric.window_index,metric.platform,metric.entity_id,metric.metric_key,
                       count(*)::integer AS sample_size,
                       sum(metric.delta_value) AS total_value,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY metric.delta_value)::numeric,0) AS median_value,
                       max(metric.quality_rank) AS quality_rank
                  FROM metric_delta metric
                 GROUP BY metric.window_index,metric.platform,metric.entity_id,metric.metric_key
            ), population AS (
                SELECT window_index,platform,entity_id,count(*)::integer AS population
                  FROM publication_delta GROUP BY window_index,platform,entity_id
            ), metric_metadata AS (
                SELECT metric.platform,metric.entity_id,
                       jsonb_object_agg(metric.metric_key||':'||metric.window_index,jsonb_build_object(
                           'sampleSize',metric.sample_size,
                           'coverage',metric.sample_size::numeric/nullif(population.population,0),
                           'quality',analytics.observation_quality_from_rank(metric.quality_rank),
                           'asOf',params.as_of,'datasetRevision',:revision)) AS metadata
                  FROM metric_aggregate metric
                  JOIN population USING(window_index,platform,entity_id) CROSS JOIN params
                 GROUP BY metric.platform,metric.entity_id
            ), metric_pivot AS (
                SELECT platform,entity_id,
                       max(total_value) FILTER(WHERE window_index=0 AND metric_key='views') AS total_views,
                       max(median_value) FILTER(WHERE window_index=0 AND metric_key='views') AS median_views,
                       max(total_value) FILTER(WHERE window_index=1 AND metric_key='views') AS previous_total_views,
                       max(median_value) FILTER(WHERE window_index=1 AND metric_key='views') AS previous_median_views,
                       max(total_value) FILTER(WHERE window_index=0 AND metric_key='reactions') AS total_reactions,
                       max(median_value) FILTER(WHERE window_index=0 AND metric_key='reactions') AS median_reactions,
                       max(total_value) FILTER(WHERE window_index=1 AND metric_key='reactions') AS previous_total_reactions,
                       max(median_value) FILTER(WHERE window_index=1 AND metric_key='reactions') AS previous_median_reactions,
                       max(total_value) FILTER(WHERE window_index=0 AND metric_key='comments') AS total_comments,
                       max(median_value) FILTER(WHERE window_index=0 AND metric_key='comments') AS median_comments,
                       max(total_value) FILTER(WHERE window_index=1 AND metric_key='comments') AS previous_total_comments,
                       max(median_value) FILTER(WHERE window_index=1 AND metric_key='comments') AS previous_median_comments,
                       max(total_value) FILTER(WHERE window_index=0 AND metric_key='shares') AS total_shares,
                       max(median_value) FILTER(WHERE window_index=0 AND metric_key='shares') AS median_shares,
                       max(total_value) FILTER(WHERE window_index=1 AND metric_key='shares') AS previous_total_shares,
                       max(median_value) FILTER(WHERE window_index=1 AND metric_key='shares') AS previous_median_shares
                  FROM metric_aggregate GROUP BY platform,entity_id
            ), activity_count AS (
                SELECT platform,entity_id,count(*)::bigint AS publication_count
                  FROM publication_delta
                 WHERE window_index=0 AND (views_delta IS NOT NULL OR reactions_delta IS NOT NULL
                    OR comments_delta IS NOT NULL OR shares_delta IS NOT NULL)
                 GROUP BY platform,entity_id
            ), publication_count AS (
                SELECT publication.platform,publication.entity_id,count(*)::bigint AS total_count,
                       count(*) FILTER(WHERE publication.published_at>=params.as_of-params.duration)::bigint AS new_count
                  FROM activity_publications publication CROSS JOIN params
                 GROUP BY publication.platform,publication.entity_id
            ), account_summary AS (
                SELECT scope_platform AS platform,entity_id,count(*)::integer AS account_count,
                       count(*) FILTER(WHERE enabled)::integer AS enabled_account_count,
                       count(DISTINCT platform) FILTER(WHERE enabled)::integer AS connected_platform_count,
                       sum(subscriber_count) AS subscriber_count,max(last_checked_at) AS last_checked_at,
                       min(latest_error_code) FILTER(WHERE latest_error_code IS NOT NULL) AS last_error_code
                  FROM selected_accounts GROUP BY scope_platform,entity_id
            ), latest_rating AS (
                SELECT DISTINCT ON(observation.institution_id,observation.category)
                       observation.institution_id,observation.category,observation.rank,
                       observation.score,observation.period,observation.fetched_at
                  FROM rating.official_institution_rating_observation observation CROSS JOIN params
                 WHERE observation.fetched_at<=params.as_of
                 ORDER BY observation.institution_id,observation.category,observation.fetched_at DESC,observation.id DESC
            ), card_source AS (
                SELECT dimension.platform, :period AS period_key,dimension.entity_type,dimension.entity_id,
                       dimension.legacy_id,dimension.legacy_route,institution.id AS institution_id,
                       institution_alias.legacy_id AS institution_legacy_id,institution.canonical_name,institution.short_name,
                       lower(coalesce(nullif(institution.short_name,''),institution.canonical_name,'')) AS sort_name,
                       lower(concat_ws(' ',institution.short_name,institution.canonical_name,telegram.current_title)) AS search_text,
                       coalesce(summary.account_count,0) AS account_count,
                       coalesce(summary.enabled_account_count,0) AS enabled_account_count,
                       coalesce(summary.connected_platform_count,0) AS connected_platform_count,
                       summary.subscriber_count,summary.last_checked_at,summary.last_error_code,
                       CASE WHEN coalesce(summary.account_count,0)=0 THEN 'no_account'
                            WHEN coalesce(summary.enabled_account_count,0)=0 THEN 'all_accounts_disabled'
                            WHEN summary.last_error_code IS NOT NULL THEN 'last_poll_failed'
                            WHEN dimension.platform='all' THEN 'connected'
                            WHEN summary.last_checked_at IS NOT NULL THEN 'polling' ELSE 'awaiting_first_poll' END AS status_code,
                       rating.rank AS rating_rank,rating.score AS rating_score,rating.period AS rating_period,rating.fetched_at AS rating_fetched_at,
                       CASE WHEN dimension.platform='all' THEN NULL ELSE coalesce(publications.total_count,0) END AS total_publication_count,
                       CASE WHEN dimension.platform='all' THEN NULL ELSE coalesce(activity.publication_count,0) END AS activity_publication_count,
                       CASE WHEN dimension.platform='all' THEN NULL ELSE coalesce(publications.new_count,0) END AS new_publication_count,
                       metric.total_views,metric.median_views,metric.previous_total_views,metric.previous_median_views,
                       metric.total_reactions,metric.median_reactions,metric.previous_total_reactions,metric.previous_median_reactions,
                       metric.total_comments,metric.median_comments,metric.previous_total_comments,metric.previous_median_comments,
                       metric.total_shares,metric.median_shares,metric.previous_total_shares,metric.previous_median_shares,
                       coalesce(metadata.metadata,'{}'::jsonb) AS aggregate_metadata,params.as_of
                  FROM dimensions dimension CROSS JOIN params
                  JOIN catalog.visible_institution institution ON institution.id=dimension.institution_id
                  JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid=institution.id AND institution_alias.entity_type='institutions'
                  LEFT JOIN selected_accounts telegram ON dimension.platform='telegram'
                    AND telegram.entity_id=dimension.entity_id AND telegram.platform='telegram'
                  LEFT JOIN account_summary summary ON summary.platform=dimension.platform AND summary.entity_id=dimension.entity_id
                  LEFT JOIN publication_count publications ON publications.platform=dimension.platform AND publications.entity_id=dimension.entity_id
                  LEFT JOIN activity_count activity ON activity.platform=dimension.platform AND activity.entity_id=dimension.entity_id
                  LEFT JOIN metric_pivot metric ON metric.platform=dimension.platform AND metric.entity_id=dimension.entity_id
                  LEFT JOIN metric_metadata metadata ON metadata.platform=dimension.platform AND metadata.entity_id=dimension.entity_id
                  LEFT JOIN latest_rating rating ON rating.institution_id=dimension.institution_id
                    AND rating.category=CASE dimension.platform WHEN 'all' THEN 'social' ELSE dimension.platform END
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
                  FROM card_source card
                 WHERE :search='' OR card.search_text LIKE '%'||lower(:search)||'%'
            ), page AS (
                SELECT * FROM filtered WHERE CAST(:afterId AS uuid) IS NULL OR page_position>(
                    SELECT page_position FROM filtered WHERE entity_id=CAST(:afterId AS uuid))
                 ORDER BY page_position LIMIT :fetchLimit
            )
            SELECT page.*,
                   :revision AS dataset_revision_id,
                   page.total_views-page.previous_total_views AS delta_total_views,
                   page.median_views-page.previous_median_views AS delta_median_views,
                   page.total_reactions-page.previous_total_reactions AS delta_total_reactions,
                   page.median_reactions-page.previous_median_reactions AS delta_median_reactions,
                   page.total_comments-page.previous_total_comments AS delta_total_comments,
                   page.median_comments-page.previous_median_comments AS delta_median_comments,
                   page.total_shares-page.previous_total_shares AS delta_total_shares,
                   page.median_shares-page.previous_median_shares AS delta_median_shares,
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
             ORDER BY page.page_position,account.platform,lower(coalesce(account.current_title,account.current_username,account.canonical_external_id))
            """;

    static final String INSTITUTION = """
            WITH selected AS (
                SELECT institution.id AS institution_id,alias.legacy_id,
                       institution.canonical_name,institution.short_name
                  FROM catalog.legacy_entity_alias alias
                  JOIN catalog.visible_institution institution ON institution.id=alias.target_uuid
                 WHERE alias.entity_type='institutions' AND alias.legacy_id=:legacyId
            ), publication_latest AS (
                SELECT publication.id,latest.*
                  FROM selected
                  JOIN catalog.visible_platform_account account ON account.institution_id=selected.institution_id
                   AND (:platform='all' OR account.platform::text=:platform)
                  JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
                   AND publication.published_at>:asOf-CASE :period WHEN '3h' THEN interval '3 hours'
                       WHEN '1d' THEN interval '1 day' WHEN '7d' THEN interval '7 days' ELSE interval '30 days' END
                   AND publication.published_at<=:asOf
                  LEFT JOIN LATERAL (
                      SELECT snapshot.* FROM analytics.usable_publication_snapshot snapshot
                       WHERE snapshot.publication_id=publication.id AND snapshot.observed_at<=:asOf
                         AND snapshot.collected_at<=:asOf AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC LIMIT 1
                  ) latest ON true
            ), metric AS (
                SELECT value.metric_key,count(value.metric_value)::integer AS sample_size,
                       sum(value.metric_value)::numeric AS total_value,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY value.metric_value)::numeric,0) AS median_value,
                       max(analytics.observation_quality_rank(value.metric_quality)) AS quality_rank
                  FROM publication_latest
                 CROSS JOIN LATERAL(VALUES
                    ('views',views_count,views_quality),('reactions',reactions_count,reactions_quality)
                 ) value(metric_key,metric_value,metric_quality)
                 GROUP BY value.metric_key
            )
            SELECT selected.*,
                   max(metric.total_value) FILTER(WHERE metric_key='reactions') AS total_reactions,
                   max(metric.total_value) FILTER(WHERE metric_key='views') AS total_views,
                   max(metric.median_value) FILTER(WHERE metric_key='reactions') AS median_reactions,
                   max(metric.median_value) FILTER(WHERE metric_key='views') AS median_views,
                   coalesce(max(metric.sample_size),0) AS sample_size,
                   CASE WHEN (SELECT count(*) FROM publication_latest)=0 THEN 0::numeric
                        ELSE coalesce(max(metric.sample_size),0)::numeric/(SELECT count(*) FROM publication_latest) END AS coverage,
                   analytics.observation_quality_from_rank(max(metric.quality_rank))::text AS quality,
                   CAST(:asOf AS timestamptz) AS as_of,'{}'::jsonb AS aggregate_metadata
              FROM selected LEFT JOIN metric ON true
             GROUP BY selected.institution_id,selected.legacy_id,selected.canonical_name,selected.short_name
            """;

    static final String PUBLICATION = """
            SELECT publication.id AS publication_id,alias.legacy_id,alias.entity_type,
                   account.institution_id,account_alias.legacy_id AS account_legacy_id,
                   account_alias.entity_type AS account_legacy_type,account.current_title AS account_name,
                   account.current_username AS account_username,identity.external_id,identity.public_url,
                   publication.published_at,publication.publication_type,publication.is_repost,
                   publication.quality_flags AS presentation_flags,
                   (SELECT count(*) FROM ingest.publication_identity author
                     WHERE author.publication_id=publication.id AND author.role='joint_author') AS joint_authors,
                   publication.deleted_at,account.platform::text AS platform,
                   latest.views_count,latest.observed_at AS views_observed_at,latest.views_quality::text AS views_quality,
                   latest.reactions_count,latest.observed_at AS reactions_observed_at,latest.reactions_quality::text AS reactions_quality,
                   latest.comments_count,latest.observed_at AS comments_observed_at,latest.comments_quality::text AS comments_quality,
                   latest.shares_count,latest.observed_at AS shares_observed_at,latest.shares_quality::text AS shares_quality,
                   coalesce(latest.quality::text,'unknown') AS quality,
                   coalesce(latest.interval_uncertain,false) AS interval_uncertain,
                   coalesce(latest.synthetic,false) AS synthetic,publication.history_completeness::text AS history_completeness,
                   latest.observed_at,:revision AS dataset_revision_id
              FROM catalog.legacy_entity_alias alias
              JOIN ingest.visible_publication publication ON publication.id=alias.target_uuid
              JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
              LEFT JOIN LATERAL (SELECT candidate.* FROM catalog.legacy_entity_alias candidate
                  WHERE candidate.target_uuid=account.id AND candidate.entity_type IN('channels','platform_accounts')
                  ORDER BY CASE WHEN candidate.entity_type='channels' AND account.platform='telegram' THEN 0 ELSE 1 END LIMIT 1) account_alias ON true
              LEFT JOIN LATERAL (SELECT candidate.external_id,candidate.public_url FROM ingest.publication_identity candidate
                  WHERE candidate.publication_id=publication.id AND candidate.role='primary' ORDER BY candidate.id LIMIT 1) identity ON true
              LEFT JOIN LATERAL (SELECT snapshot.* FROM analytics.usable_publication_snapshot snapshot
                  WHERE snapshot.publication_id=publication.id AND snapshot.observed_at<=:asOf
                    AND snapshot.collected_at<=:asOf AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
                  ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC LIMIT 1) latest ON true
             WHERE alias.entity_type=:legacyType AND alias.legacy_id=:legacyId
            """;

    static final String ACCOUNT = """
            WITH aliases AS (
                SELECT target_uuid,
                       min(legacy_id) FILTER(WHERE entity_type='channels') AS channel_legacy_id,
                       min(legacy_id) FILTER(WHERE entity_type='platform_accounts') AS platform_account_legacy_id
                  FROM catalog.legacy_entity_alias WHERE entity_type IN('channels','platform_accounts') GROUP BY target_uuid
            )
            SELECT account.id AS account_id,account_alias.legacy_id,account_alias.entity_type,
                   aliases.channel_legacy_id,aliases.platform_account_legacy_id,
                   institution.id AS institution_id,institution_alias.legacy_id AS institution_legacy_id,
                   institution.canonical_name,institution.short_name,account.platform::text AS platform,
                   account.canonical_external_id,account.current_username,account.current_title,account.current_url,
                   account.access_mode::text AS access_mode,account.enabled,
                   (SELECT count(*) FROM ingest.visible_publication publication WHERE publication.primary_account_id=account.id) AS publication_count,
                   metric.observed_at AS latest_observed_at
              FROM catalog.legacy_entity_alias account_alias
              JOIN catalog.visible_platform_account account ON account.id=account_alias.target_uuid
              JOIN catalog.visible_institution institution ON institution.id=account.institution_id
              JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
               AND institution_alias.entity_type='institutions'
              LEFT JOIN aliases ON aliases.target_uuid=account.id
              LEFT JOIN LATERAL (SELECT snapshot.observed_at FROM ingest.account_metric_snapshot_active snapshot
                  WHERE snapshot.platform_account_id=account.id AND snapshot.observed_at<=:asOf
                  ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1) metric ON true
             WHERE account_alias.entity_type=:legacyType AND account_alias.legacy_id=:legacyId
            """;

    static final String COMPARISON = """
            WITH params AS (
                SELECT CAST(:asOf AS timestamptz) AS as_of,
                       (:horizonSeconds/3600)::integer AS horizon_hours,
                       md5('source|'||CAST(:revision AS text)||'|'||:platform||'|'||CAST(:horizonSeconds AS text)||'|'||CAST(:includePartial AS text))::uuid AS cohort_id
            ), requested AS (
                SELECT value::bigint AS legacy_id,ordinality::integer AS position
                  FROM jsonb_array_elements_text(CAST(:selectionLegacyIdsJson AS jsonb)) WITH ORDINALITY item(value,ordinality)
                 LIMIT :institutionLimit
            ), selections AS (
                SELECT requested.position,requested.legacy_id AS requested_legacy_id,
                       account.id AS selection_id,'channels'::text AS selection_type,
                       coalesce(nullif(account.current_title,''),CASE WHEN account.current_username IS NOT NULL
                         THEN '@'||account.current_username END,institution.short_name,institution.canonical_name) AS selection_label,
                       institution.id AS institution_id,institution_alias.legacy_id,
                       institution.canonical_name,institution.short_name,account.id AS account_id
                  FROM requested
                  LEFT JOIN catalog.legacy_entity_alias alias ON :platform='telegram'
                   AND alias.entity_type='channels' AND alias.legacy_id=requested.legacy_id
                  LEFT JOIN catalog.visible_platform_account account ON account.id=alias.target_uuid
                   AND account.platform='telegram' AND account.enabled
                  LEFT JOIN catalog.visible_institution institution ON institution.id=account.institution_id
                  LEFT JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
                   AND institution_alias.entity_type='institutions'
                 WHERE :platform='telegram'
                UNION ALL
                SELECT requested.position,requested.legacy_id,institution.id,'institutions',
                       coalesce(institution.short_name,institution.canonical_name),institution.id,alias.legacy_id,
                       institution.canonical_name,institution.short_name,NULL::uuid
                  FROM requested
                  LEFT JOIN catalog.legacy_entity_alias alias ON alias.entity_type='institutions'
                   AND alias.legacy_id=requested.legacy_id
                  LEFT JOIN catalog.visible_institution institution ON institution.id=alias.target_uuid
                 WHERE :platform<>'telegram'
                   AND (institution.id IS NULL OR EXISTS(SELECT 1 FROM catalog.visible_platform_account account
                     WHERE account.institution_id=institution.id AND account.platform::text=:platform AND account.enabled))
            ), publications AS (
                SELECT selection.*,publication.id AS publication_id,publication.history_completeness
                  FROM selections selection
                 CROSS JOIN params
                  JOIN LATERAL (
                      SELECT candidate.id,candidate.history_completeness
                        FROM catalog.visible_platform_account account
                        JOIN ingest.visible_publication candidate ON candidate.primary_account_id=account.id
                       WHERE account.enabled
                         AND ((:platform='telegram' AND account.id=selection.account_id)
                           OR (:platform<>'telegram' AND account.institution_id=selection.institution_id
                             AND account.platform::text=:platform))
                         AND candidate.published_at<=params.as_of
                         AND candidate.published_at>params.as_of-interval '7 days'
                         AND (:includePartial OR candidate.history_completeness='complete')
                       ORDER BY candidate.published_at DESC,candidate.id
                       LIMIT 20
                  ) publication ON true
            ), observed AS (
                SELECT publication.position,publication.requested_legacy_id,publication.selection_id,
                       publication.selection_type,publication.selection_label,publication.institution_id,
                       publication.legacy_id,publication.canonical_name,publication.short_name,
                       publication.publication_id,params.horizon_hours AS hour_offset,
                       CASE :metric WHEN 'views' THEN snapshot.views_count WHEN 'comments' THEN snapshot.comments_count
                         WHEN 'shares' THEN snapshot.shares_count ELSE snapshot.reactions_count END::numeric AS metric_value,
                       CASE :metric WHEN 'views' THEN snapshot.views_quality WHEN 'comments' THEN snapshot.comments_quality
                         WHEN 'shares' THEN snapshot.shares_quality ELSE snapshot.reactions_quality END AS metric_quality,
                       CASE WHEN snapshot.views_count>0 AND snapshot.reactions_count IS NOT NULL
                         THEN snapshot.reactions_count::numeric*100/snapshot.views_count END AS engagement_value,
                       greatest(analytics.observation_quality_rank(snapshot.views_quality),
                         analytics.observation_quality_rank(snapshot.reactions_quality)) AS engagement_quality_rank
                  FROM publications publication CROSS JOIN params
                  JOIN LATERAL (
                      SELECT candidate.* FROM analytics.usable_publication_snapshot candidate
                       WHERE candidate.publication_id=publication.publication_id
                         AND candidate.age_seconds>=0 AND candidate.age_seconds<=:horizonSeconds
                         AND candidate.observed_at<=params.as_of AND candidate.collected_at<=params.as_of
                         AND NOT candidate.synthetic AND candidate.quality<>'invalid'
                       ORDER BY candidate.age_seconds DESC,candidate.observed_at DESC,
                                candidate.published_month DESC,candidate.id DESC LIMIT 1
                  ) snapshot ON true
            ), cohort AS (
                SELECT selection_id,count(DISTINCT publication_id)::integer AS size
                  FROM observed GROUP BY selection_id
            ), point AS (
                SELECT selection_id,hour_offset,count(metric_value)::integer AS sample_size,
                       CASE WHEN :aggregation='sum' THEN sum(metric_value)
                            ELSE round(percentile_cont(0.5) WITHIN GROUP(ORDER BY metric_value)::numeric,0) END AS value,
                       analytics.observation_quality_from_rank(max(analytics.observation_quality_rank(metric_quality)))::text AS quality,
                       count(engagement_value)::integer AS engagement_sample_size,
                       round(percentile_cont(0.5) WITHIN GROUP(ORDER BY engagement_value)::numeric,6) AS engagement_value,
                       analytics.observation_quality_from_rank(max(engagement_quality_rank))::text AS engagement_quality
                  FROM observed GROUP BY selection_id,hour_offset
            ), total AS (SELECT count(DISTINCT publication_id)::integer AS size FROM observed)
            SELECT params.cohort_id,total.size AS cohort_sample_size,params.as_of,
                   selection.requested_legacy_id AS selection_legacy_id,selection.selection_id,
                   selection.selection_type,selection.selection_label,selection.institution_id,
                   selection.legacy_id,selection.canonical_name,selection.short_name,
                   coalesce(cohort.size,0) AS primary_cohort_size,coalesce(cohort.size,0) AS engagement_cohort_size,
                   point.hour_offset,point.value,coalesce(point.sample_size,0) AS sample_size,
                   CASE WHEN coalesce(cohort.size,0)=0 THEN 0::numeric
                        ELSE point.sample_size::numeric/cohort.size END AS coverage,
                   coalesce(point.quality,'unknown') AS quality,point.engagement_value,
                   coalesce(point.engagement_sample_size,0) AS engagement_sample_size,
                   CASE WHEN coalesce(cohort.size,0)=0 THEN 0::numeric
                        ELSE point.engagement_sample_size::numeric/cohort.size END AS engagement_coverage,
                   coalesce(point.engagement_quality,'unknown') AS engagement_quality
              FROM params CROSS JOIN total CROSS JOIN selections selection
              LEFT JOIN cohort ON cohort.selection_id=selection.selection_id
              LEFT JOIN point ON point.selection_id=selection.selection_id
             ORDER BY selection.position,point.hour_offset
            """;
}
