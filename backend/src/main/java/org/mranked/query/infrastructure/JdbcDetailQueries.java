package org.mranked.query.infrastructure;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.mranked.analytics.domain.CounterMetric;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.InstitutionIdentity;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.domain.AccountView;
import org.mranked.query.domain.HistorySnapshot;
import org.mranked.query.domain.PublicationListItem;
import org.springframework.jdbc.core.simple.JdbcClient;

/** Bounded detail reads over catalog identities and same-observation projections. */
final class JdbcDetailQueries {
    private final JdbcClient jdbc;
    private static final tools.jackson.databind.ObjectMapper JSON = new tools.jackson.databind.json.JsonMapper();
    JdbcDetailQueries(JdbcClient jdbc) {this.jdbc=jdbc;}

    org.mranked.query.domain.AccountStats stats(UUID account,Platform platform,int retentionDays,long revision) {
        return jdbc.sql("""
            WITH publications AS (
                SELECT p.* FROM ingest.visible_publication p
                JOIN analytics.dataset_revision revision ON revision.id=:revision
                WHERE primary_account_id=:account AND published_at>=revision.committed_at-make_interval(days=>:days)
                  AND published_at<=revision.committed_at
            ), latest AS (
                SELECT p.id,history.* FROM publications p
                LEFT JOIN LATERAL (SELECT h.* FROM analytics.publication_history h WHERE h.publication_id=p.id
                    AND h.dataset_revision_id=:revision
                    AND (:platform<>'telegram' OR NOT h.synthetic)
                    ORDER BY h.observed_at DESC,h.snapshot_id DESC LIMIT 1) history ON true
            ), metric AS (
                SELECT v.key,percentile_cont(0.5) WITHIN GROUP(ORDER BY v.value) AS median_value,
                    count(v.value) AS sample_size,count(*) AS population,
                    (array_agg(v.quality ORDER BY CASE v.quality WHEN 'exact' THEN 1 WHEN 'rounded' THEN 2
                        WHEN 'estimated' THEN 3 WHEN 'unknown' THEN 4 WHEN 'degraded' THEN 5 ELSE 6 END DESC)
                        FILTER(WHERE v.value IS NOT NULL))[1] AS quality
                FROM latest CROSS JOIN LATERAL(VALUES ('views',views_count,views_quality::text),
                    ('reactions',reactions_count,reactions_quality::text),('comments',comments_count,comments_quality::text)) v(key,value,quality)
                GROUP BY v.key
            )
            SELECT revision.committed_at,
                (SELECT count(*) FROM publications) AS post_count,
                (SELECT count(*) FROM publications WHERE history_completeness='complete') AS monitored,
                coalesce((SELECT jsonb_object_agg(key,jsonb_build_object('value',median_value,'sampleSize',sample_size,
                    'coverage',CASE WHEN population=0 THEN 0 ELSE sample_size::numeric/population END,
                    'quality',coalesce(quality,'unknown'))) FROM metric),'{}'::jsonb) AS medians,
                card.rating_rank,card.rating_period,subscribers.value AS subscriber_count,
                account.latest_error_code,account.last_checked_at
            FROM analytics.dataset_revision revision
            JOIN catalog.visible_platform_account identity ON identity.id=:account
            LEFT JOIN LATERAL(SELECT a.* FROM analytics.legacy_overview_account a
                WHERE a.account_id=:account AND a.dataset_revision_id=:revision
                ORDER BY CASE WHEN a.platform::text=:platform THEN 0 ELSE 1 END LIMIT 1) account ON true
            LEFT JOIN analytics.legacy_overview_card card ON card.platform::text=:platform AND card.period_key='1d'
                AND card.entity_id=CASE WHEN :platform='telegram' THEN identity.id ELSE identity.institution_id END
                AND card.dataset_revision_id=:revision
            LEFT JOIN analytics.account_latest subscribers ON subscribers.platform_account_id=:account
                AND subscribers.dataset_revision_id=:revision
            WHERE revision.id=:revision
            """).param("account",account).param("platform",platform.databaseValue()).param("days",retentionDays)
                .param("revision",revision).query((row,index)->{
                    var values=JSON.readTree(row.getString("medians"));Instant asOf=instant(row,"committed_at");
                    return new org.mranked.query.domain.AccountStats(retentionDays,row.getLong("post_count"),row.getLong("monitored"),
                            aggregate(values,"reactions",revision,asOf),aggregate(values,"views",revision,asOf),aggregate(values,"comments",revision,asOf),
                            row.getObject("rating_rank",Integer.class),row.getString("rating_period"),row.getObject("subscriber_count",Long.class),
                            row.getString("latest_error_code"),instant(row,"last_checked_at"));
                }).single();
    }

    private static org.mranked.analytics.domain.AggregateMetric aggregate(tools.jackson.databind.JsonNode tree,
            String key,long revision,Instant asOf) {
        var node=tree.path(key);
        var value=node.path("value");
        return new org.mranked.analytics.domain.AggregateMetric(value.isNumber()?value.decimalValue():null,asOf,revision,
                node.path("sampleSize").asInt(),node.path("coverage").isNumber()?node.path("coverage").decimalValue():BigDecimal.ZERO,
                node.path("quality").asString("unknown"));
    }

    List<PublicationListItem> publications(UUID account,org.mranked.catalog.domain.LegacyEntityType accountType,
            int limit,UUID after,long revision,int retentionDays) {
        return jdbc.sql("""
            WITH page AS (
                SELECT publication.* FROM ingest.visible_publication publication
                WHERE primary_account_id=:account AND published_at >=
                    (SELECT committed_at-make_interval(days=>:days) FROM analytics.dataset_revision WHERE id=:revision)
                  AND EXISTS(SELECT 1 FROM catalog.legacy_entity_alias alias
                    WHERE alias.target_uuid=publication.id AND alias.entity_type=:publicationType)
                  AND published_at<=
                    (SELECT committed_at FROM analytics.dataset_revision WHERE id=:revision)
                  AND (CAST(:after AS uuid) IS NULL OR (published_at,id)<
                    (SELECT published_at,id FROM ingest.visible_publication WHERE id=CAST(:after AS uuid)))
                ORDER BY published_at DESC,id DESC LIMIT :limit
            )
            SELECT page.id,alias.legacy_id,alias.entity_type,alias.legacy_route,
                   identity.external_id,identity.public_url,page.published_at,page.publication_type,
                   page.deleted_at,page.history_completeness::text,page.is_repost,page.quality_flags,
                   (SELECT platform::text FROM catalog.visible_platform_account WHERE id=page.primary_account_id) AS platform,
                   (SELECT count(*) FROM ingest.publication_identity i WHERE i.publication_id=page.id AND i.role='joint_author') AS joint_authors,
                   history.*
            FROM page
            LEFT JOIN LATERAL (SELECT alias.* FROM catalog.legacy_entity_alias alias
                WHERE alias.target_uuid=page.id AND alias.entity_type=:publicationType LIMIT 1) alias ON true
            LEFT JOIN LATERAL (SELECT identity.external_id,identity.public_url FROM ingest.publication_identity identity
                WHERE identity.publication_id=page.id AND identity.role='primary' ORDER BY identity.id LIMIT 1) identity ON true
            LEFT JOIN LATERAL (SELECT h.* FROM analytics.publication_history h WHERE h.publication_id=page.id
                AND h.dataset_revision_id=:revision
                ORDER BY h.observed_at DESC,h.snapshot_id DESC LIMIT 1) history ON true
            ORDER BY page.published_at DESC,page.id DESC
            """).param("account",account).param("days",retentionDays).param("limit",limit).param("after",after,Types.OTHER).param("revision",revision)
                .param("publicationType",accountType==org.mranked.catalog.domain.LegacyEntityType.CHANNELS?"posts":"platform_posts")
                .query((row,index)->{
                    var presentation=PublicationPresentationMapper.map(row.getString("platform"),row.getString("external_id"),
                            row.getString("public_url"),row.getBoolean("is_repost"),row.getString("quality_flags"),row.getInt("joint_authors"));
                    return new PublicationListItem(row.getObject("id",UUID.class),row.getObject("legacy_id",Long.class),
                        row.getString("entity_type"),row.getString("legacy_route"),row.getString("external_id"),
                        instant(row,"published_at"),row.getString("public_url"),row.getString("publication_type"),
                        instant(row,"deleted_at"),row.getString("history_completeness"),counter(row,"views"),counter(row,"reactions"),
                        counter(row,"comments"),counter(row,"shares"),null,null,presentation.displayExternalId(),presentation.repost(),presentation.joint(),
                        presentation.additionalAuthorCount(),presentation.ambiguousAlbumReactions());}).list();
    }

    private static final String INSTITUTION_FILTER = """
        FROM catalog.visible_platform_account account
        JOIN catalog.visible_institution institution ON institution.id=account.institution_id
        JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
            AND institution_alias.entity_type='institutions'
        WHERE institution_alias.legacy_id=:legacy AND (:platform='all' OR account.platform::text=:platform)
        """;

    long accountCount(long legacy,Platform platform) {
        return jdbc.sql("SELECT count(*) "+INSTITUTION_FILTER).param("legacy",legacy)
                .param("platform",platform.databaseValue()).query(Long.class).single();
    }

    List<AccountView> accounts(long legacy,Platform platform,int limit,UUID after,long revision) {
        return jdbc.sql("""
            WITH page AS (
                SELECT account.*,institution.canonical_name,institution.short_name,institution_alias.legacy_id AS institution_legacy_id
            """+INSTITUTION_FILTER+"""
                AND (CAST(:after AS uuid) IS NULL OR account.id>CAST(:after AS uuid))
                ORDER BY account.id LIMIT :limit
            ), totals AS (
                SELECT p.platform_account_id,count(*) count,max(p.observed_at) observed_at
                  FROM analytics.publication_latest p JOIN page ON page.id=p.platform_account_id
                 WHERE p.dataset_revision_id=:revision GROUP BY p.platform_account_id
            )
            SELECT page.*,channel.legacy_id AS channel_id,generic.legacy_id AS generic_id,
                   coalesce(totals.count,0) AS publication_count,totals.observed_at,
                   revision.committed_at AS as_of
            FROM page LEFT JOIN catalog.legacy_entity_alias channel ON channel.target_uuid=page.id AND channel.entity_type='channels'
            LEFT JOIN catalog.legacy_entity_alias generic ON generic.target_uuid=page.id AND generic.entity_type='platform_accounts'
            LEFT JOIN totals ON totals.platform_account_id=page.id
            JOIN analytics.dataset_revision revision ON revision.id=:revision
            ORDER BY page.id
            """).param("legacy",legacy).param("platform",platform.databaseValue()).param("limit",limit)
                .param("after",after,Types.OTHER).param("revision",revision).query((row,index)->{
                    Long channel=row.getObject("channel_id",Long.class),generic=row.getObject("generic_id",Long.class);
                    boolean telegram="telegram".equals(row.getString("platform"))&&channel!=null;
                    return new AccountView(row.getObject("id",UUID.class),telegram?channel:generic==null?0:generic,
                            telegram?LegacyEntityType.CHANNELS:LegacyEntityType.PLATFORM_ACCOUNTS,channel,generic,
                            new InstitutionIdentity(row.getObject("institution_id",UUID.class),row.getLong("institution_legacy_id"),
                                    row.getString("canonical_name"),row.getString("short_name")),Platform.fromApiValue(row.getString("platform")),
                            row.getString("canonical_external_id"),row.getString("current_username"),row.getString("current_title"),
                            row.getString("current_url"),row.getString("access_mode"),row.getBoolean("enabled"),
                            row.getLong("publication_count"),instant(row,"observed_at"),revision,instant(row,"as_of"));
                }).list();
    }

    List<HistorySnapshot> history(UUID publication,int limit,Long after,long revision) {
        return jdbc.sql("""
            SELECT history.* FROM analytics.publication_history history
            WHERE publication_id=:publication
              AND dataset_revision_id=:revision
              AND (CAST(:after AS bigint) IS NULL OR (observed_at,snapshot_id)<
                  (SELECT observed_at,snapshot_id FROM analytics.publication_history
                    WHERE publication_id=:publication AND dataset_revision_id=:revision
                      AND snapshot_id=CAST(:after AS bigint)))
            ORDER BY observed_at DESC,snapshot_id DESC LIMIT :limit
            """).param("publication",publication).param("after",after,Types.BIGINT)
                .param("limit",limit).param("revision",revision).query((row,index)->new HistorySnapshot(row.getString("snapshot_id"),instant(row,"observed_at"),
                        BigDecimal.valueOf(row.getLong("age_seconds")).divide(BigDecimal.valueOf(3600),8,RoundingMode.HALF_UP),
                        counter(row,"views"),counter(row,"reactions"),counter(row,"comments"),counter(row,"shares"),
                        row.getObject("delta_views",Long.class),row.getObject("delta_reactions",Long.class),
                        row.getObject("delta_comments",Long.class),row.getObject("delta_shares",Long.class),
                        reactions(row.getString("reaction_breakdown")),row.getBoolean("synthetic"),row.getBoolean("interval_uncertain"),
                        row.getString("quality"),evidence(row.getString("lineage")),
                        row.getString("delta_reaction_breakdown")==null?null:reactions(row.getString("delta_reaction_breakdown")),
                        reactionEntries(row.getString("reaction_entries")),reactionEntries(row.getString("delta_reaction_entries"))))
                .list();
    }

    List<Long> neighbours(UUID publication,LegacyEntityType type) {
        return jdbc.sql("""
            SELECT
                (SELECT alias.legacy_id FROM ingest.visible_publication neighbour JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=neighbour.id AND alias.entity_type=:type
                 WHERE neighbour.primary_account_id=publication.primary_account_id
                   AND (neighbour.published_at,neighbour.id)<(publication.published_at,publication.id)
                 ORDER BY neighbour.published_at DESC,neighbour.id DESC LIMIT 1) AS previous,
                (SELECT alias.legacy_id FROM ingest.visible_publication neighbour JOIN catalog.legacy_entity_alias alias
                    ON alias.target_uuid=neighbour.id AND alias.entity_type=:type
                 WHERE neighbour.primary_account_id=publication.primary_account_id
                   AND (neighbour.published_at,neighbour.id)>(publication.published_at,publication.id)
                 ORDER BY neighbour.published_at,neighbour.id LIMIT 1) AS next
            FROM ingest.visible_publication publication WHERE publication.id=:publication
            """).param("publication",publication).param("type",type.databaseValue())
                .query((row,index)->java.util.Arrays.asList(row.getObject("previous",Long.class),row.getObject("next",Long.class))).single();
    }

    private static Instant instant(ResultSet row,String name)throws SQLException {
        var timestamp=row.getObject(name,OffsetDateTime.class);return timestamp==null?null:timestamp.toInstant();
    }
    private static CounterMetric counter(ResultSet row,String metric)throws SQLException {
        return new CounterMetric(row.getObject(metric+"_count",Long.class),instant(row,"observed_at"),row.getString(metric+"_quality"));
    }
    private static Map<String,Long> reactions(String json) {
        Map<String,Long> result=new LinkedHashMap<>();var tree=JSON.readTree(json);
        tree.properties().forEach(entry->result.put(entry.getKey(),entry.getValue().asLong()));return result;
    }
    private static Map<String,Object> evidence(String json) {
        return JSON.readValue(json,new tools.jackson.core.type.TypeReference<Map<String,Object>>(){});
    }
    private static List<org.mranked.query.domain.ReactionBreakdownEntry> reactionEntries(String json) {
        return json==null?null:JSON.readValue(json,
            new tools.jackson.core.type.TypeReference<List<org.mranked.query.domain.ReactionBreakdownEntry>>(){});
    }
}
