WITH selected_revision AS (
    SELECT revision.id,
           revision.committed_at AS as_of,
           revision.committed_at - CASE :period
               WHEN '3h' THEN interval '3 hours'
               WHEN '1d' THEN interval '1 day'
               WHEN '7d' THEN interval '7 days'
               ELSE interval '30 days'
           END AS cutoff
      FROM analytics.dataset_revision revision
     WHERE revision.id = :revision
),
latest_subscribers AS (
    SELECT snapshot.platform_account_id,
           snapshot.value AS subscriber_count
      FROM analytics.account_latest snapshot
     WHERE snapshot.dataset_revision_id = :revision
       AND snapshot.metric_key = 'subscribers'
),
subscriber_totals AS (
    SELECT account.institution_id,
           sum(subscriber.subscriber_count)::bigint AS subscriber_count
      FROM catalog.visible_platform_account account
      LEFT JOIN latest_subscribers subscriber
        ON subscriber.platform_account_id = account.id
     WHERE account.platform::text = :platform
       AND account.enabled
     GROUP BY account.institution_id
),
publication_facts AS (
    SELECT latest.publication_id,
           latest.institution_id,
           CASE WHEN latest.source_snapshot_refs ->> 'views'
                          = latest.source_snapshot_refs ->> 'latest'
                THEN latest.views_count END AS views_count,
           CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                          = latest.source_snapshot_refs ->> 'latest'
                THEN latest.reactions_count END AS reactions_count,
           CASE WHEN latest.source_snapshot_refs ->> 'comments'
                          = latest.source_snapshot_refs ->> 'latest'
                THEN latest.comments_count END AS comments_count,
           CASE WHEN latest.source_snapshot_refs ->> 'shares'
                          = latest.source_snapshot_refs ->> 'latest'
                THEN latest.shares_count END AS shares_count,
           CASE WHEN (CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                       = latest.source_snapshot_refs ->> 'latest'
                                 THEN latest.reactions_count END) IS NULL
                          AND (CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                       = latest.source_snapshot_refs ->> 'latest'
                                 THEN latest.comments_count END) IS NULL
                          AND (CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                       = latest.source_snapshot_refs ->> 'latest'
                                 THEN latest.shares_count END) IS NULL
                THEN NULL
                ELSE coalesce(CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                       = latest.source_snapshot_refs ->> 'latest'
                                  THEN latest.reactions_count END, 0)
                   + coalesce(CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                       = latest.source_snapshot_refs ->> 'latest'
                                  THEN latest.comments_count END, 0)
                   + coalesce(CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                       = latest.source_snapshot_refs ->> 'latest'
                                  THEN latest.shares_count END, 0)
           END AS interactions_count
      FROM selected_revision revision
      JOIN analytics.publication_latest latest
        ON latest.dataset_revision_id = revision.id
       AND latest.platform::text = :platform
      JOIN ingest.visible_publication publication
        ON publication.id = latest.publication_id
       AND publication.published_at >= revision.cutoff
      JOIN catalog.visible_platform_account account
        ON account.id = latest.platform_account_id
       AND account.enabled
),
aggregate_facts AS (
    SELECT fact.institution_id,
           count(*)::integer AS publication_count,
           avg(fact.reactions_count::numeric) AS average_reactions,
           avg(fact.views_count::numeric) AS average_views,
           coalesce(sum(fact.reactions_count), 0)::bigint AS total_reactions,
           coalesce(sum(fact.views_count), 0)::bigint AS total_views,
           coalesce(sum(fact.comments_count), 0)::bigint AS total_comments,
           coalesce(sum(fact.shares_count), 0)::bigint AS total_shares,
           coalesce(sum(fact.interactions_count), 0)::bigint AS total_interactions
      FROM publication_facts fact
     GROUP BY fact.institution_id
),
rated AS (
    SELECT institution.id AS entity_id,
           'institutions'::text AS entity_type,
           institution_alias.legacy_id,
           coalesce(institution_alias.legacy_route,
                    '/institutions/' || institution_alias.legacy_id) AS legacy_route,
           institution.id AS institution_id,
           institution_alias.legacy_id AS institution_legacy_id,
           institution.canonical_name,
           institution.short_name,
           NULL::text AS username,
           NULL::text AS title,
           aggregate.publication_count,
           aggregate.average_reactions,
           aggregate.average_views,
           aggregate.total_reactions,
           aggregate.total_views,
           aggregate.total_comments,
           aggregate.total_shares,
           aggregate.total_interactions,
           CASE WHEN aggregate.total_views > 0 THEN
               aggregate.total_interactions::numeric * 100
                   / aggregate.total_views
           END AS engagement_rate,
           subscribers.subscriber_count
      FROM aggregate_facts aggregate
      JOIN catalog.visible_institution institution
        ON institution.id = aggregate.institution_id
      JOIN catalog.legacy_entity_alias institution_alias
        ON institution_alias.target_uuid = institution.id
       AND institution_alias.entity_type = 'institutions'
      LEFT JOIN subscriber_totals subscribers
        ON subscribers.institution_id = institution.id
),
sortable AS (
    SELECT rated.*,
           CASE :channelSort
               WHEN 'average' THEN average_reactions
               WHEN 'total' THEN total_reactions::numeric
               WHEN 'views' THEN total_views::numeric
               WHEN 'subscribers' THEN subscriber_count::numeric
               ELSE engagement_rate
           END AS sort_value
      FROM rated
), positioned AS (SELECT sortable.*, row_number() OVER (ORDER BY CASE WHEN :channelDirection = 'desc' THEN sort_value END DESC NULLS LAST,
       CASE WHEN :channelDirection = 'asc' THEN sort_value END ASC NULLS LAST,
       legacy_id) AS page_position FROM sortable) 
SELECT page_position, entity_id, entity_type, legacy_id, legacy_route,
       institution_id, institution_legacy_id,
       canonical_name, short_name, username, title,
       publication_count, average_reactions, average_views, total_reactions,
       total_views, total_comments, total_shares, total_interactions,
       engagement_rate, subscriber_count
  FROM positioned
  WHERE CAST(:afterEntityId AS uuid) IS NULL OR page_position > (SELECT page_position FROM positioned WHERE entity_id = CAST(:afterEntityId AS uuid))  ORDER BY page_position LIMIT :entityFetchLimit