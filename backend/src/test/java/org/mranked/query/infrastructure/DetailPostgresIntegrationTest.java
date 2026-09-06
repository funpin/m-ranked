package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Types;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.domain.DatasetRevision;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.application.CursorCodec;
import org.mranked.query.application.PublicQueryService;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named="MRANKED_ADMIN_TEST_POSTGRES_URL",matches=".+")
class DetailPostgresIntegrationTest {
    @Test void publicDetailQueriesUseOnlyGrantedIdentityColumns() throws Exception {
        try(var connection=DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                "api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"))) {
            var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
            var repository=new JdbcProjectionQueryRepository(jdbc);
            assertThat(repository.findAccountPublications(UUID.randomUUID(),LegacyEntityType.CHANNELS,2,null,1)).isEmpty();
            assertThat(repository.findPublication(Long.MAX_VALUE,LegacyEntityType.POSTS,1)).isEmpty();
        }
    }
    @Test void sameObservationHistoryCorrectionsRetentionStatsAndBoundedNavigation() throws Exception {
        try(Connection connection=DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"))) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),secondAccount=UUID.randomUUID(),run=UUID.randomUUID();
                UUID older=UUID.randomUUID(),publication=UUID.randomUUID(),newer=UUID.randomUUID(),retainedOut=UUID.randomUUID();
                long seed=9_800_000_000L+Math.floorMod(institution.getLeastSignificantBits(),90_000_000L);
                long snapshot=9_100_000_000_000_000L+Math.floorMod(account.getLeastSignificantBits(),90_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,'Detail fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('institutions',:id,:uuid)").param("id",seed).param("uuid",institution).update();
                for(UUID id:java.util.List.of(account,secondAccount)) {
                    jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,current_username,current_title,access_mode,enabled) VALUES (:id,:institution,'telegram',:external,'detail_channel','Detail channel','public_web',true)")
                            .param("id",id).param("institution",institution).param("external",id.toString()).update();
                }
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('channels',:first,:account),('channels',:second,:secondAccount)")
                        .param("first",seed+1).param("second",seed+2).param("account",account).param("secondAccount",secondAccount).update();
                UUID[] publications={older,publication,newer,retainedOut};int[] hours={6,5,4,24*80};
                for(int index=0;index<publications.length;index++) {
                    jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES (:id,:account,now()-make_interval(hours=>:hours),now(),'post','complete')")
                            .param("id",publications[index]).param("account",account).param("hours",hours[index]).update();
                    jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route) VALUES ('posts',:legacy,:id,:route)")
                            .param("legacy",seed+10+index).param("id",publications[index]).param("route","/posts/"+(seed+10+index)).update();
                    jdbc.sql("INSERT INTO ingest.publication_identity(publication_id,platform_account_id,external_id,role,public_url) VALUES (:publication,:account,:external,'primary',:url)")
                            .param("publication",publications[index]).param("account",account).param("external",Integer.toString(index))
                            .param("url","https://t.me/detail_channel/"+index).update();
                }
                jdbc.sql("UPDATE ingest.publication SET is_repost=true,quality_flags='{\"ambiguous_album_reactions\":true}' WHERE id=:id").param("id",publication).update();
                jdbc.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES (:id,'telegram','detail','integration',now(),'succeeded',:correlation)")
                        .param("id",run).param("correlation",UUID.randomUUID()).update();
                for(int bucket=0;bucket<3;bucket++) {
                    insertSnapshot(jdbc,publication,run,snapshot+bucket,bucket,bucket*10L,bucket==2?null:bucket*2L,"original-"+bucket);
                }
                insertSnapshot(jdbc,publication,run,snapshot+3,1,12L,2L,"corrected-1");
                jdbc.sql("INSERT INTO ingest.reaction_breakdown(snapshot_published_month,snapshot_id,reaction_key,reaction_count) SELECT published_month,id,'👍',2 FROM ingest.publication_metric_snapshot WHERE id=:id")
                        .param("id",snapshot+3).update();
                long revision=jdbc.sql("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES ('migration',:correlation,now()+interval '5 seconds') RETURNING id")
                        .param("correlation",UUID.randomUUID()).query(Long.class).single();
                jdbc.sql("SELECT analytics.rebuild_core_projections(:revision)").param("revision",revision).query(String.class).single();
                var pinned=new DatasetRevision(revision,jdbc.sql("SELECT committed_at FROM analytics.dataset_revision WHERE id=:id").param("id",revision).query(java.time.OffsetDateTime.class).single().toInstant());
                var repository=new JdbcProjectionQueryRepository(jdbc);
                var service=new PublicQueryService(repository,()->pinned,new CursorCodec());
                var first=service.publicationHistoryAtRevision(seed+11,LegacyEntityType.POSTS,2,null,pinned);
                assertThat(first.items()).hasSize(2);
                assertThat(first.items().getFirst().snapshotId()).isEqualTo(Long.toString(snapshot+2));
                assertThat(first.items().getFirst().views().value()).isEqualTo(20);
                assertThat(first.items().getFirst().reactions().value()).isNull();
                assertThat(first.items().getFirst().deltaViews()).isEqualTo(8);
                assertThat(first.items().getFirst().deltaReactions()).isNull();
                assertThat(first.items().get(1).snapshotId()).isEqualTo(Long.toString(snapshot+3));
                assertThat(first.items().get(1).views().value()).isEqualTo(12);
                assertThat(first.items().get(1).reactionsBreakdown()).containsEntry("👍",2L);
                assertThat(first.items().get(1).rawEvidence()).containsEntry("supersedesSnapshotId",Long.toString(snapshot+1));
                assertThat(first.items().get(1).reactions().quality()).isEqualTo("rounded");
                assertThat(first.previousLegacyId()).isEqualTo(seed+10);
                assertThat(first.nextLegacyId()).isEqualTo(seed+12);
                assertThat(first.publication().accountLegacyId()).isEqualTo(seed+1);
                assertThat(first.publication().publicUrl()).isEqualTo("https://t.me/detail_channel/1");
                assertThat(first.publication().presentation().displayExternalId()).isEqualTo("1");
                assertThat(first.publication().presentation().repost()).isTrue();
                assertThat(first.publication().presentation().ambiguousAlbumReactions()).isTrue();
                var tail=service.publicationHistoryAtRevision(seed+11,LegacyEntityType.POSTS,2,first.nextCursor(),pinned);
                assertThat(tail.items()).singleElement().satisfies(row->{
                    assertThat(row.views().value()).isZero();assertThat(row.reactions().value()).isZero();
                    assertThat(row.deltaViews()).isNull();
                });
                assertThat(tail.nextCursor()).isNull();
                assertThatThrownBy(()->service.publicationHistoryAtRevision(seed+12,LegacyEntityType.POSTS,2,first.nextCursor(),pinned))
                        .isInstanceOf(org.mranked.query.application.InvalidCursorException.class);
                var page=service.accountPublicationsAtRevision(seed+1,LegacyEntityType.CHANNELS,2,null,pinned);
                assertThat(page.items()).extracting(org.mranked.query.domain.PublicationListItem::legacyId).containsExactly(seed+12,seed+11);
                assertThat(page.items().get(1).reactions().value()).isNull();
                var rest=service.accountPublicationsAtRevision(seed+1,LegacyEntityType.CHANNELS,2,page.nextCursor(),pinned);
                assertThat(rest.items()).singleElement().satisfies(row->assertThat(row.legacyId()).isEqualTo(seed+10));
                assertThat(rest.nextCursor()).isNull();
                // One canonical Telegram account may have both legacy namespaces.
                // Generic institution pages must not inject its posts-only records.
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES('platform_accounts',:legacy,:id)")
                        .param("legacy",seed+1).param("id",account).update();
                assertThat(service.accountPublicationsAtRevision(seed+1,LegacyEntityType.PLATFORM_ACCOUNTS,1,null,pinned).items()).isEmpty();
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route) VALUES('platform_posts',:older,:old,:oldRoute),('platform_posts',:newer,:new,:newRoute)")
                        .param("older",seed+30).param("old",older).param("oldRoute","/platform-posts/"+(seed+30))
                        .param("newer",seed+32).param("new",newer).param("newRoute","/platform-posts/"+(seed+32)).update();
                var generic=service.accountPublicationsAtRevision(seed+1,LegacyEntityType.PLATFORM_ACCOUNTS,1,null,pinned);
                assertThat(generic.items()).singleElement().satisfies(row->{
                    assertThat(row.legacyId()).isEqualTo(seed+32);assertThat(row.legacyType()).isEqualTo("platform_posts");
                });
                var genericTail=service.accountPublicationsAtRevision(seed+1,LegacyEntityType.PLATFORM_ACCOUNTS,1,generic.nextCursor(),pinned);
                assertThat(genericTail.items()).singleElement().satisfies(row->assertThat(row.legacyId()).isEqualTo(seed+30));
                assertThat(genericTail.nextCursor()).isNull();
                assertThatThrownBy(()->service.accountPublicationsAtRevision(seed+1,LegacyEntityType.CHANNELS,1,generic.nextCursor(),pinned))
                        .isInstanceOf(org.mranked.query.application.InvalidCursorException.class);
                var stats=service.accountAtRevision(seed+1,LegacyEntityType.CHANNELS,pinned).stats();
                assertThat(stats.retentionDays()).isEqualTo(70);assertThat(stats.postCount()).isEqualTo(3);assertThat(stats.monitored()).isEqualTo(3);
                assertThat(stats.medianViews().value()).isEqualByComparingTo("20");assertThat(stats.medianViews().sampleSize()).isEqualTo(1);
                assertThat(stats.medianViews().coverage()).isBetween(new java.math.BigDecimal("0.333"),new java.math.BigDecimal("0.334"));
                assertThat(stats.medianReactions().value()).isNull();assertThat(stats.medianReactions().sampleSize()).isZero();
                var accounts=service.institutionAccountsAtRevision(seed,Platform.TELEGRAM,1,null,pinned);
                assertThat(accounts.items()).hasSize(1);assertThat(accounts.legacyTotalAccountCount()).isEqualTo(2);assertThat(accounts.nextCursor()).isNotNull();
                var moreAccounts=service.institutionAccountsAtRevision(seed,Platform.TELEGRAM,1,accounts.nextCursor(),pinned);
                assertThat(moreAccounts.items()).hasSize(1);assertThat(moreAccounts.nextCursor()).isNull();
                assertThat(moreAccounts.items().getFirst().id()).isNotEqualTo(accounts.items().getFirst().id());
                assertThat(service.institutionAccountsAtRevision(seed,Platform.VK,1,null,pinned).items()).isEmpty();
            } finally {connection.rollback();}
        }
    }
    @Test void archivedTextProjectionUsesCurrentRowHashAndOnlyPublicStringFields() throws Exception {
        try(var connection=DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"))) {
            connection.setAutoCommit(false);
            try {
                var jdbc=JdbcClient.create(new SingleConnectionDataSource(connection,true));
                UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),publication=UUID.randomUUID(),batch=UUID.randomUUID();
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES(:id,'Content fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(:id,:institution,'vk',:external,'public_web')")
                        .param("id",account).param("institution",institution).param("external",account.toString()).update();
                jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES(:id,:account,now()-interval '1 day',now(),'post','complete')")
                        .param("id",publication).param("account",account).update();
                jdbc.sql("INSERT INTO migration.import_batch(id,source_name,source_file_name,source_size_bytes,source_sha256,source_schema_version,snapshot_kind,tool_version,status) VALUES(:id,:name,'fixture.db',0,repeat('a',64),1,'fixture','integration','succeeded')")
                        .param("id",batch).param("name",batch.toString()).update();
                jdbc.sql("INSERT INTO migration.legacy_identity_map(source_namespace,source_table,source_pk,target_type,target_uuid,natural_key,source_row_hash,first_batch_id,last_seen_batch_id) VALUES(:namespace,'platform_posts','1','publication',:id,'{}',repeat('a',64),:batch,:batch)")
                        .param("namespace",UUID.randomUUID()).param("id",publication).param("batch",batch).update();
                var json=new tools.jackson.databind.json.JsonMapper();
                for(String hash:java.util.List.of("a","b")) {
                    String body=json.writeValueAsString(java.util.Map.of("present",true,"payload",java.util.Map.of(
                            "text",hash.equals("a")?" \nPublic archived text\n ":"Stale text", "message","Wrong priority", "token","must-not-be-public")));
                    jdbc.sql("INSERT INTO migration.legacy_evidence(batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence) VALUES(:batch,'platform_posts','1',repeat(:hash,64),'raw_json',CAST(:body AS jsonb))")
                            .param("batch",batch).param("hash",hash).param("body",body).update();
                }
                long revision=jdbc.sql("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('migration',:id,now()) RETURNING id")
                        .param("id",UUID.randomUUID()).query(Long.class).single();
                jdbc.sql("SELECT analytics.refresh_publication_content(:id)").param("id",revision).query(Long.class).single();
                assertThat(new JdbcProjectionQueryRepository(jdbc).findPublicationArchivedText(publication,revision)).isEqualTo("Public archived text");
                assertThat(jdbc.sql("SELECT to_jsonb(content)::text FROM analytics.publication_content content WHERE publication_id=:id").param("id",publication).query(String.class).single())
                        .doesNotContain("token","must-not-be-public","Stale text","Wrong priority");
                assertThat(jdbc.sql("SELECT has_table_privilege('api_read','analytics.publication_content','SELECT')").query(Boolean.class).single()).isTrue();
                assertThat(jdbc.sql("SELECT has_table_privilege('api_read','migration.legacy_evidence','SELECT')").query(Boolean.class).single()).isFalse();
            } finally {connection.rollback();}
        }
    }

    private static void insertSnapshot(JdbcClient jdbc,UUID publication,UUID run,long id,int bucket,Long views,Long reactions,String fingerprint) {
        jdbc.sql("""
            INSERT INTO ingest.publication_metric_snapshot(published_month,id,publication_id,collection_run_id,observed_at,
                age_seconds,sampling_bucket,views_count,reactions_count,quality,views_quality,reactions_quality,source_fingerprint,collected_at)
            SELECT date_trunc('month',published_at AT TIME ZONE 'UTC')::date,:id,:publication,:run,
                published_at+make_interval(hours=>:bucket+1),(:bucket+1)*3600,:bucket,:views,:reactions,'exact','exact','rounded',:fingerprint,now()
            FROM ingest.publication WHERE id=:publication
            """).param("publication",publication).param("run",run).param("id",id).param("bucket",bucket).param("views",views,Types.BIGINT)
                .param("reactions",reactions,Types.BIGINT).param("fingerprint",fingerprint).update();
    }
}
