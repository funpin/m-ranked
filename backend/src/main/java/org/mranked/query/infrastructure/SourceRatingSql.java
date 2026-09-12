package org.mranked.query.infrastructure;

/** Bounded activity-rating reads over canonical facts. */
final class SourceRatingSql {
    private SourceRatingSql() {}

    static final String ENTITIES = """
            WITH params AS (
                SELECT CAST(:asOf AS timestamptz) AS as_of,
                       CAST(:asOf AS timestamptz)-CASE :period WHEN '3h' THEN interval '3 hours'
                           WHEN '1d' THEN interval '1 day' WHEN '7d' THEN interval '7 days'
                           ELSE interval '30 days' END AS cutoff
            ), account_base AS (
                SELECT account.*,
                       subscriber.subscriber_count,
                       channel_alias.legacy_id AS channel_legacy_id,
                       channel_alias.legacy_route AS channel_legacy_route
                  FROM catalog.visible_platform_account account CROSS JOIN params
                  LEFT JOIN LATERAL (
                      SELECT snapshot.subscriber_count FROM ingest.account_metric_snapshot_active snapshot
                       WHERE snapshot.platform_account_id=account.id AND snapshot.observed_at<=params.as_of
                         AND snapshot.collected_at<=params.as_of AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1
                  ) subscriber ON true
                  LEFT JOIN LATERAL (
                      SELECT alias.legacy_id,alias.legacy_route FROM catalog.legacy_entity_alias alias
                       WHERE alias.target_uuid=account.id AND alias.entity_type='channels'
                       ORDER BY alias.legacy_id LIMIT 1
                  ) channel_alias ON true
                 WHERE account.enabled AND account.platform::text=:platform
            ), dimension_candidates AS (
                SELECT account.id AS entity_id,'channels'::text AS entity_type,
                       account.channel_legacy_id AS legacy_id,account.channel_legacy_route AS legacy_route,
                       institution.id AS institution_id,institution_alias.legacy_id AS institution_legacy_id,
                       institution.canonical_name,institution.short_name,
                       account.current_username AS username,account.current_title AS title,
                       account.subscriber_count::bigint AS subscriber_count
                  FROM account_base account
                  JOIN catalog.visible_institution institution ON institution.id=account.institution_id
                  LEFT JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid=institution.id AND institution_alias.entity_type='institutions'
                 WHERE :platform='telegram' AND account.channel_legacy_id IS NOT NULL
                UNION ALL
                SELECT institution.id,'institutions',institution_alias.legacy_id,institution_alias.legacy_route,
                       institution.id,institution_alias.legacy_id,institution.canonical_name,institution.short_name,
                       NULL::text,NULL::text,sum(account.subscriber_count)::bigint
                  FROM catalog.visible_institution institution
                  JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid=institution.id AND institution_alias.entity_type='institutions'
                  JOIN account_base account ON account.institution_id=institution.id
                 WHERE :platform<>'telegram'
                 GROUP BY institution.id,institution_alias.legacy_id,institution_alias.legacy_route,
                          institution.canonical_name,institution.short_name
            ), dimensions AS (
                SELECT * FROM dimension_candidates
                 ORDER BY subscriber_count DESC NULLS LAST,entity_id LIMIT 100
            ), facts AS (
                SELECT dimension.entity_id,publication.id AS publication_id,
                       latest.views_count,latest.reactions_count,latest.comments_count,latest.shares_count
                  FROM dimensions dimension CROSS JOIN params
                  JOIN LATERAL (
                      SELECT candidate.id,date_trunc('month',candidate.published_at AT TIME ZONE 'UTC')::date AS published_month
                        FROM account_base account
                        JOIN ingest.visible_publication candidate ON candidate.primary_account_id=account.id
                       WHERE ((:platform='telegram' AND account.id=dimension.entity_id)
                           OR (:platform<>'telegram' AND account.institution_id=dimension.institution_id))
                         AND candidate.published_at>=params.cutoff AND candidate.published_at<=params.as_of
                       ORDER BY candidate.published_at DESC,candidate.id LIMIT 20
                  ) publication ON true
                  LEFT JOIN LATERAL (
                      SELECT snapshot.views_count,snapshot.reactions_count,snapshot.comments_count,snapshot.shares_count
                        FROM analytics.publication_snapshot_slice(publication.id,publication.published_month) snapshot
                       WHERE snapshot.publication_id=publication.id AND snapshot.observed_at<=params.as_of
                         AND snapshot.published_month=publication.published_month
                         AND snapshot.collected_at<=params.as_of AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC LIMIT 1
                  ) latest ON true
            ), rated AS (
                SELECT dimension.*,count(fact.publication_id)::integer AS publication_count,
                       coalesce(avg(fact.reactions_count::numeric),0) AS average_reactions,
                       avg(fact.views_count::numeric) AS average_views,
                       coalesce(sum(coalesce(fact.reactions_count,0)),0)::bigint AS total_reactions,
                       sum(fact.views_count)::bigint AS total_views,
                       sum(fact.comments_count)::bigint AS total_comments,
                       sum(fact.shares_count)::bigint AS total_shares,
                       sum(CASE WHEN fact.reactions_count IS NULL AND fact.comments_count IS NULL AND fact.shares_count IS NULL
                           THEN NULL ELSE coalesce(fact.reactions_count,0)+coalesce(fact.comments_count,0)+coalesce(fact.shares_count,0) END)::bigint AS total_interactions,
                       CASE WHEN dimension.subscriber_count>0 THEN
                           coalesce(avg(fact.reactions_count::numeric),0)*100/dimension.subscriber_count END AS engagement_rate
                  FROM dimensions dimension LEFT JOIN facts fact ON fact.entity_id=dimension.entity_id
                 GROUP BY dimension.entity_id,dimension.entity_type,dimension.legacy_id,dimension.legacy_route,
                          dimension.institution_id,dimension.institution_legacy_id,dimension.canonical_name,
                          dimension.short_name,dimension.username,dimension.title,dimension.subscriber_count
            ), sortable AS (
                SELECT rated.*,CASE :channelSort WHEN 'average' THEN average_reactions
                       WHEN 'total' THEN total_reactions::numeric WHEN 'views' THEN total_views::numeric
                       WHEN 'subscribers' THEN subscriber_count::numeric ELSE engagement_rate END AS sort_value
                  FROM rated
            ), positioned AS (
                SELECT sortable.*,row_number() OVER(ORDER BY
                       CASE WHEN :channelDirection='desc' THEN sort_value END DESC NULLS LAST,
                       CASE WHEN :channelDirection='asc' THEN sort_value END ASC NULLS FIRST,
                       lower(coalesce(username,short_name,canonical_name,'')),legacy_id) AS page_position
                  FROM sortable
            )
            SELECT * FROM positioned
             WHERE CAST(:afterEntityId AS uuid) IS NULL OR page_position>(
                 SELECT page_position FROM positioned WHERE entity_id=CAST(:afterEntityId AS uuid))
             ORDER BY page_position LIMIT :entityFetchLimit
            """;

    static final String PUBLICATIONS = """
            WITH params AS (
                SELECT CAST(:asOf AS timestamptz) AS as_of,
                       CAST(:asOf AS timestamptz)-CASE :period WHEN '3h' THEN interval '3 hours'
                           WHEN '1d' THEN interval '1 day' WHEN '7d' THEN interval '7 days'
                           ELSE interval '30 days' END AS cutoff
            ), candidates AS (
                SELECT publication.id AS publication_id,publication.primary_account_id AS account_id,
                       publication.published_at,date_trunc('month',publication.published_at AT TIME ZONE 'UTC')::date AS published_month,
                       publication.deleted_at,publication.is_repost,
                       account.institution_id,account.current_username,account.current_title,
                       account.platform::text AS platform
                  FROM ingest.visible_publication publication
                  JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
                 CROSS JOIN params
                 WHERE account.enabled AND account.platform::text=:platform
                   AND publication.published_at>=params.cutoff AND publication.published_at<=params.as_of
                 ORDER BY publication.published_at DESC,publication.id LIMIT 200
            ), facts AS (
                SELECT candidate.*,publication_alias.legacy_id,publication_alias.legacy_route,
                       institution_alias.legacy_id AS institution_legacy_id,
                       institution.canonical_name AS institution_canonical_name,
                       institution.short_name AS institution_short_name,
                       account_alias.legacy_id AS account_legacy_id,
                       identity.external_id,identity.public_url,
                       latest.views_count AS views,latest.reactions_count AS reactions,
                       latest.comments_count AS comments,latest.shares_count AS shares,
                       subscriber.subscriber_count,
                       (SELECT count(*) FROM ingest.publication_identity author
                         WHERE author.publication_id=candidate.publication_id AND author.role='joint_author')::integer AS additional_author_count
                  FROM candidates candidate CROSS JOIN params
                  JOIN catalog.visible_institution institution ON institution.id=candidate.institution_id
                  LEFT JOIN catalog.legacy_entity_alias institution_alias
                    ON institution_alias.target_uuid=institution.id AND institution_alias.entity_type='institutions'
                  LEFT JOIN LATERAL (
                      SELECT alias.legacy_id,alias.legacy_route FROM catalog.legacy_entity_alias alias
                       WHERE alias.target_uuid=candidate.publication_id
                         AND alias.entity_type=CASE WHEN :platform='telegram' THEN 'posts' ELSE 'platform_posts' END
                       ORDER BY alias.legacy_id LIMIT 1
                  ) publication_alias ON true
                  LEFT JOIN LATERAL (
                      SELECT alias.legacy_id FROM catalog.legacy_entity_alias alias
                       WHERE alias.target_uuid=candidate.account_id
                         AND alias.entity_type=CASE WHEN :platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
                       ORDER BY alias.legacy_id LIMIT 1
                  ) account_alias ON true
                  LEFT JOIN LATERAL (
                      SELECT value.external_id,value.public_url FROM ingest.publication_identity value
                       WHERE value.publication_id=candidate.publication_id AND value.role='primary'
                       ORDER BY value.id LIMIT 1
                  ) identity ON true
                  LEFT JOIN LATERAL (
                      SELECT snapshot.views_count,snapshot.reactions_count,snapshot.comments_count,snapshot.shares_count
                        FROM analytics.publication_snapshot_slice(candidate.publication_id,candidate.published_month) snapshot
                       WHERE snapshot.publication_id=candidate.publication_id AND snapshot.observed_at<=params.as_of
                         AND snapshot.published_month=candidate.published_month
                         AND snapshot.collected_at<=params.as_of AND NOT snapshot.synthetic AND snapshot.quality<>'invalid'
                       ORDER BY snapshot.observed_at DESC,snapshot.published_month DESC,snapshot.id DESC LIMIT 1
                  ) latest ON true
                  LEFT JOIN LATERAL (
                      SELECT snapshot.subscriber_count FROM ingest.account_metric_snapshot_active snapshot
                       WHERE snapshot.platform_account_id=candidate.account_id AND snapshot.observed_at<=params.as_of
                       ORDER BY snapshot.observed_at DESC,snapshot.id DESC LIMIT 1
                  ) subscriber ON true
            ), sortable AS (
                SELECT fact.*,
                       CASE WHEN reactions IS NULL AND comments IS NULL AND shares IS NULL THEN NULL
                           ELSE coalesce(reactions,0)+coalesce(comments,0)+coalesce(shares,0) END::bigint AS interactions,
                       CASE WHEN subscriber_count>0 THEN reactions::numeric*100/subscriber_count END AS subscriber_share,
                       CASE WHEN views>0 THEN reactions::numeric*100/views END AS view_share
                  FROM facts fact
            )
            SELECT publication_id,legacy_id,
                   CASE WHEN :platform='telegram' THEN 'posts' ELSE 'platform_posts' END AS legacy_type,
                   legacy_route,institution_id,institution_legacy_id,institution_canonical_name,
                   institution_short_name,account_id,account_legacy_id,current_username AS account_username,
                   current_title AS account_title,external_id,public_url,published_at,deleted_at,
                   additional_author_count>0 AS joint,additional_author_count,is_repost AS repost,
                   views,reactions,comments,shares,interactions,subscriber_share,view_share
              FROM sortable
             ORDER BY
                   CASE WHEN :postDirection='desc' THEN CASE :postSort WHEN 'views' THEN views::numeric
                       WHEN 'comments' THEN comments::numeric WHEN 'shares' THEN shares::numeric
                       WHEN 'interactions' THEN interactions::numeric WHEN 'subscriber_share' THEN subscriber_share
                       WHEN 'view_share' THEN view_share ELSE reactions::numeric END END DESC NULLS LAST,
                   CASE WHEN :postDirection='asc' THEN CASE :postSort WHEN 'views' THEN views::numeric
                       WHEN 'comments' THEN comments::numeric WHEN 'shares' THEN shares::numeric
                       WHEN 'interactions' THEN interactions::numeric WHEN 'subscriber_share' THEN subscriber_share
                       WHEN 'view_share' THEN view_share ELSE reactions::numeric END END ASC NULLS FIRST,
                   published_at DESC,publication_id LIMIT 50
            """;
}
