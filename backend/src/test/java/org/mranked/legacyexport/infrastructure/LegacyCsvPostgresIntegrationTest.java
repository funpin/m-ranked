package org.mranked.legacyexport.infrastructure;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.mranked.cache.infrastructure.JdbcDatasetRevisionProvider;
import org.mranked.legacyexport.application.LegacyCsvService;
import org.mranked.legacyexport.web.LegacyCsvController;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

/** Actual Flyway + bridge + api_read cursor + Spring MVC bytes versus original FastAPI. */
@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class LegacyCsvPostgresIntegrationTest {
    @TempDir Path output;
    @Test void originalFastApiBytesMatchAllFormatsAndActualTargetChangesCannotHideBehindSourceHashes() throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");
        URI uri=URI.create(initial.substring(5));
        assertThat(uri.getHost()).isIn("127.0.0.1","localhost","[::1]");
        assertThat(uri.getPath()).endsWith("_it");
        String name="mranked_csv_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+name,null,null);
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                Flyway.configure().dataSource(url,owner,password).initSql("SET ROLE migration_owner")
                    .defaultSchema("flyway").locations("filesystem:"+root.resolve("backend/src/main/resources/db/migration"))
                    .cleanDisabled(true).load().migrate();
                var emptyData=new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"));
                new JdbcLegacyCsvRows(emptyData).stream(new org.mranked.legacyexport.application.LegacyCsvFormat("posts","telegram"),0,
                    cells -> {throw new AssertionError("Empty database returned a CSV row");});
                var process=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.legacy_csv_fixture",
                    "--output",output.toString()).directory(root.toFile()).redirectErrorStream(true)
                    .redirectOutput(output.resolve("producer.log").toFile());
                process.environment().put("MRANKED_LEGACY_CSV_DSN",new URI("postgresql",owner+":"+password,
                    uri.getHost(),uri.getPort(),"/"+name,null,null).toString());
                var producer=process.start();
                assertThat(producer.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
                assertThat(producer.exitValue()).withFailMessage(Files.readString(output.resolve("producer.log"))).isZero();
                var data=new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"));
                var target=new LegacyCsvService(new JdbcLegacyCsvRows(data),new JdbcDatasetRevisionProvider(JdbcClient.create(data)));
                ProxyFactory factory=new ProxyFactory(target);
                factory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(data),new AnnotationTransactionAttributeSource()));
                var service=(LegacyCsvService)factory.getProxy();
                try {
                    var mvc=MockMvcBuilders.standaloneSetup(new LegacyCsvController(service)).build();
                    var json=new tools.jackson.databind.json.JsonMapper();
                    var cases=json.readTree(Files.readString(output.resolve("manifest.json"))).path("cases");
                    assertThat(cases.size()).isEqualTo(14);
                    for(var item:cases) {
                        var request=mvc.perform(get("/api/v1/legacy-exports/"+item.path("kind").asString()+".csv")
                            .param("platform",item.path("platform").asString()).param("ignored","1")).andReturn();
                        assertThat(request.getResponse().getStatus()).withFailMessage("%s: %s",item.path("file").asString(),request.getResponse().getContentAsString()).isEqualTo(200);
                        assertThat(request.getRequest().isAsyncStarted()).isTrue();
                        var response=mvc.perform(asyncDispatch(request)).andReturn().getResponse();
                        assertThat(response.getContentAsByteArray()).as(item.path("file").asString())
                            .isEqualTo(Files.readAllBytes(output.resolve(item.path("file").asString())));
                        assertThat(response.getHeader("Content-Disposition")).isEqualTo(item.path("disposition").asString());
                        assertThat(response.getHeader("Content-Type")).isEqualTo(item.path("contentType").asString());
                        assertThat(response.getHeader("Cache-Control")).isEqualTo("no-store");
                        assertThat(response.getHeader("X-Dataset-Revision")).isNotBlank();
                    }
                    var duplicates=mvc.perform(get("/api/v1/legacy-exports/posts.csv").param("platform","vk","tg")).andReturn();
                    assertThat(mvc.perform(asyncDispatch(duplicates)).andReturn().getResponse().getContentAsByteArray())
                        .isEqualTo(Files.readAllBytes(output.resolve("05.csv")));
                    // A corrupted target projection cannot be hidden by matching mapping/evidence hashes.
                    try(var changed=DriverManager.getConnection(url,owner,password);var statement=changed.createStatement()) {
                        statement.execute("UPDATE analytics.legacy_export_row SET cells[6]='999999' WHERE kind='snapshots' AND namespace='telegram' AND ordinal=1");
                    }
                    var changed=mvc.perform(get("/api/v1/legacy-exports/snapshots.csv")).andReturn();
                    assertThat(mvc.perform(asyncDispatch(changed)).andReturn().getResponse().getContentAsByteArray())
                        .isNotEqualTo(Files.readAllBytes(output.resolve("00.csv")));
                    // Classified unsafe evidence returns no CSV bytes, even after the artifact has begun preparation.
                    try(var blocked=DriverManager.getConnection(url,owner,password);var statement=blocked.createStatement()) {
                        statement.execute("UPDATE analytics.legacy_export_row SET blocked_reason='UNSAFE_RAW_JSON' WHERE kind='snapshots' AND namespace='generic' AND platform='vk'");
                    }
                    var blocked=mvc.perform(get("/api/v1/legacy-exports/snapshots.csv").param("platform","vk")).andReturn().getResponse();
                    assertThat(blocked.getStatus()).isEqualTo(409);
                    assertThat(blocked.getContentAsString()).contains("UNSAFE_RAW_JSON").doesNotContain("сырой_json");
                    assertThat(JdbcClient.create(data).sql("SELECT has_table_privilege(current_user,'ingest.publication_metric_snapshot','SELECT')").query(Boolean.class).single()).isFalse();
                    try(var reader=data.getConnection();var statement=reader.createStatement()) {
                        var denied=org.junit.jupiter.api.Assertions.assertThrows(java.sql.SQLException.class,
                            () -> statement.execute("SELECT * FROM migration.legacy_export_lexeme LIMIT 1"));
                        assertThat(denied.getSQLState()).isEqualTo("42501");
                    }
                    // Actual collector role creates new publications and aliases; reverse sync
                    // verifies the generated raw representation before a second bridge import.
                    process.command().add("--native");
                    var nativeProducer=process.start();
                    assertThat(nativeProducer.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
                    assertThat(nativeProducer.exitValue()).withFailMessage(Files.readString(output.resolve("producer.log"))).isZero();
                    var nativeTarget=new LegacyCsvService(new JdbcLegacyCsvRows(data),new JdbcDatasetRevisionProvider(JdbcClient.create(data)));
                    ProxyFactory nativeFactory=new ProxyFactory(nativeTarget);
                    nativeFactory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(data),new AnnotationTransactionAttributeSource()));
                    try {
                        var nativeMvc=MockMvcBuilders.standaloneSetup(new LegacyCsvController((LegacyCsvService)nativeFactory.getProxy())).build();
                        var nativeManifest=json.readTree(Files.readString(output.resolve("native-manifest.json")));
                        assertThat(nativeManifest.path("attribution").asString()).isEqualTo("target-generated-v1");
                        assertThat(nativeManifest.path("nativeSnapshots").asInt()).isEqualTo(8);
                        for(var item:nativeManifest.path("cases")) {
                            var request=nativeMvc.perform(get("/api/v1/legacy-exports/"+item.path("kind").asString()+".csv")
                                .param("platform",item.path("platform").asString())).andReturn();
                            assertThat(request.getResponse().getStatus()).isEqualTo(200);
                            assertThat(nativeMvc.perform(asyncDispatch(request)).andReturn().getResponse().getContentAsByteArray())
                                .as("native roundtrip "+item.path("file").asString())
                                .isEqualTo(Files.readAllBytes(output.resolve(item.path("file").asString())));
                        }
                        assertRepeatableRead(data,url,owner,password,Files.readAllBytes(output.resolve("native-snapshots-telegram.csv")));
                        assertColdArchiveCannotSilentlyTruncate(url,owner,password);
                        var proof=new java.util.LinkedHashMap<String,Object>();
                        proof.put("status","pass"); proof.put("legacyCases",json.readTree(Files.readString(output.resolve("manifest.json"))));
                        proof.put("nativeRoundTrip",nativeManifest);proof.put("repeatableReadConcurrentRebuild","pass");
                        proof.put("emptyCsv","pass");proof.put("readerRawPrivileges","denied42501");
                        proof.put("coldArchivePartialExport","blocked");
                        Files.writeString(Path.of(System.getProperty("mranked.build.directory","target"),"legacy-csv-golden.json"),json.writeValueAsString(proof));
                    } finally {nativeTarget.close();}
                } finally {target.close();}
            } finally {control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)");}
        }
    }

    private static void assertColdArchiveCannotSilentlyTruncate(String url,String owner,String password) throws Exception {
        try(var connection=DriverManager.getConnection(url,owner,password)) {
            connection.setAutoCommit(false);
            try(var statement=connection.createStatement()) {
                statement.execute("INSERT INTO ops_and_admin.archive_manifest(dataset_type,schema_version,partition_start,partition_end,object_uri,sha256,row_count,status,verified_at,hot_dropped_at) VALUES('publication_metric_snapshot',1,now()-interval '400 days',now()-interval '370 days','test://cold-fixture',repeat('a',64),1,'hot_dropped',now(),now())");
                statement.execute("SELECT analytics.refresh_legacy_exports((SELECT max(id) FROM analytics.dataset_revision))");
                var rows=statement.executeQuery("SELECT count(*) FROM analytics.legacy_export_row WHERE blocked_reason='COLD_ARCHIVE_RESTORE_REQUIRED'");
                assertThat(rows.next()).isTrue();assertThat(rows.getInt(1)).isEqualTo(10);
            } finally {connection.rollback();}
        }
    }

    private static void assertRepeatableRead(javax.sql.DataSource data,String url,String owner,String password,byte[] expected) throws Exception {
        var pinned=new java.util.concurrent.CountDownLatch(1);
        var replaced=new java.util.concurrent.CountDownLatch(1);
        var delegate=new JdbcDatasetRevisionProvider(JdbcClient.create(data));
        var original=delegate.current();
        var target=new LegacyCsvService(new JdbcLegacyCsvRows(data),()->{
            var value=delegate.current(); pinned.countDown();
            try {if(!replaced.await(15,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Concurrent rebuild did not finish");}
            catch(InterruptedException failure){Thread.currentThread().interrupt();throw new IllegalStateException(failure);}
            return value;
        });
        var factory=new ProxyFactory(target);
        factory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(data),new AnnotationTransactionAttributeSource()));
        var service=(LegacyCsvService)factory.getProxy();
        try(var executor=java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var export=executor.submit(()->service.prepare(new org.mranked.legacyexport.application.LegacyCsvFormat("snapshots","telegram")));
            assertThat(pinned.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            try(var mutation=DriverManager.getConnection(url,owner,password);var statement=mutation.createStatement()) {
                mutation.setAutoCommit(false);
                statement.execute("UPDATE catalog.platform_account SET current_username=current_username||'_r2' WHERE platform='telegram'");
                var row=statement.executeQuery("INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES('configuration',gen_random_uuid()) RETURNING id");
                assertThat(row.next()).isTrue();long revision=row.getLong(1);row.close();
                statement.execute("SELECT analytics.rebuild_core_projections("+revision+")");
                mutation.commit();
            } finally {replaced.countDown();}
            try(var artifact=export.get(15,java.util.concurrent.TimeUnit.SECONDS)) {
                assertThat(artifact.revision()).isEqualTo(original);
                assertThat(Files.readAllBytes(artifact.path())).isEqualTo(expected);
            }
            assertThat(delegate.current().id()).isGreaterThan(original.id());
        } finally {replaced.countDown();target.close();}
    }
}
