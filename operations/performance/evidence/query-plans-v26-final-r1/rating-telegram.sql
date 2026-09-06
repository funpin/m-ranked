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
enabled_channels AS (
    SELECT account.id AS entity_id,
           channel_alias.legacy_id,
           coalesce(channel_alias.legacy_route,
                    '/channels/' || channel_alias.legacy_id) AS legacy_route,
           institution.id AS institution_id,
           institution_alias.legacy_id AS institution_legacy_id,
           institution.canonical_name,
           institution.short_name,
           account.current_username AS username,
           account.current_title AS title,
           subscriber.subscriber_count
      FROM catalog.visible_platform_account account
      JOIN catalog.legacy_entity_alias channel_alias
        ON channel_alias.target_uuid = account.id
       AND channel_alias.entity_type = 'channels'
      JOIN catalog.visible_institution institution
        ON institution.id = account.institution_id
      LEFT JOIN catalog.legacy_entity_alias institution_alias
        ON institution_alias.target_uuid = institution.id
       AND institution_alias.entity_type = 'institutions'
      LEFT JOIN latest_subscribers subscriber
        ON subscriber.platform_account_id = account.id
     WHERE account.platform = 'telegram'
       AND account.enabled
),
publication_facts AS (
    SELECT latest.publication_id,
           latest.platform_account_id,
           CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                          = latest.source_snapshot_refs ->> 'latest'
                THEN latest.reactions_count END AS reactions_count
      FROM selected_revision revision
      JOIN analytics.publication_latest latest
        ON latest.dataset_revision_id = revision.id
       AND latest.platform = 'telegram'
      JOIN ingest.visible_publication publication
        ON publication.id = latest.publication_id
       AND publication.published_at >= revision.cutoff
),
rated AS (
    SELECT channel.entity_id,
           'channels'::text AS entity_type,
           channel.legacy_id,
           channel.legacy_route,
           channel.institution_id,
           channel.institution_legacy_id,
           channel.canonical_name,
           channel.short_name,
           channel.username,
           channel.title,
           count(fact.publication_id)::integer AS publication_count,
           CASE WHEN count(fact.publication_id) = 0 THEN 0::numeric
                ELSE sum(coalesce(fact.reactions_count, 0))::numeric
                     / count(fact.publication_id)
           END AS average_reactions,
           NULL::numeric AS average_views,
           coalesce(sum(coalesce(fact.reactions_count, 0)), 0)::bigint
               AS total_reactions,
           NULL::bigint AS total_views,
           NULL::bigint AS total_comments,
           NULL::bigint AS total_shares,
           NULL::bigint AS total_interactions,
           CASE WHEN channel.subscriber_count > 0 THEN
               (CASE WHEN count(fact.publication_id) = 0 THEN 0::numeric
                     ELSE sum(coalesce(fact.reactions_count, 0))::numeric
                          / count(fact.publication_id)
                END) * 100 / channel.subscriber_count
           END AS engagement_rate,
           channel.subscriber_count
      FROM enabled_channels channel
      LEFT JOIN publication_facts fact
        ON fact.platform_account_id = channel.entity_id
     GROUP BY channel.entity_id, channel.legacy_id, channel.legacy_route,
              channel.institution_id, channel.institution_legacy_id,
              channel.canonical_name, channel.short_name,
              channel.username, channel.title, channel.subscriber_count
),
sortable AS (
    SELECT rated.*,
           CASE :channelSort
               WHEN 'average' THEN average_reactions
               WHEN 'total' THEN total_reactions::numeric
               WHEN 'subscribers' THEN subscriber_count::numeric
               ELSE engagement_rate
           END AS sort_value
      FROM rated
), positioned AS (SELECT sortable.*, row_number() OVER (ORDER BY CASE WHEN :channelDirection = 'desc' THEN sort_value END DESC NULLS LAST,
       CASE WHEN :channelDirection = 'asc' THEN sort_value END ASC NULLS FIRST,
       lower(coalesce(username, '')), legacy_id) AS page_position FROM sortable) 
SELECT page_position, entity_id, entity_type, legacy_id, legacy_route,
       institution_id, institution_legacy_id,
       canonical_name, short_name, username, title,
       publication_count, average_reactions, average_views, total_reactions,
       total_views, total_comments, total_shares, total_interactions,
       engagement_rate, subscriber_count
  FROM positioned
  WHERE CAST(:afterEntityId AS uuid) IS NULL OR page_position > (SELECT page_position FROM positioned WHERE entity_id = CAST(:afterEntityId AS uuid))  ORDER BY page_position LIMIT :entityFetchLimit