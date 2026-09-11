package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.sql.DriverManager;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.query.domain.ReactionBreakdownEntry;
import org.mranked.cache.domain.DatasetRevision;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named="MRANKED_ADMIN_TEST_POSTGRES_URL",matches=".+")
class HistoryReactionDetailsPostgresIntegrationTest {
    private static final tools.jackson.databind.json.JsonMapper JSON=new tools.jackson.databind.json.JsonMapper();
    private java.sql.Connection owner() throws Exception {
        return DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
            System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
    }

    @Test void runtimeRoleReadsExtendedProjectionButCannotReadRetainedEvidence() throws Exception {
        try(var connection=DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                "api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"))) {
            var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
            assertThat(new JdbcProjectionQueryRepository(jdbc).findPublicationHistory(UUID.randomUUID(),1,null,1)).isEmpty();
            for(String table:List.of("ingest.raw_payload")) {
                assertThatThrownBy(()->connection.createStatement().executeQuery("SELECT * FROM "+table+" LIMIT 1"))
                    .isInstanceOf(java.sql.SQLException.class).satisfies(error->assertThat(((java.sql.SQLException)error).getSQLState()).isEqualTo("42501"));
            }
            assertThat(jdbc.sql("SELECT has_table_privilege('api_read','ingest.reaction_breakdown','SELECT')").query(Boolean.class).single()).isTrue();
        }
    }

    @Test void safeParserPreservesKeyOrderLastDuplicateValueAndExactUnicode() throws Exception {
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                String parsed=parse(jdbc,"{\"👍\":1,\"❤\":2,\"👍\":3,\"❤️\":-1}",true);
                assertThat(JSON.readTree(parsed)).isEqualTo(JSON.readTree("[{\"reaction\":\"👍\",\"count\":3},{\"reaction\":\"❤\",\"count\":2},{\"reaction\":\"❤️\",\"count\":-1}]"));
                for(String invalid:List.of("{","[]","null","{\"👍\":\"password=secret\"}","{\"password=secret\":1}","{\"👍\":9223372036854775808}","{\"👍\":1.1}"))
                    assertThat(parse(jdbc,invalid,true)).as(invalid).isNull();
                assertThat(parse(jdbc,"{\"👍\":-1}",false)).isNull();
                assertThat(parse(jdbc,"{}",false)).isEqualTo("[]");
                assertThat(jdbc.sql("SELECT has_function_privilege('api_read','analytics.refresh_history_reaction_details(bigint)','EXECUTE')").query(Boolean.class).single()).isFalse();
                assertThat(jdbc.sql("SELECT has_table_privilege('api_read','ingest.raw_payload','SELECT')").query(Boolean.class).single()).isFalse();
            } finally { connection.rollback(); }
        }
    }

    @Test void canonicalReactionDeltasAndOrderDeriveFromReactionBreakdownForEveryPublication() throws Exception {
        // Final contract: reaction decoration derives from canonical
        // ingest.reaction_breakdown for every publication; retained legacy
        // evidence no longer exists.
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),publication=UUID.randomUUID(),nativePublication=UUID.randomUUID(),run=UUID.randomUUID();
                long first=7_300_000_000_000_000L+Math.floorMod(publication.getLeastSignificantBits(),90_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES(:id,'History reaction fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(:id,:institution,'telegram',:external,'public_web')")
                    .param("id",account).param("institution",institution).param("external",account.toString()).update();
                for(UUID id:List.of(publication,nativePublication))
                    jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES(:id,:account,now()-interval '5 hours',now()-interval '5 hours','post','complete')")
                        .param("id",id).param("account",account).update();
                jdbc.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(:id,'telegram','history-details','integration',now()-interval '5 hours','succeeded',:correlation)")
                    .param("id",run).param("correlation",UUID.randomUUID()).update();
                // Same breakdown shapes as the frontend v3 fixture, posts/1: a custom
                // emoji disappears while plain reactions move; deltas are derived per key.
                String[] current={"{}","{\"custom:5368324170671202286\": 8, \"\\u2764\": 4}","{\"❤\": 3, \"👍\": 7}"};
                for(int point=0;point<3;point++)
                    seed(jdbc,publication,run,first+point,point,current[point],point==0?0:point==1?12:10);
                seed(jdbc,nativePublication,run,first+10,0,"{\"❤\":2,\"👍\":3}",5);
                seed(jdbc,nativePublication,run,first+11,1,"{\"❤\":1,\"👍\":5}",6);
                seed(jdbc,nativePublication,run,first+12,2,"{\"❤️\":1,\"👍\":6}",7);
                long revision=jdbc.sql("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('migration',:id,now()) RETURNING id").param("id",UUID.randomUUID()).query(Long.class).single();
                jdbc.sql("SELECT analytics.rebuild_core_projections(:revision)").param("revision",revision).query(String.class).single();
                var repository=new JdbcProjectionQueryRepository(jdbc);
                var head=repository.findPublicationHistory(publication,1,null,revision).getFirst();
                assertThat(head.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("custom:5368324170671202286",-8L,"❤",-1L,"👍",7L));
                assertThat(head.deltaReactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("custom:5368324170671202286",-8),new ReactionBreakdownEntry("❤",-1),new ReactionBreakdownEntry("👍",7));
                assertThat(head.rawEvidence()).containsEntry("reactionDetailsSource","canonical");
                var previous=repository.findPublicationHistory(publication,1,Long.parseLong(head.snapshotId()),revision).getFirst();
                // canonical jsonb key order: shorter keys first, then bytewise
                assertThat(previous.reactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("❤",4),new ReactionBreakdownEntry("custom:5368324170671202286",8));
                var initial=repository.findPublicationHistory(publication,1,Long.parseLong(previous.snapshotId()),revision).getFirst();
                assertThat(initial.deltaReactionsBreakdown()).isNull();
                assertThat(initial.deltaReactionsBreakdownEntries()).isNull();
                var nativeHead=repository.findPublicationHistory(nativePublication,1,null,revision).getFirst();
                assertThat(nativeHead.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("❤",-1L,"❤️",1L,"👍",1L));
                var nativePrior=repository.findPublicationHistory(nativePublication,1,Long.parseLong(nativeHead.snapshotId()),revision).getFirst();
                assertThat(nativePrior.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("❤",-1L,"👍",2L));
                assertThat(repository.findPublicationHistory(nativePublication,1,Long.parseLong(nativePrior.snapshotId()),revision).getFirst().deltaReactionsBreakdown()).isNull();
                // Refreshing again is idempotent and never exposes internal lineage fields.
                jdbc.sql("SELECT analytics.refresh_history_reaction_details(:revision)").param("revision",revision).query(Long.class).single();
                var refreshed=repository.findPublicationHistory(publication,1,null,revision).getFirst();
                assertThat(refreshed.deltaReactionsBreakdown()).isEqualTo(head.deltaReactionsBreakdown());
                assertThat(JSON.writeValueAsString(refreshed)).doesNotContain("password=secret","delta_by_reaction_json","source_namespace");
            } finally { connection.rollback(); }
        }
    }

    @Test void sourceBackedHistoryDerivesTheSameOrderedReactionsAndDeltasWithoutTheProjection() throws Exception {
        // The bounded source-read API answers from ingest partitions instead of
        // analytics.publication_history, and must decorate reactions identically.
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),publication=UUID.randomUUID(),run=UUID.randomUUID();
                long first=7_300_000_000_000_000L+Math.floorMod(publication.getLeastSignificantBits(),90_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES(:id,'Source reaction fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(:id,:institution,'telegram',:external,'public_web')")
                    .param("id",account).param("institution",institution).param("external",account.toString()).update();
                jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES(:id,:account,now()-interval '5 hours',now()-interval '5 hours','post','complete')")
                    .param("id",publication).param("account",account).update();
                jdbc.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(:id,'telegram','source-details','integration',now()-interval '5 hours','succeeded',:correlation)")
                    .param("id",run).param("correlation",UUID.randomUUID()).update();
                String[] current={"{}","{\"custom:5368324170671202286\": 8, \"\\u2764\": 4}","{\"❤\": 3, \"👍\": 7}"};
                for(int point=0;point<3;point++)
                    seed(jdbc,publication,run,first+point,point,current[point],point==0?0:point==1?12:10);
                long sourceRevision=System.currentTimeMillis();
                assertThat(sourceRevision).isGreaterThanOrEqualTo(DatasetRevision.SOURCE_ID_FLOOR);
                var repository=new JdbcProjectionQueryRepository(jdbc);
                var head=repository.findPublicationHistory(publication,1,null,sourceRevision).getFirst();
                assertThat(head.reactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("❤",3),new ReactionBreakdownEntry("👍",7));
                assertThat(head.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("custom:5368324170671202286",-8L,"❤",-1L,"👍",7L));
                assertThat(head.deltaReactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("custom:5368324170671202286",-8),new ReactionBreakdownEntry("❤",-1),new ReactionBreakdownEntry("👍",7));
                assertThat(head.rawEvidence()).containsEntry("reactionDetailsSource","canonical");
                var previous=repository.findPublicationHistory(publication,1,Long.parseLong(head.snapshotId()),sourceRevision).getFirst();
                assertThat(previous.reactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("❤",4),new ReactionBreakdownEntry("custom:5368324170671202286",8));
                var initial=repository.findPublicationHistory(publication,1,Long.parseLong(previous.snapshotId()),sourceRevision).getFirst();
                assertThat(initial.deltaReactionsBreakdown()).isNull();
                assertThat(initial.deltaReactionsBreakdownEntries()).isNull();
                assertThat(jdbc.sql("SELECT count(*) FROM analytics.publication_history").query(Long.class).single()).isZero();
            } finally { connection.rollback(); }
        }
    }

    private static String parse(JdbcClient jdbc,String raw,boolean signed) {
        return jdbc.sql("SELECT analytics.ordered_history_reactions(:raw,:signed)::text").param("raw",raw).param("signed",signed).query(String.class).optional().orElse(null);
    }
    private static void seed(JdbcClient jdbc,UUID publication,UUID run,long id,int bucket,String raw,long total) {
        jdbc.sql("""
            INSERT INTO ingest.publication_metric_snapshot(published_month,id,publication_id,collection_run_id,observed_at,
                age_seconds,sampling_bucket,views_count,reactions_count,quality,views_quality,reactions_quality,source_fingerprint,collected_at)
            SELECT date_trunc('month',published_at AT TIME ZONE 'UTC')::date,:id,:publication,:run,published_at+make_interval(hours=>:bucket+1),
                (:bucket+1)*3600,:bucket,0,:total,'exact','exact','exact',:fingerprint,now()
            FROM ingest.publication WHERE id=:publication
            """).param("publication",publication).param("run",run).param("id",id).param("bucket",bucket).param("total",total).param("fingerprint",publication+":"+bucket).update();
        jdbc.sql("INSERT INTO ingest.reaction_breakdown(snapshot_published_month,snapshot_id,reaction_key,reaction_count) SELECT s.published_month,s.id,r.key,(r.value::text)::bigint FROM ingest.publication_metric_snapshot s CROSS JOIN jsonb_each(CAST(:raw AS jsonb)) r WHERE s.id=:id")
            .param("raw",raw).param("id",id).update();
    }
}
