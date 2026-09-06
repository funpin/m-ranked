WITH filtered AS (
    SELECT card.*,
           row_number() OVER (ORDER BY
               CASE WHEN :sort = 'name' AND :direction = 'asc'
                    THEN card.sort_name END ASC NULLS LAST,
               CASE WHEN :sort = 'name' AND :direction = 'desc'
                    THEN card.sort_name END DESC NULLS LAST,
               CASE WHEN :sort <> 'name' AND :direction = 'asc' THEN
                   CASE :sort
                       WHEN 'm_rating' THEN card.rating_rank::numeric
                       WHEN 'coverage' THEN card.connected_platform_count::numeric
                       WHEN 'accounts' THEN card.account_count::numeric
                       WHEN 'subscribers' THEN card.subscriber_count::numeric
                       WHEN 'posts' THEN card.new_publication_count::numeric
                       WHEN 'views' THEN card.total_views
                       WHEN 'reactions' THEN card.total_reactions
                       ELSE card.median_reactions
                   END
               END ASC NULLS LAST,
               CASE WHEN :sort <> 'name' AND :direction = 'desc' THEN
                   CASE :sort
                       WHEN 'm_rating' THEN card.rating_rank::numeric
                       WHEN 'coverage' THEN card.connected_platform_count::numeric
                       WHEN 'accounts' THEN card.account_count::numeric
                       WHEN 'subscribers' THEN card.subscriber_count::numeric
                       WHEN 'posts' THEN card.new_publication_count::numeric
                       WHEN 'views' THEN card.total_views
                       WHEN 'reactions' THEN card.total_reactions
                       ELSE card.median_reactions
                   END
               END DESC NULLS LAST,
               card.sort_name ASC,
               card.entity_id ASC
           ) AS page_position
      FROM analytics.legacy_overview_card AS card
     WHERE card.dataset_revision_id = :revision
       AND card.platform::text = :platform
       AND card.period_key = :period
       AND (
           :search = ''
           OR card.search_text LIKE '%' || btrim(regexp_replace(
               replace(lower(:search), 'ё', 'е'),
               '[[:space:]]+', ' ', 'g'
           )) || '%'
       )
), page AS (
    SELECT filtered.*
      FROM filtered
     WHERE CAST(:afterId AS uuid) IS NULL
        OR filtered.page_position > (
            SELECT cursor_row.page_position
              FROM filtered AS cursor_row
             WHERE cursor_row.entity_id = CAST(:afterId AS uuid)
        )
     ORDER BY filtered.page_position
     LIMIT :fetchLimit
)
SELECT page.dataset_revision_id,
       page.platform::text AS platform,
       page.period_key,
       page.entity_type,
       page.entity_id,
       page.legacy_id,
       page.legacy_route,
       page.institution_id,
       page.institution_legacy_id,
       page.canonical_name,
       page.short_name,
       page.account_count,
       page.enabled_account_count,
       page.connected_platform_count,
       page.subscriber_count,
       page.last_checked_at,
       page.last_error_code,
       page.status_code,
       page.rating_rank,
       page.rating_score,
       page.rating_period,
       page.rating_fetched_at,
       page.total_publication_count,
       page.activity_publication_count,
       page.new_publication_count,
       page.total_views,
       page.median_views,
       page.previous_total_views,
       page.previous_median_views,
       page.delta_total_views,
       page.delta_median_views,
       page.total_reactions,
       page.median_reactions,
       page.previous_total_reactions,
       page.previous_median_reactions,
       page.delta_total_reactions,
       page.delta_median_reactions,
       page.total_comments,
       page.median_comments,
       page.previous_total_comments,
       page.previous_median_comments,
       page.delta_total_comments,
       page.delta_median_comments,
       page.total_shares,
       page.median_shares,
       page.previous_total_shares,
       page.previous_median_shares,
       page.delta_total_shares,
       page.delta_median_shares,
       page.as_of,
       page.aggregate_metadata,
       account.account_id,
       account.legacy_id AS account_legacy_id,
       account.legacy_route AS account_legacy_route,
       account.account_platform::text AS account_platform,
       account.canonical_external_id AS account_external_id,
       account.username AS account_username,
       account.title AS account_title,
       account.url AS account_url,
       account.access_mode::text AS account_access_mode,
       account.enabled AS account_enabled,
       account.subscriber_count AS account_subscriber_count,
       account.subscriber_display AS account_subscriber_display,
       account.subscriber_observed_at AS account_subscriber_observed_at,
       account.latest_poll_started_at AS account_latest_poll_started_at,
       account.latest_poll_completed_at AS account_latest_poll_completed_at,
       account.latest_poll_status::text AS account_latest_poll_status,
       account.latest_error_code AS account_latest_error_code
  FROM page
  LEFT JOIN analytics.legacy_overview_account AS account
    ON account.dataset_revision_id = page.dataset_revision_id
   AND account.platform = page.platform
   AND account.entity_id = page.entity_id
 ORDER BY page.page_position, account.position
