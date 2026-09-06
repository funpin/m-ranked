package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.sql.DriverManager;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.query.domain.ReactionBreakdownEntry;
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
            for(String table:List.of("migration.legacy_evidence","migration.legacy_export_lexeme")) {
                assertThatThrownBy(()->connection.createStatement().executeQuery("SELECT * FROM "+table+" LIMIT 1"))
                    .isInstanceOf(java.sql.SQLException.class).satisfies(error->assertThat(((java.sql.SQLException)error).getSQLState()).isEqualTo("42501"));
            }
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
                assertThat(jdbc.sql("SELECT has_table_privilege('api_read','migration.legacy_evidence','SELECT')").query(Boolean.class).single()).isFalse();
            } finally { connection.rollback(); }
        }
    }

    @Test void retainedTelegramDeltaAndOrderMatchRealFixtureWhileNativePagesUseWholeHistory() throws Exception {
        try(var connection=owner()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),publication=UUID.randomUUID(),nativePublication=UUID.randomUUID(),run=UUID.randomUUID(),batch=UUID.randomUUID(),namespace=UUID.randomUUID();
                long first=7_300_000_000_000_000L+Math.floorMod(publication.getLeastSignificantBits(),90_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES(:id,'History reaction fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(:id,:institution,'telegram',:external,'public_web')")
                    .param("id",account).param("institution",institution).param("external",account.toString()).update();
                for(UUID id:List.of(publication,nativePublication))
                    jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES(:id,:account,now()-interval '5 hours',now()-interval '5 hours','post','complete')")
                        .param("id",id).param("account",account).update();
                jdbc.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(:id,'telegram','history-details','integration',now()-interval '5 hours','succeeded',:correlation)")
                    .param("id",run).param("correlation",UUID.randomUUID()).update();
                jdbc.sql("INSERT INTO migration.import_batch(id,source_name,source_file_name,source_size_bytes,source_sha256,source_schema_version,snapshot_kind,tool_version,status) VALUES(:id,:name,'history.db',0,repeat('a',64),1,'fixture','integration','succeeded')")
                    .param("id",batch).param("name",batch.toString()).update();
                // Exact lexemes from frontend v3 fixture, posts/1 (SHA 22ec8c52...):
                // source custom emoji and plain thumbs differ; stored deltas are authoritative legacy presentation.
                String[] current={"{}","{\"custom:5368324170671202286\": 8, \"\\u2764\": 4}","{\"❤\": 3, \"👍\": 7}"};
                String[] delta={null,"{\"❤\": 4, \"👍\": 8}","{\"❤\": -1, \"👍\": -1}"};
                for(int point=0;point<3;point++) {
                    seed(jdbc,publication,run,first+point,point,current[point],point==0?0:point==1?12:10);
                    retained(jdbc,namespace,batch,publication,first+point,point,current[point],delta[point]);
                }
                seed(jdbc,nativePublication,run,first+10,0,"{\"❤\":2,\"👍\":3}",5);
                seed(jdbc,nativePublication,run,first+11,1,"{\"❤\":1,\"👍\":5}",6);
                seed(jdbc,nativePublication,run,first+12,2,"{\"❤️\":1,\"👍\":6}",7);
                long revision=jdbc.sql("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('migration',:id,now()) RETURNING id").param("id",UUID.randomUUID()).query(Long.class).single();
                jdbc.sql("SELECT analytics.rebuild_core_projections(:revision)").param("revision",revision).query(String.class).single();
                var repository=new JdbcProjectionQueryRepository(jdbc);
                var head=repository.findPublicationHistory(publication,1,null,revision).getFirst();
                assertThat(head.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("❤",-1L,"👍",-1L));
                assertThat(head.deltaReactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("❤",-1),new ReactionBreakdownEntry("👍",-1));
                assertThat(head.rawEvidence()).containsEntry("reactionDetailsSource","legacy");
                var previous=repository.findPublicationHistory(publication,1,Long.parseLong(head.snapshotId()),revision).getFirst();
                assertThat(previous.reactionsBreakdownEntries()).containsExactly(new ReactionBreakdownEntry("custom:5368324170671202286",8),new ReactionBreakdownEntry("❤",4));
                var initial=repository.findPublicationHistory(publication,1,Long.parseLong(previous.snapshotId()),revision).getFirst();
                assertThat(initial.deltaReactionsBreakdown()).isEmpty();
                assertThat(initial.deltaReactionsBreakdownEntries()).isEmpty();
                var nativeHead=repository.findPublicationHistory(nativePublication,1,null,revision).getFirst();
                assertThat(nativeHead.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("❤",-1L,"❤️",1L,"👍",1L));
                var nativePrior=repository.findPublicationHistory(nativePublication,1,Long.parseLong(nativeHead.snapshotId()),revision).getFirst();
                assertThat(nativePrior.deltaReactionsBreakdown()).containsExactlyInAnyOrderEntriesOf(Map.of("❤",-1L,"👍",2L));
                assertThat(repository.findPublicationHistory(nativePublication,1,Long.parseLong(nativePrior.snapshotId()),revision).getFirst().deltaReactionsBreakdown()).isNull();
                // A different row hash can never substitute its retained delta.
                jdbc.sql("UPDATE migration.legacy_identity_map SET source_row_hash=repeat('f',64) WHERE source_namespace=:namespace AND source_pk='3'").param("namespace",namespace).update();
                jdbc.sql("SELECT analytics.refresh_history_reaction_details(:revision)").param("revision",revision).query(Long.class).single();
                var unavailable=repository.findPublicationHistory(publication,1,null,revision).getFirst();
                assertThat(unavailable.deltaReactionsBreakdown()).isNull();
                assertThat(unavailable.rawEvidence()).containsEntry("reactionDetailsSource","legacy_unavailable");
                assertThat(JSON.writeValueAsString(unavailable)).doesNotContain("password=secret","delta_by_reaction_json","source_namespace");
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
    private static void retained(JdbcClient jdbc,UUID namespace,UUID batch,UUID publication,long snapshot,int point,String raw,String delta) {
        String pk=Integer.toString(point+1),hash=Integer.toString(point+1).repeat(64);
        jdbc.sql("""
            INSERT INTO migration.legacy_identity_map(source_namespace,source_table,source_pk,target_type,target_bigint,natural_key,source_row_hash,first_batch_id,last_seen_batch_id)
            SELECT :namespace,'reaction_snapshots',:pk,'publication_metric_snapshot',:snapshot,
                jsonb_build_object('publication_id',publication_id::text,'published_month',published_month::text,'sampling_bucket',sampling_bucket),:hash,:batch,:batch
            FROM ingest.publication_metric_snapshot WHERE id=:snapshot AND publication_id=:publication
            """).param("namespace",namespace).param("pk",pk).param("snapshot",snapshot).param("hash",hash).param("batch",batch).param("publication",publication).update();
        jdbc.sql("INSERT INTO migration.legacy_export_lexeme(source_namespace,source_table,source_pk,source_row_hash,fields) VALUES(:namespace,'reaction_snapshots',:pk,:hash,CAST(:body AS jsonb))")
            .param("namespace",namespace).param("pk",pk).param("hash",hash).param("body",JSON.writeValueAsString(Map.of("reactions_json",raw))).update();
        var body=new java.util.LinkedHashMap<String,Object>();body.put("delta_by_reaction_json",delta);
        jdbc.sql("INSERT INTO migration.legacy_evidence(batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence) VALUES(:batch,'reaction_snapshots',:pk,:hash,'legacy_derived_metrics',CAST(:body AS jsonb))")
            .param("batch",batch).param("pk",pk).param("hash",hash).param("body",JSON.writeValueAsString(body)).update();
    }
}
