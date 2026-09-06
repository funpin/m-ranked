package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.util.UUID;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.admin.application.CatalogService;
import org.mranked.admin.application.AdminOptimisticLockException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@EnabledIfEnvironmentVariable(named="MRANKED_CATALOG_TEST_POSTGRES_URL",matches=".+")
class CatalogPostgresIntegrationTest {
    private final String url=System.getenv("MRANKED_CATALOG_TEST_POSTGRES_URL");
    private final DriverManagerDataSource source=new DriverManagerDataSource(url,"api_write_admin",System.getenv("MRANKED_ADMIN_TEST_PASSWORD"));
    private final JdbcClient owner=JdbcClient.create(new DriverManagerDataSource(url,System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD")));
    private final JdbcCatalogRepository repository=new JdbcCatalogRepository(JdbcClient.create(source),new TransactionTemplate(new DataSourceTransactionManager(source)));
    private final CatalogService service=new CatalogService(repository);
    private final String actor="catalog-it-"+UUID.randomUUID();

    @Test void modernAccountRequiresObservedVersionAndRetainsLegacyHttpDisplayUrl() {
        var institution=service.createInstitution("Versioned account","VA",actor,UUID.randomUUID());
        String reference="http://max.ru/version_"+UUID.randomUUID();
        var created=service.versionedAccount(institution.targetId(),null,"max",reference,null,null,actor,UUID.randomUUID());
        assertThatThrownBy(()->service.versionedAccount(institution.targetId(),null,"max",reference,"Unobserved update",null,actor,UUID.randomUUID()))
            .isInstanceOf(AdminOptimisticLockException.class);
        var updated=service.versionedAccount(institution.targetId(),created.rowVersion(),"max",reference,"Observed update",null,actor,UUID.randomUUID());
        assertThat(owner.sql("SELECT current_url FROM catalog.platform_account WHERE id=:id").param("id",updated.targetId()).query(String.class).single()).isEqualTo(reference);
        assertThat(owner.sql("SELECT url FROM catalog.account_identity_history WHERE platform_account_id=:id AND valid_to IS NULL").param("id",updated.targetId()).query(String.class).single()).isEqualTo(reference);
        service.accountCommand(updated.targetId(),updated.rowVersion(),"delete",null,actor,UUID.randomUUID());
        assertThatThrownBy(()->service.versionedAccount(institution.targetId(),updated.rowVersion(),"max",reference,null,null,actor,UUID.randomUUID()))
            .isInstanceOf(AdminOptimisticLockException.class);
    }

    @Test void officialImportKeepsPerChannelRanksNullCategoriesAuditAndIdempotentHttpCommand() {
        var institution=service.createInstitution("Official import institution","OI",actor,UUID.randomUUID());
        var mephi=service.upsertAccount(institution.targetId(),null,"telegram","mephi_of",null,null,actor,UUID.randomUUID());
        var kbsu=service.upsertAccount(institution.targetId(),null,"telegram","kbsu1957",null,null,actor,UUID.randomUUID());
        var repository=new JdbcOfficialRatingRepository(JdbcClient.create(source),new TransactionTemplate(new DataSourceTransactionManager(source)));
        var fetched=new java.util.concurrent.atomic.AtomicInteger();
        var dataset=OfficialRatingParser.parse("{\"months\":[{\"name\":\"Август\",\"items\":[{\"code\":\"19\",\"name\":\"MEPHI\",\"scores\":{\"social\":10,\"tg\":8}},{\"code\":\"84\",\"name\":\"KBSU\",\"scores\":{\"social\":20,\"tg\":9,\"vk\":3}}]}]}".getBytes(java.nio.charset.StandardCharsets.UTF_8),2026,"https://www.m-rating.ru/ratings.json",java.time.Instant.now().minusSeconds(60));
        var ratings=new org.mranked.admin.application.OfficialRatingService(()->{fetched.incrementAndGet();return dataset;},repository);
        var legacy=new org.mranked.admin.application.LegacyCatalogService(service,this.repository,ratings);
        UUID correlation=UUID.randomUUID();
        var result=ratings.refresh(actor,correlation);
        assertThat(legacy.execute("/manage/m-rating/update",Map.of(),actor,correlation)).isEqualTo("/manage?m_rating_status=updated");
        assertThat(fetched.get()).isOne();assertThat(result.updated()).isOne();assertThat(result.available()).isEqualTo(2);
        for(var account:Map.of(mephi.targetId(),2,kbsu.targetId(),1).entrySet())
            assertThat(owner.sql("SELECT DISTINCT rating_rank FROM analytics.legacy_overview_card WHERE entity_id=:id AND platform='telegram'")
                .param("id",account.getKey()).query(Integer.class).list()).containsExactly(account.getValue());
        var managed=this.repository.institutions(institution.legacyId()-1,1).getFirst();
        assertThat(managed.officialRatings().get("all").rank()).isOne();
        assertThat(managed.officialRatings().get("vk").score()).isEqualByComparingTo("3");
        assertThat(managed.officialRatings().get("max").rank()).isNull();
        assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.audit_log WHERE correlation_id=:id").param("id",correlation).query(Integer.class).single()).isOne();
        assertThat(owner.sql("SELECT count(*) FROM rating.official_import WHERE correlation_id=:id AND evidence_sha256=encode(sha256(convert_to(evidence::text,'UTF8')),'hex')").param("id",correlation).query(Integer.class).single()).isOne();
        assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.outbox_event WHERE dataset_revision_id=:id AND event_type='official_rating.updated'").param("id",result.datasetRevision()).query(Integer.class).single()).isOne();
        assertThatThrownBy(()->owner.sql("UPDATE rating.official_import SET period='changed' WHERE correlation_id=:id").param("id",correlation).update()).isInstanceOf(org.springframework.dao.DataAccessException.class);
        var unavailable=new org.mranked.admin.application.OfficialRatingService(()->{throw new IllegalStateException("sensitive-token-never-log");},repository);
        UUID failure=UUID.randomUUID();
        assertThat(new org.mranked.admin.application.LegacyCatalogService(service,this.repository,unavailable).execute("/manage/m-rating/update",Map.of(),actor,failure)).isEqualTo("/manage?m_rating_status=error");
        String checkpoint=owner.sql("SELECT value::text FROM ops_and_admin.operational_checkpoint WHERE checkpoint_key='admin.m_rating'").query(String.class).single();
        assertThat(checkpoint).contains("Август 2026","official_source_unavailable").doesNotContain("sensitive-token");
        UUID retry=UUID.randomUUID();
        owner.sql("ALTER TABLE analytics.projection_state ADD CONSTRAINT official_injected_failure CHECK(dataset_revision_id<0) NOT VALID").update();
        try {
            assertThatThrownBy(()->ratings.refresh(actor,retry)).isInstanceOf(org.springframework.dao.DataAccessException.class);
            assertThat(owner.sql("SELECT count(*) FROM rating.official_import WHERE correlation_id=:id").param("id",retry).query(Integer.class).single()).isZero();
            assertThat(owner.sql("SELECT count(*) FROM analytics.dataset_revision WHERE correlation_id=:id").param("id",retry).query(Integer.class).single()).isZero();
        } finally { owner.sql("ALTER TABLE analytics.projection_state DROP CONSTRAINT official_injected_failure").update(); }
        assertThat(ratings.refresh(actor,retry).updated()).isOne();
    }

    @Test void legacyFormsKeepRedirectsAndMatrixConflictRollsBackEveryEarlierAccount() {
        var legacy=new org.mranked.admin.application.LegacyCatalogService(service,repository,null);
        String suffix=UUID.randomUUID().toString().replace("-","").substring(0,12);
        String location=legacy.execute("/manage/institutions",Map.of("name","Legacy "+suffix,"short_name","L"),actor,UUID.randomUUID());
        long id=Long.parseLong(location.substring(location.lastIndexOf('=')+1));
        UUID institution=service.resolve("institutions",id);
        assertThat(legacy.execute("/manage/institutions/"+id,Map.of("name","Edited "+suffix,"short_name","E","expected_row_version","0"),actor,UUID.randomUUID()))
            .isEqualTo("/manage?platform_status=institution-updated&institution_id="+id);
        var fields=new java.util.HashMap<>(Map.of("telegram","@legacy_"+suffix,"vk","https://vk.com/legacy_"+suffix,
            "max_account","max_"+suffix,"rutube","https://rutube.ru/channel/"+suffix,"expected_row_version","1","expected_account_versions","{}"));
        assertThat(legacy.execute("/manage/institutions/"+id+"/accounts",fields,actor,UUID.randomUUID()))
            .isEqualTo("/manage?platform_status=accounts-updated&institution_id="+id);
        var accounts=repository.accounts(institution,0,200);assertThat(accounts).hasSize(4);
        var maximum=accounts.stream().filter(account->account.platform().equals("max")).findFirst().orElseThrow();
        assertThat(legacy.execute("/manage/platform-accounts/"+maximum.legacyId()+"/native-id",Map.of("native_id","-123456","expected_row_version","0"),actor,UUID.randomUUID()))
            .isEqualTo("/manage?platform_status=native-id-updated&institution_id="+id);
        var stale=new java.util.LinkedHashMap<String,Long>();accounts.forEach(account->stale.put(account.id().toString(),account.rowVersion()));
        fields.put("expected_account_versions",new tools.jackson.databind.json.JsonMapper().writeValueAsString(stale));
        assertThatThrownBy(()->legacy.execute("/manage/institutions/"+id+"/accounts",fields,actor,UUID.randomUUID())).isInstanceOf(AdminOptimisticLockException.class);
        for(var current:repository.accounts(institution,0,200)) assertThat(current.rowVersion()).isEqualTo(current.id().equals(maximum.id())?1:0);
        String accountPath="/manage/platform-accounts/"+maximum.legacyId();
        assertThat(legacy.execute(accountPath+"/disable",Map.of("expected_row_version","1"),actor,UUID.randomUUID())).contains("account-disabled");
        assertThat(legacy.execute(accountPath+"/enable",Map.of("expected_row_version","2"),actor,UUID.randomUUID())).contains("account-enabled");
        assertThat(legacy.execute(accountPath+"/native-id",Map.of("expected_row_version","3","native_id",""),actor,UUID.randomUUID())).contains("native-id-updated");
        assertThat(legacy.execute(accountPath+"/delete",Map.of("expected_row_version","4"),actor,UUID.randomUUID())).contains("account-deleted");
        assertThat(legacy.execute("/manage/platform-accounts",Map.of("institution_id",Long.toString(id),"platform","vk","reference","other_"+suffix,"title","Other"),actor,UUID.randomUUID()))
            .isEqualTo("/manage?platform_status=account-added");
        assertThat(legacy.execute("/manage/channels",Map.of("channel","auto_"+suffix),actor,UUID.randomUUID())).isEqualTo("/manage?channel_status=added");
        long channel=owner.sql("SELECT alias.legacy_id FROM catalog.visible_platform_account account JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id AND alias.entity_type='channels' WHERE account.current_username=:name")
            .param("name","auto_"+suffix).query(Long.class).single();
        assertThat(legacy.execute("/manage/channels/"+channel+"/disable",Map.of("expected_row_version","0"),actor,UUID.randomUUID())).isEqualTo("/manage");
        assertThat(legacy.execute("/manage/channels/"+channel+"/enable",Map.of("expected_row_version","1"),actor,UUID.randomUUID())).isEqualTo("/manage");
        assertThat(legacy.execute("/manage/channels/"+channel+"/delete",Map.of("expected_row_version","2"),actor,UUID.randomUUID())).isEqualTo("/manage?channel_status=deleted");
    }

    @Test void simultaneousIdenticalCommandsPublishOnlyOneAuditAndRevision() throws Exception {
        UUID correlation=UUID.randomUUID();
        try(var pool=java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var latch=new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.Callable<org.mranked.admin.domain.CatalogCommandResult> command=()->{latch.await();return service.createInstitution("Simultaneous replay","SR",actor,correlation);};
            var first=pool.submit(command);var second=pool.submit(command);latch.countDown();
            assertThat(first.get(30,java.util.concurrent.TimeUnit.SECONDS)).isEqualTo(second.get(30,java.util.concurrent.TimeUnit.SECONDS));
        }
        assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.audit_log WHERE correlation_id=:id").param("id",correlation).query(Integer.class).single()).isOne();
        assertThat(owner.sql("SELECT count(*) FROM analytics.dataset_revision WHERE correlation_id=:id").param("id",correlation).query(Integer.class).single()).isOne();
    }

    @Test void nativeIdHistoryDeletionReenrollmentAndIdempotentReplayPreserveImmutableFacts() {
        var createId=UUID.randomUUID();
        var institution=service.createInstitution("Catalogue rehearsal","CR",actor,createId);
        assertThat(service.createInstitution("Catalogue rehearsal","CR",actor,createId)).isEqualTo(institution);
        assertThatThrownBy(()->service.createInstitution("Different payload","CR",actor,createId)).isInstanceOf(AdminOptimisticLockException.class);
        var account=service.upsertAccount(institution.targetId(),null,"max","catalogue_"+UUID.randomUUID(),null,null,actor,UUID.randomUUID());
        String canonical=owner.sql("SELECT canonical_external_id FROM catalog.platform_account WHERE id=:id").param("id",account.targetId()).query(String.class).single();
        var known=service.accountCommand(account.targetId(),0,"native_id","-12345",actor,UUID.randomUUID());
        var changed=service.accountCommand(account.targetId(),known.rowVersion(),"native_id","-67890",actor,UUID.randomUUID());
        assertThat(owner.sql("SELECT external_id FROM catalog.account_external_identity WHERE platform_account_id=:id ORDER BY valid_from")
            .param("id",account.targetId()).query(String.class).list()).containsExactly("-12345","-67890");
        assertThat(owner.sql("SELECT canonical_external_id FROM catalog.platform_account WHERE id=:id").param("id",account.targetId()).query(String.class).single()).isEqualTo(canonical);
        UUID publication=seedObservation(account.targetId());
        String before=observation(publication);
        var removal=service.accountCommand(account.targetId(),changed.rowVersion(),"delete",null,actor,UUID.randomUUID());
        assertThat(removal.datasetRevision()).isGreaterThan(changed.datasetRevision());
        assertThat(observation(publication)).isEqualTo(before);
        assertThat(owner.sql("SELECT count(*) FROM ingest.visible_publication WHERE id=:id").param("id",publication).query(Integer.class).single()).isZero();
        assertThat(owner.sql("SELECT count(*) FROM analytics.publication_history WHERE publication_id=:id").param("id",publication).query(Integer.class).single()).isZero();
        assertThat(owner.sql("SELECT enabled FROM catalog.platform_account WHERE id=:id").param("id",account.targetId()).query(Boolean.class).single()).isFalse();
        var enrolled=service.upsertAccount(institution.targetId(),null,"max",canonical,null,null,actor,UUID.randomUUID());
        assertThat(enrolled.targetId()).isNotEqualTo(account.targetId());
        assertThat(enrolled.legacyId()).isGreaterThan(account.legacyId());
        assertThat(repository.institutions(institution.legacyId()-1,1)).singleElement().satisfies(row->{
            assertThat(row.accounts()).singleElement().satisfies(value->assertThat(value.id()).isEqualTo(enrolled.targetId()));
        });
        assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.audit_log WHERE subject=:actor AND action='account.delete' AND outcome='succeeded'")
            .param("actor",actor).query(Integer.class).single()).isOne();
        assertThatThrownBy(()->owner.sql("UPDATE ops_and_admin.catalog_command_receipt SET response='{}' WHERE actor=:actor").param("actor",actor).update())
            .isInstanceOf(org.springframework.dao.DataAccessException.class);
        var read=JdbcClient.create(new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_API_READ_TEST_PASSWORD")));
        assertThatThrownBy(()->read.sql("SELECT ops_and_admin.catalog_command('institution.create',NULL,NULL,'{}','spoof',gen_random_uuid())").query(String.class).single())
            .isInstanceOf(org.springframework.dao.DataAccessException.class);
    }
    @Test void optimisticConflictAndFailedProjectionCannotPublishPartialCommand() {
        var institution=service.createInstitution("Concurrent catalogue","CC",actor,UUID.randomUUID());
        var updated=service.updateInstitution(institution.targetId(),0,"Changed catalogue","CC",actor,UUID.randomUUID());
        assertThatThrownBy(()->service.updateInstitution(institution.targetId(),0,"Stale write","BAD",actor,UUID.randomUUID()))
            .isInstanceOf(AdminOptimisticLockException.class);
        UUID correlation=UUID.randomUUID();
        owner.sql("ALTER TABLE analytics.projection_state ADD CONSTRAINT catalog_injected_rebuild_failure CHECK(dataset_revision_id<0) NOT VALID").update();
        try {
            assertThatThrownBy(()->service.updateInstitution(institution.targetId(),updated.rowVersion(),"Must roll back","BAD",actor,correlation))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
            assertThat(owner.sql("SELECT canonical_name FROM catalog.institution WHERE id=:id").param("id",institution.targetId()).query(String.class).single()).isEqualTo("Changed catalogue");
            assertThat(owner.sql("SELECT count(*) FROM analytics.dataset_revision WHERE correlation_id=:id").param("id",correlation).query(Integer.class).single()).isZero();
            assertThat(owner.sql("SELECT count(*) FROM ops_and_admin.catalog_command_receipt WHERE correlation_id=:id").param("id",correlation).query(Integer.class).single()).isZero();
        } finally { owner.sql("ALTER TABLE analytics.projection_state DROP CONSTRAINT catalog_injected_rebuild_failure").update(); }
        assertThat(service.updateInstitution(institution.targetId(),updated.rowVersion(),"Retry succeeds","OK",actor,correlation).outcome()).isEqualTo("succeeded");
    }
    private String observation(UUID publication) {
        return owner.sql("SELECT to_jsonb(snapshot)::text FROM ingest.publication_metric_snapshot snapshot WHERE publication_id=:id")
            .param("id",publication).query(String.class).single();
    }
    private UUID seedObservation(UUID account) {
        UUID run=UUID.randomUUID(),publication=UUID.randomUUID();
        owner.sql("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(:id,'max',:key,'catalog-test',now()-interval '1 hour','succeeded',gen_random_uuid())")
            .param("id",run).param("key",run.toString()).update();
        owner.sql("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) VALUES(:id,:account,now()-interval '1 hour',now()-interval '1 hour','text','complete')")
            .param("id",publication).param("account",account).update();
        owner.sql("INSERT INTO ingest.publication_metric_snapshot(published_month,publication_id,collection_run_id,observed_at,collected_at,age_seconds,sampling_bucket,views_count,quality,views_quality,source_fingerprint) VALUES(date_trunc('month',now())::date,:id,:run,now()-interval '1 minute',now()-interval '1 minute',3540,1,17,'exact','exact',:fingerprint)")
            .param("id",publication).param("run",run).param("fingerprint",UUID.randomUUID().toString()).update();
        return publication;
    }
}
