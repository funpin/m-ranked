package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.HashSet;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.cache.application.PublicCacheKeyFactory;
import org.mranked.cache.application.PublicDtoCache;
import org.mranked.cache.infrastructure.DisabledPublicCacheStore;
import org.mranked.cache.infrastructure.JdbcDatasetRevisionProvider;
import org.mranked.catalog.domain.LegacyEntityType;
import org.mranked.query.application.CursorCodec;
import org.mranked.query.application.PublicQueryService;
import org.mranked.query.domain.ActivityRatingQuery;
import org.mranked.query.domain.OverviewQuery;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import tools.jackson.databind.json.JsonMapper;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class BackendConsistencyPostgresIntegrationTest {
    private static Connection connection() throws SQLException {
        return DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"), System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
    }
    private static Connection roleConnection(String role) throws SQLException {
        return DriverManager.getConnection(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"), role,
                System.getenv(role.equals("api_read") ? "MRANKED_QUERY_TEST_PASSWORD" : "MRANKED_ADMIN_TEST_PASSWORD"));
    }
    private static JdbcClient jdbc(Connection connection) { return JdbcClient.create(new SingleConnectionDataSource(connection, true)); }
    private static long revision(JdbcClient jdbc) {
        return jdbc.sql("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES ('migration',:correlation,now()+interval '5 seconds') RETURNING id")
                .param("correlation", UUID.randomUUID()).query(Long.class).single();
    }
    private static void rebuild(JdbcClient jdbc, long revision) {
        jdbc.sql("SELECT analytics.rebuild_core_projections(:revision)").param("revision",revision).query(String.class).single();
    }

    @Test
    void formulaComponentsCheckBothParentsAndAuditIsImmutableAsAdmin() throws Exception {
        try (var connection=roleConnection("api_write_admin")) {
            connection.setAutoCommit(false);
            try {
                var jdbc=jdbc(connection);
                UUID draft=UUID.randomUUID(), published=UUID.randomUUID(), retired=UUID.randomUUID(), component=UUID.randomUUID();
                for (UUID id: java.util.List.of(draft,published,retired)) {
                    jdbc.sql("INSERT INTO rating.formula_definition(id,formula_key,version,effective_from,definition,source_hash) VALUES (:id,:key,1,now(),'{}',repeat('a',64))")
                            .param("id",id).param("key","review-"+id).update();
                }
                jdbc.sql("INSERT INTO rating.formula_component(id,formula_definition_id,component_code,numerator_metric,weight,normalization,missing_policy,minimum_quality) VALUES (:id,:parent,'c','views',1,'none','omit','exact')")
                        .param("id",component).param("parent",draft).update();
                jdbc.sql("UPDATE rating.formula_definition SET status='published',published_at=now() WHERE id IN (:ids)")
                        .param("ids",java.util.List.of(published,retired)).update();
                jdbc.sql("UPDATE rating.formula_definition SET status='retired' WHERE id=:id").param("id",retired).update();
                for (UUID parent:java.util.List.of(published,retired)) {
                    blocked(connection,"UPDATE rating.formula_component SET formula_definition_id='"+parent+"' WHERE id='"+component+"'","55000");
                    blocked(connection,"INSERT INTO rating.formula_component(formula_definition_id,component_code,numerator_metric,weight,normalization,missing_policy,minimum_quality) VALUES ('"+parent+"','new','views',1,'none','omit','exact')","55000");
                }
                assertThat(jdbc.sql("UPDATE rating.formula_component SET weight=2 WHERE id=:id").param("id",component).update()).isEqualTo(1);
                jdbc.sql("UPDATE rating.formula_definition SET status='published',published_at=now() WHERE id=:id").param("id",draft).update();
                blocked(connection,"UPDATE rating.formula_component SET weight=3 WHERE id='"+component+"'","55000");
                blocked(connection,"DELETE FROM rating.formula_component WHERE id='"+component+"'","42501");
                jdbc.sql("INSERT INTO ops_and_admin.audit_log(subject,action,target_type,correlation_id,outcome) VALUES ('integration','test','fixture',:id,'succeeded')")
                        .param("id",UUID.randomUUID()).update();
                blocked(connection,"UPDATE ops_and_admin.audit_log SET outcome='changed'","42501");
                blocked(connection,"DELETE FROM ops_and_admin.audit_log","42501");
            } finally {connection.rollback();}
        }
    }

    @Test
    void auditRejectsOwnerUpdateDeleteAndTruncate() throws Exception {
        try (var owner=connection()) {
            owner.setAutoCommit(false);
            try {
                jdbc(owner).sql("INSERT INTO ops_and_admin.audit_log(subject,action,target_type,correlation_id,outcome) VALUES ('owner-integration','test','fixture',:id,'succeeded')").param("id",UUID.randomUUID()).update();
                blocked(owner,"UPDATE ops_and_admin.audit_log SET outcome='changed'","55000");
                blocked(owner,"DELETE FROM ops_and_admin.audit_log","55000");
                blocked(owner,"TRUNCATE ops_and_admin.audit_log","55000");
            } finally {owner.rollback();}
        }
    }

    @Test
    void aggregateMetadataDoesNotBorrowSampleSizeFromAnotherMetric() throws Exception {
        try (var connection=connection()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=jdbc(connection);UUID id=UUID.randomUUID();long legacy=9_500_000_000L+Math.floorMod(id.getLeastSignificantBits(),100_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,'Metadata fixture')").param("id",id).update();
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('institutions',:legacy,:id)").param("legacy",legacy).param("id",id).update();
                long revision=revision(jdbc);
                jdbc.sql("""
                    INSERT INTO analytics.institution_period_metrics(institution_id,platform,period_key,metric_key,aggregation,
                        window_start,window_end,value,sample_size,coverage,quality,as_of,dataset_revision_id)
                    SELECT :id,'vk','1d',metric::analytics.metric_key,aggregation::analytics.aggregation_code,
                        now()-interval '1 day',now(),value,sample,coverage,quality::ingest.observation_quality,now(),:revision
                    FROM (VALUES ('views','sum',100,10,1.0,'exact'),('views','median',10,10,1.0,'exact'),
                        ('reactions','sum',0,1,0.1,'rounded'),('reactions','median',0,1,0.1,'rounded'))
                        candidates(metric,aggregation,value,sample,coverage,quality)
                    """).param("id",id).param("revision",revision).update();
                var view=new JdbcProjectionQueryRepository(jdbc).findInstitution(legacy,Platform.VK,PeriodKey.ONE_DAY,revision).orElseThrow();
                var json=new JsonMapper().valueToTree(org.mranked.query.web.PublicApiModels.institution(view));
                assertThat(json.at("/metrics/aggregates/totalViews/sampleSize").asInt()).isEqualTo(10);
                assertThat(json.at("/metrics/aggregates/medianViews/coverage").decimalValue()).isEqualByComparingTo("1");
                assertThat(json.at("/metrics/aggregates/totalReactions/sampleSize").asInt()).isEqualTo(1);
                assertThat(json.at("/metrics/aggregates/medianReactions/coverage").decimalValue()).isEqualByComparingTo("0.1");
                assertThat(json.at("/metrics/aggregates/totalReactions/value").decimalValue()).isEqualByComparingTo("0");
                assertThat(json.at("/metrics/aggregates/totalReactions/quality").asText()).isEqualTo("rounded");
                assertThat(json.at("/metrics/aggregates/totalViews/datasetRevision").asLong()).isEqualTo(revision);
            } finally {connection.rollback();}
        }
    }

    @Test
    void rebuiltOverviewKeepsTenViewsCandidatesAndOneRoundedReactionCandidate() throws Exception {
        try (var connection=connection()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=jdbc(connection); UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),run=UUID.randomUUID();
                long legacy=9_700_000_000L+Math.floorMod(institution.getLeastSignificantBits(),100_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,:name)").param("id",institution).param("name","Sparse overview "+legacy).update();
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('institutions',:legacy,:id)").param("legacy",legacy).param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode,enabled) VALUES (:id,:institution,'vk',:external,'public_web',true)").param("id",account).param("institution",institution).param("external",account.toString()).update();
                jdbc.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES (:id,'vk','sparse','integration',now()-interval '10 minutes','succeeded',:correlation)").param("id",run).param("correlation",UUID.randomUUID()).update();
                jdbc.sql("""
                    WITH publications AS (
                        INSERT INTO ingest.publication(primary_account_id,published_at,discovered_at,publication_type,
                            history_completeness,synthetic_baseline_allowed)
                        SELECT :account,now()-interval '10 minutes',now()-interval '10 minutes','post','complete',true
                            FROM generate_series(1,10) RETURNING id,published_at
                    ), numbered AS (SELECT *,row_number() OVER(ORDER BY id) n FROM publications)
                    INSERT INTO ingest.publication_metric_snapshot(published_month,publication_id,collection_run_id,
                        observed_at,age_seconds,sampling_bucket,views_count,reactions_count,shares_count,
                        quality,views_quality,reactions_quality,shares_quality,source_fingerprint,collected_at)
                    SELECT date_trunc('month',published_at AT TIME ZONE 'UTC')::date,id,:run,
                        now()-interval '5 minutes',300,0,10,CASE WHEN n=1 THEN 0 END,99,
                        'invalid','exact','rounded','invalid',id::text,now()
                    FROM numbered
                    """).param("account",account).param("run",run).update();
                long revision=revision(jdbc);rebuild(jdbc,revision);
                var cards=new JdbcProjectionQueryRepository(jdbc).findOverview(OverviewQuery.normalized(
                        Platform.VK,PeriodKey.ONE_DAY,"Sparse overview "+legacy,"name","asc"),5,null,revision);
                assertThat(cards).singleElement().satisfies(card->{
                    assertThat(card.views().total()).isEqualByComparingTo("100");
                    assertThat(card.views().totalMetadata().sampleSize()).isEqualTo(10);
                    assertThat(card.views().totalMetadata().coverage()).isEqualByComparingTo("1");
                    assertThat(card.views().medianMetadata().quality()).isEqualTo("exact");
                    assertThat(card.reactions().total()).isEqualByComparingTo("0");
                    assertThat(card.reactions().totalMetadata().sampleSize()).isEqualTo(1);
                    assertThat(card.reactions().medianMetadata().coverage()).isEqualByComparingTo("0.1");
                    assertThat(card.reactions().totalMetadata().quality()).isEqualTo("rounded");
                    assertThat(card.shares().total()).isNull();
                    assertThat(card.shares().totalMetadata().sampleSize()).isZero();
                    assertThat(card.reactions().totalMetadata().datasetRevision()).isEqualTo(revision);
                });
            } finally {connection.rollback();}
        }
    }

    @Test
    void concurrentPublicationSerializesWithComponentInsertion() throws Exception {
        UUID id=UUID.randomUUID();
        try (var publisher=roleConnection("api_write_admin");var mutation=roleConnection("api_write_admin")) {
            jdbc(publisher).sql("INSERT INTO rating.formula_definition(id,formula_key,version,effective_from,definition,source_hash) VALUES (:id,:key,1,now(),'{}',repeat('b',64))")
                    .param("id",id).param("key","concurrent-"+id).update();
            publisher.setAutoCommit(false);mutation.setAutoCommit(false);
            jdbc(publisher).sql("UPDATE rating.formula_definition SET status='published',published_at=now() WHERE id=:id").param("id",id).update();
            CountDownLatch started=new CountDownLatch(1);
            try (var executor=java.util.concurrent.Executors.newSingleThreadExecutor()) {
                var future=executor.submit(()->{
                    started.countDown();
                    try { jdbc(mutation).sql("INSERT INTO rating.formula_component(formula_definition_id,component_code,numerator_metric,weight,normalization,missing_policy,minimum_quality) VALUES (:id,'racing','views',1,'none','omit','exact')").param("id",id).update(); return "inserted"; }
                    catch (org.springframework.dao.DataAccessException failure) { return ((SQLException)failure.getMostSpecificCause()).getSQLState(); }
                });
                assertThat(started.await(5,TimeUnit.SECONDS)).isTrue();
                // The publisher retains the parent lock; the mutation cannot commit before it.
                assertThat(future.isDone()).isFalse();
                publisher.commit();
                assertThat(future.get(10,TimeUnit.SECONDS)).isEqualTo("55000");
            } finally {mutation.rollback();publisher.rollback();}
        }
    }

    @Test
    void ratingContinuationMakesAll205EntitiesAvailableWithRawSelectRevoked() throws Exception {
        try (var connection=connection()) {
            connection.setAutoCommit(false);
            try {
                var jdbc=jdbc(connection);UUID institution=UUID.randomUUID();long seed=9_000_000_000L+Math.floorMod(UUID.randomUUID().getLeastSignificantBits(),100_000_000L);
                jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,'Pagination fixture')").param("id",institution).update();
                jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('institutions',:legacy,:id)").param("legacy",seed).param("id",institution).update();
                jdbc.sql("WITH accounts AS (INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,current_username,access_mode,enabled) SELECT :institution,'telegram',:prefix||n,:prefix||n,'public_web',true FROM generate_series(1,205) n RETURNING id,canonical_external_id) INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) SELECT 'channels',:seed+row_number() OVER(ORDER BY canonical_external_id),id FROM accounts")
                        .param("institution",institution).param("prefix","page-"+institution+"-").param("seed",seed).update();
                long revision=revision(jdbc);rebuild(jdbc,revision);
                connection.commit();
                try (var reader=roleConnection("api_read")) {
                reader.setAutoCommit(false);
                var readJdbc=jdbc(reader);
                blocked(reader,"SELECT subscriber_count FROM ingest.account_metric_snapshot LIMIT 1","42501");
                var repository=new JdbcProjectionQueryRepository(readJdbc);
                var query=ActivityRatingQuery.normalized(Platform.TELEGRAM,PeriodKey.THIRTY_DAYS,"engagement","desc","view_share","desc");
                var service=new PublicQueryService(repository,()->new org.mranked.cache.domain.DatasetRevision(revision,java.time.Instant.now()),new CursorCodec());
                var selected=new org.mranked.cache.domain.DatasetRevision(revision,java.time.Instant.now());
                HashSet<UUID> seen=new HashSet<>();String cursor=null;int expectedOffset=0;
                do {
                    var page=service.ratingPageAtRevision(query,50,cursor,selected);
                    assertThat(page.entityOffset()).isEqualTo(expectedOffset);
                    for (var entity:page.entities()) assertThat(seen.add(entity.entityId())).isTrue();
                    expectedOffset+=page.entities().size();cursor=page.nextEntityCursor();
                } while(cursor!=null);
                assertThat(seen.size()).isGreaterThanOrEqualTo(205);
                var candidates=new java.util.ArrayList<Long>();String candidateCursor=null;
                do {
                    var page=service.comparisonCandidatesAtRevision(Platform.TELEGRAM,50,candidateCursor,selected);
                    candidates.addAll(page.items().stream().map(org.mranked.query.domain.ComparisonCandidate::selectionLegacyId).toList());
                    candidateCursor=page.nextCursor();
                } while(candidateCursor!=null);
                assertThat(candidates.size()).isGreaterThanOrEqualTo(205);
                assertThat(new HashSet<>(candidates)).hasSize(candidates.size());
                var defaultSeries=new java.util.ArrayList<Long>();String selectionCursor=null;UUID cohort=null;
                do {
                    var page=service.comparisonPageAtRevision(Platform.TELEGRAM,72,false,"reactions","median",50,
                            org.mranked.query.domain.ComparisonSelection.defaults(org.mranked.query.domain.ComparisonSelectionType.CHANNELS),selectionCursor,selected);
                    if(cohort==null)cohort=page.cohortId();
                    assertThat(page.cohortId()).isEqualTo(cohort);
                    assertThat(page.series().size()).isLessThanOrEqualTo(50);
                    defaultSeries.addAll(page.series().stream().map(org.mranked.query.domain.ComparisonSeries::selectionLegacyId).toList());
                    selectionCursor=page.nextSelectionCursor();
                } while(selectionCursor!=null);
                assertThat(defaultSeries).containsExactlyElementsOf(candidates);
                java.util.Collections.reverse(candidates);
                var explicit=new org.mranked.query.domain.ComparisonSelection(org.mranked.query.domain.ComparisonSelectionType.CHANNELS,candidates);
                var explicitSeries=new java.util.ArrayList<Long>();selectionCursor=null;
                do {
                    var page=service.comparisonPageAtRevision(Platform.TELEGRAM,72,false,"reactions","median",50,explicit,selectionCursor,selected);
                    explicitSeries.addAll(page.series().stream().map(org.mranked.query.domain.ComparisonSeries::selectionLegacyId).toList());
                    selectionCursor=page.nextSelectionCursor();
                } while(selectionCursor!=null);
                assertThat(explicitSeries).containsExactlyElementsOf(candidates);

                String plan=readJdbc.sql("EXPLAIN (ANALYZE, BUFFERS) "+ActivityRatingSql.entityPageSql(ActivityRatingSql.TELEGRAM_ENTITIES))
                        .param("revision",revision).param("period","30d").param("channelSort","engagement")
                        .param("channelDirection","desc").param("afterEntityId",null,java.sql.Types.OTHER).param("entityFetchLimit",51)
                        .query(String.class).list().toString();
                assertThat(plan).contains("account_latest").doesNotContain("account_metric_snapshot","publication_metric_snapshot");
                reader.rollback();
                }
            } finally {connection.rollback();}
        }
    }

    @Test
    void repeatableReadPreservesOverviewInstitutionAndPublicationDuringCommittedRebuild() throws Exception {
        var ds=new DriverManagerDataSource(System.getenv("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
        var jdbc=JdbcClient.create(ds);UUID institution=UUID.randomUUID(),account=UUID.randomUUID(),publication=UUID.randomUUID();
        long seed=9_200_000_000L+Math.floorMod(UUID.randomUUID().getLeastSignificantBits(),100_000_000L);
        jdbc.sql("INSERT INTO catalog.institution(id,canonical_name) VALUES (:id,'Revision race fixture')").param("id",institution).update();
        jdbc.sql("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES (:id,:institution,'vk',:external,'public_web')").param("id",account).param("institution",institution).param("external",account.toString()).update();
        jdbc.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES (:id,:account,now()-interval '1 day',now(),'post','incomplete')").param("id",publication).param("account",account).update();
        jdbc.sql("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) VALUES ('institutions',:legacy,:institution),('platform_posts',:postLegacy,:publication)").param("legacy",seed).param("institution",institution).param("postLegacy",seed+1).param("publication",publication).update();
        long first=revision(jdbc);rebuild(jdbc,first);
        var repository=new JdbcProjectionQueryRepository(jdbc);
        var provider=new JdbcDatasetRevisionProvider(jdbc);
        var target=new PublicQueryService(repository,provider,new CursorCodec());
        var factory=new ProxyFactory(target);
        factory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(ds),new AnnotationTransactionAttributeSource()));
        var service=(PublicQueryService)factory.getProxy();
        CountDownLatch pinned=new CountDownLatch(1),published=new CountDownLatch(1);
        var cache=new PublicDtoCache(provider,new PublicCacheKeyFactory(),com.github.benmanes.caffeine.cache.Caffeine.newBuilder().maximumSize(10).build(),new DisabledPublicCacheStore(),new JsonMapper(),java.time.Duration.ofMinutes(1));
        var request=cache.prepare("overview",Map.of("q","Revision race fixture"));
        try (var executor=java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var reader=executor.submit(()->cache.getOrLoadSnapshot(request,String.class,()->service.readSnapshot(revision->{
                assertThat(revision.id()).isEqualTo(first);pinned.countDown();
                try {if(!published.await(10,TimeUnit.SECONDS))throw new AssertionError("rebuild timeout");}catch(InterruptedException error){throw new RuntimeException(error);}
                var overview=service.overviewAtRevision(OverviewQuery.normalized(Platform.VK,PeriodKey.ONE_DAY,"Revision race fixture","name","asc"),50,null,revision);
                assertThat(overview.items()).isNotEmpty();assertThat(overview.datasetRevision()).isEqualTo(first);
                assertThat(service.institutionAtRevision(seed,Platform.VK,PeriodKey.ONE_DAY,revision).metrics().datasetRevision()).isEqualTo(first);
                assertThat(service.publicationAtRevision(seed+1,LegacyEntityType.PLATFORM_POSTS,revision).datasetRevision()).isEqualTo(first);
                return "coherent-"+revision.id();
            })));
            assertThat(pinned.await(10,TimeUnit.SECONDS)).isTrue();
            long second=revision(jdbc);rebuild(jdbc,second);published.countDown();
            var body=reader.get(15,TimeUnit.SECONDS);
            assertThat(body.revision().id()).isEqualTo(first);
            assertThat(request.key().atRevision(body.revision()).redisKey()).contains(":r"+first+":");
            assertThat(new org.mranked.cache.application.ETagFactory().create(request.key().atRevision(body.revision()))).startsWith("\"mr-"+first+"-");
            var fresh=cache.getOrLoadSnapshot(request,String.class,()->service.readSnapshot(rev->"coherent-"+rev.id()));
            // An explicitly old cache request is immutable; normal HTTP requests prepare again.
            assertThat(fresh.value()).isEqualTo(body.value());
            var current=cache.getOrLoadSnapshot(cache.prepare("overview",Map.of("q","Revision race fixture")),String.class,()->service.readSnapshot(rev->"coherent-"+rev.id()));
            assertThat(current.revision().id()).isEqualTo(second);
        } finally {published.countDown();}
    }

    private static void blocked(Connection connection,String sql,String state) throws Exception {
        var savepoint=connection.setSavepoint();
        try (var statement=connection.createStatement()) {
            assertThatThrownBy(()->statement.execute(sql)).isInstanceOf(SQLException.class)
                    .satisfies(error->assertThat(((SQLException)error).getSQLState()).isEqualTo(state));
        } finally {connection.rollback(savepoint);}
    }
}
