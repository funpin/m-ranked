package org.mranked.query.infrastructure;

/**
 * Revision-pinned read SQL for the legacy activity rating. These queries read
 * the rebuilt latest projection and never rescan raw publication snapshots.
 */
final class ActivityRatingSql {
    private ActivityRatingSql() {
    }

    static final String TELEGRAM_ENTITIES = """
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
                SELECT DISTINCT ON (snapshot.platform_account_id)
                       snapshot.platform_account_id,
                       snapshot.subscriber_count
                  FROM ingest.account_metric_snapshot snapshot
                  CROSS JOIN selected_revision revision
                 WHERE snapshot.observed_at <= revision.as_of
                   AND snapshot.collected_at <= revision.as_of
                   AND snapshot.quality <> 'invalid'
                 ORDER BY snapshot.platform_account_id,
                          snapshot.observed_at DESC,
                          snapshot.id DESC
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
                  FROM catalog.platform_account account
                  JOIN catalog.legacy_entity_alias channel_alias
                    ON channel_alias.target_uuid = account.id
                   AND channel_alias.entity_type = 'channels'
                  JOIN catalog.institution institution
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
                  JOIN ingest.publication publication
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
            )
            SELECT entity_id, entity_type, legacy_id, legacy_route,
                   institution_id, institution_legacy_id,
                   canonical_name, short_name, username, title,
                   publication_count, average_reactions, average_views, total_reactions,
                   total_views, total_comments, total_shares, total_interactions,
                   engagement_rate, subscriber_count
              FROM sortable
             ORDER BY
                   CASE WHEN :channelDirection = 'desc' THEN sort_value END DESC NULLS LAST,
                   CASE WHEN :channelDirection = 'asc' THEN sort_value END ASC NULLS FIRST,
                   lower(coalesce(username, '')), legacy_id
             LIMIT :entityFetchLimit
            """;

    static final String PLATFORM_ENTITIES = """
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
                SELECT DISTINCT ON (snapshot.platform_account_id)
                       snapshot.platform_account_id,
                       snapshot.subscriber_count
                  FROM ingest.account_metric_snapshot snapshot
                  CROSS JOIN selected_revision revision
                 WHERE snapshot.observed_at <= revision.as_of
                   AND snapshot.collected_at <= revision.as_of
                   AND snapshot.quality <> 'invalid'
                 ORDER BY snapshot.platform_account_id,
                          snapshot.observed_at DESC,
                          snapshot.id DESC
            ),
            subscriber_totals AS (
                SELECT account.institution_id,
                       sum(subscriber.subscriber_count)::bigint AS subscriber_count
                  FROM catalog.platform_account account
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
                  JOIN ingest.publication publication
                    ON publication.id = latest.publication_id
                   AND publication.published_at >= revision.cutoff
                  JOIN catalog.platform_account account
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
                  JOIN catalog.institution institution
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
            )
            SELECT entity_id, entity_type, legacy_id, legacy_route,
                   institution_id, institution_legacy_id,
                   canonical_name, short_name, username, title,
                   publication_count, average_reactions, average_views, total_reactions,
                   total_views, total_comments, total_shares, total_interactions,
                   engagement_rate, subscriber_count
              FROM sortable
             ORDER BY
                   CASE WHEN :channelDirection = 'desc' THEN sort_value END DESC NULLS LAST,
                   CASE WHEN :channelDirection = 'asc' THEN sort_value END ASC NULLS LAST,
                   legacy_id
             LIMIT :entityFetchLimit
            """;

    static final String TELEGRAM_PUBLICATIONS = """
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
                SELECT DISTINCT ON (snapshot.platform_account_id)
                       snapshot.platform_account_id,
                       snapshot.subscriber_count
                  FROM ingest.account_metric_snapshot snapshot
                  CROSS JOIN selected_revision revision
                 WHERE snapshot.observed_at <= revision.as_of
                   AND snapshot.collected_at <= revision.as_of
                   AND snapshot.quality <> 'invalid'
                 ORDER BY snapshot.platform_account_id,
                          snapshot.observed_at DESC,
                          snapshot.id DESC
            ),
            publication_rows AS (
                SELECT publication.id AS publication_id,
                       publication_alias.legacy_id,
                       'posts'::text AS legacy_type,
                       coalesce(publication_alias.legacy_route,
                                CASE WHEN publication_alias.legacy_id IS NOT NULL
                                     THEN '/posts/' || publication_alias.legacy_id END)
                           AS legacy_route,
                       institution.id AS institution_id,
                       institution_alias.legacy_id AS institution_legacy_id,
                       institution.canonical_name AS institution_canonical_name,
                       institution.short_name AS institution_short_name,
                       account.id AS account_id,
                       account_alias.legacy_id AS account_legacy_id,
                       account.current_username AS account_username,
                       account.current_title AS account_title,
                       identity.external_id,
                       identity.public_url,
                       publication.published_at,
                       publication.deleted_at,
                       false AS joint,
                       0 AS additional_author_count,
                       publication.is_repost AS repost,
                       CASE WHEN latest.source_snapshot_refs ->> 'views'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.views_count END AS views,
                       CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.reactions_count END AS reactions,
                       CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.comments_count END AS comments,
                       CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.shares_count END AS shares,
                       NULL::bigint AS interactions,
                       CASE WHEN subscriber.subscriber_count > 0 THEN
                           (CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                           = latest.source_snapshot_refs ->> 'latest'
                                 THEN latest.reactions_count END)::numeric * 100
                               / subscriber.subscriber_count
                       END AS subscriber_share,
                       CASE WHEN (CASE WHEN latest.source_snapshot_refs ->> 'views'
                                                = latest.source_snapshot_refs ->> 'latest'
                                      THEN latest.views_count END) > 0 THEN
                           (CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                           = latest.source_snapshot_refs ->> 'latest'
                                 THEN latest.reactions_count END)::numeric * 100
                               / (CASE WHEN latest.source_snapshot_refs ->> 'views'
                                                = latest.source_snapshot_refs ->> 'latest'
                                      THEN latest.views_count END)
                       END AS view_share
                  FROM selected_revision revision
                  JOIN analytics.publication_latest latest
                    ON latest.dataset_revision_id = revision.id
                   AND latest.platform = 'telegram'
                  JOIN ingest.publication publication
                    ON publication.id = latest.publication_id
                   AND publication.published_at >= revision.cutoff
                  JOIN catalog.platform_account account
                    ON account.id = latest.platform_account_id
                   AND account.enabled
                  JOIN catalog.institution institution
                    ON institution.id = latest.institution_id
                  JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid = institution.id
                   AND institution_alias.entity_type = 'institutions'
                  JOIN catalog.legacy_entity_alias account_alias
                    ON account_alias.target_uuid = account.id
                   AND account_alias.entity_type = 'channels'
                  LEFT JOIN catalog.legacy_entity_alias publication_alias
                    ON publication_alias.target_uuid = publication.id
                   AND publication_alias.entity_type = 'posts'
                  LEFT JOIN latest_subscribers subscriber
                    ON subscriber.platform_account_id = account.id
                  LEFT JOIN LATERAL (
                      SELECT publication_identity.external_id,
                             publication_identity.public_url
                        FROM ingest.publication_identity publication_identity
                       WHERE publication_identity.publication_id = publication.id
                       ORDER BY (publication_identity.role = 'primary') DESC,
                                publication_identity.id
                       LIMIT 1
                  ) identity ON true
            ),
            sortable AS (
                SELECT publication_rows.*,
                       CASE :postSort
                           WHEN 'reactions' THEN reactions::numeric
                           WHEN 'subscriber_share' THEN subscriber_share
                           WHEN 'views' THEN views::numeric
                           ELSE view_share
                       END AS sort_value
                  FROM publication_rows
            )
            SELECT publication_id, legacy_id, legacy_type, legacy_route,
                   institution_id, institution_legacy_id,
                   institution_canonical_name, institution_short_name,
                   account_id, account_legacy_id, account_username, account_title,
                   external_id, public_url, published_at, deleted_at,
                   joint, additional_author_count, repost,
                   views, reactions, comments, shares, interactions,
                   subscriber_share, view_share
              FROM sortable
             ORDER BY
                   CASE WHEN :postDirection = 'desc' THEN sort_value END DESC NULLS LAST,
                   CASE WHEN :postDirection = 'asc' THEN sort_value END ASC NULLS FIRST,
                   legacy_id ASC NULLS LAST, publication_id
             LIMIT 50
            """;

    static final String PLATFORM_PUBLICATIONS = """
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
            publication_rows AS (
                SELECT publication.id AS publication_id,
                       publication_alias.legacy_id,
                       'platform_posts'::text AS legacy_type,
                       coalesce(publication_alias.legacy_route,
                                CASE WHEN publication_alias.legacy_id IS NOT NULL
                                     THEN '/platform-posts/' || publication_alias.legacy_id END)
                           AS legacy_route,
                       institution.id AS institution_id,
                       institution_alias.legacy_id AS institution_legacy_id,
                       institution.canonical_name AS institution_canonical_name,
                       institution.short_name AS institution_short_name,
                       account.id AS account_id,
                       account_alias.legacy_id AS account_legacy_id,
                       account.current_username AS account_username,
                       account.current_title AS account_title,
                       identity.external_id,
                       identity.public_url,
                       publication.published_at,
                       publication.deleted_at,
                       (coalesce(
                           CASE WHEN jsonb_typeof(publication.quality_flags -> 'joint_post')
                                     = 'boolean'
                                THEN (publication.quality_flags ->> 'joint_post')::boolean
                           END,
                           false
                       ) OR coalesce(
                           CASE WHEN jsonb_typeof(publication.quality_flags -> 'legacy_is_joint')
                                     = 'boolean'
                                THEN (publication.quality_flags ->> 'legacy_is_joint')::boolean
                           END,
                           false
                       ) OR joint_authors.author_count > 0) AS joint,
                       greatest(
                           coalesce(CASE WHEN jsonb_typeof(
                                         publication.quality_flags
                                             -> 'additional_author_count'
                                     ) = 'number'
                                THEN (publication.quality_flags
                                          ->> 'additional_author_count')::integer
                           END, 0),
                           coalesce(CASE WHEN jsonb_typeof(
                                         publication.quality_flags
                                             -> 'legacy_additional_author_count'
                                     ) = 'number'
                                THEN (publication.quality_flags
                                          ->> 'legacy_additional_author_count')::integer
                           END, 0),
                           joint_authors.author_count,
                           0
                       ) AS additional_author_count,
                       publication.is_repost AS repost,
                       CASE WHEN latest.source_snapshot_refs ->> 'views'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.views_count END AS views,
                       CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.reactions_count END AS reactions,
                       CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.comments_count END AS comments,
                       CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                      = latest.source_snapshot_refs ->> 'latest'
                            THEN latest.shares_count END AS shares,
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
                       END AS interactions,
                       NULL::numeric AS subscriber_share,
                       CASE WHEN (CASE WHEN latest.source_snapshot_refs ->> 'views'
                                                = latest.source_snapshot_refs ->> 'latest'
                                      THEN latest.views_count END) > 0
                                      AND NOT (
                                          (CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                                         = latest.source_snapshot_refs ->> 'latest'
                                                THEN latest.reactions_count END) IS NULL
                                          AND (CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                                         = latest.source_snapshot_refs ->> 'latest'
                                                THEN latest.comments_count END) IS NULL
                                          AND (CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                                         = latest.source_snapshot_refs ->> 'latest'
                                                THEN latest.shares_count END) IS NULL
                                      )
                            THEN (coalesce(CASE WHEN latest.source_snapshot_refs ->> 'reactions'
                                                        = latest.source_snapshot_refs ->> 'latest'
                                               THEN latest.reactions_count END, 0)
                                + coalesce(CASE WHEN latest.source_snapshot_refs ->> 'comments'
                                                        = latest.source_snapshot_refs ->> 'latest'
                                               THEN latest.comments_count END, 0)
                                + coalesce(CASE WHEN latest.source_snapshot_refs ->> 'shares'
                                                        = latest.source_snapshot_refs ->> 'latest'
                                               THEN latest.shares_count END, 0))::numeric * 100
                                 / (CASE WHEN latest.source_snapshot_refs ->> 'views'
                                                  = latest.source_snapshot_refs ->> 'latest'
                                        THEN latest.views_count END)
                       END AS view_share
                  FROM selected_revision revision
                  JOIN analytics.publication_latest latest
                    ON latest.dataset_revision_id = revision.id
                   AND latest.platform::text = :platform
                  JOIN ingest.publication publication
                    ON publication.id = latest.publication_id
                   AND publication.published_at >= revision.cutoff
                  JOIN catalog.platform_account account
                    ON account.id = latest.platform_account_id
                   AND account.enabled
                  JOIN catalog.institution institution
                    ON institution.id = latest.institution_id
                  JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid = institution.id
                   AND institution_alias.entity_type = 'institutions'
                  LEFT JOIN catalog.legacy_entity_alias account_alias
                    ON account_alias.target_uuid = account.id
                   AND account_alias.entity_type = 'platform_accounts'
                  LEFT JOIN catalog.legacy_entity_alias publication_alias
                    ON publication_alias.target_uuid = publication.id
                   AND publication_alias.entity_type = 'platform_posts'
                  LEFT JOIN LATERAL (
                      SELECT publication_identity.external_id,
                             publication_identity.public_url
                        FROM ingest.publication_identity publication_identity
                       WHERE publication_identity.publication_id = publication.id
                       ORDER BY (publication_identity.role = 'primary') DESC,
                                publication_identity.id
                       LIMIT 1
                  ) identity ON true
                  LEFT JOIN LATERAL (
                      SELECT count(*)::integer AS author_count
                        FROM ingest.publication_identity publication_identity
                       WHERE publication_identity.publication_id = publication.id
                         AND publication_identity.role = 'joint_author'
                  ) joint_authors ON true
            ),
            sortable AS (
                SELECT publication_rows.*,
                       CASE :postSort
                           WHEN 'reactions' THEN reactions::numeric
                           WHEN 'views' THEN views::numeric
                           WHEN 'comments' THEN comments::numeric
                           WHEN 'shares' THEN shares::numeric
                           WHEN 'interactions' THEN interactions::numeric
                           ELSE view_share
                       END AS sort_value
                  FROM publication_rows
            )
            SELECT publication_id, legacy_id, legacy_type, legacy_route,
                   institution_id, institution_legacy_id,
                   institution_canonical_name, institution_short_name,
                   account_id, account_legacy_id, account_username, account_title,
                   external_id, public_url, published_at, deleted_at,
                   joint, additional_author_count, repost,
                   views, reactions, comments, shares, interactions,
                   subscriber_share, view_share
              FROM sortable
             ORDER BY
                   CASE WHEN :postDirection = 'desc' THEN sort_value END DESC NULLS LAST,
                   CASE WHEN :postDirection = 'asc' THEN sort_value END ASC NULLS LAST,
                   legacy_id ASC NULLS LAST, publication_id
             LIMIT 50
            """;
}
