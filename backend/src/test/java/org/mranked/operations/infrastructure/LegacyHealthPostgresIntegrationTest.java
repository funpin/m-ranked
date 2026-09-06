package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.cache.infrastructure.JdbcDatasetRevisionProvider;
import org.mranked.operations.application.LegacyHealthService;
import org.mranked.operations.application.ReadinessService;
import org.mranked.operations.web.LegacyHealthController;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import tools.jackson.databind.json.JsonMapper;

@EnabledIfEnvironmentVariable(named="MRANKED_HEALTH_TEST_ADMIN_URL",matches=".+")
class LegacyHealthPostgresIntegrationTest {
    @Test void safeHealthContractTracksRealCollectorsAllProjectionsAndFailureStates() throws Exception {
        long started=System.nanoTime();String initial=System.getenv("MRANKED_HEALTH_TEST_ADMIN_URL");
        URI uri=URI.create(initial.substring(5));assertThat(uri.getHost()).isIn("127.0.0.1","localhost");assertThat(uri.getPath()).endsWith("_it");
        String database="mranked_health_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+database,null,null);
        String owner=System.getenv("MRANKED_HEALTH_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_HEALTH_TEST_ADMIN_PASSWORD");
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+database+" OWNER migration_owner");
            try {
                Flyway.configure().dataSource(url,owner,password).initSql("SET ROLE migration_owner").defaultSchema("flyway")
                        .locations("classpath:db/migration").cleanDisabled(true).load().migrate();
                var reader=new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"));
                var jdbc=JdbcClient.create(reader);var json=new JsonMapper();
                var source=new JdbcHealthSnapshotSource(reader,json);
                var service=new LegacyHealthService(source,"public_web",60,"unknown","missing","missing","missing",false,false);
                var mvc=MockMvcBuilders.standaloneSetup(new LegacyHealthController(service)).build();
                var readiness=new ReadinessService(new JdbcReadinessProbe(jdbc,new JdbcDatasetRevisionProvider(jdbc)));
                assertThatThrownBy(() -> jdbc.sql("SELECT value FROM ops_and_admin.operational_checkpoint").query(String.class).list())
                        .hasMessageContaining("bad SQL grammar");
                try(var seed=DriverManager.getConnection(url,owner,password);var statement=seed.createStatement()) {
                    statement.execute("""
                        INSERT INTO catalog.institution(id,canonical_name) VALUES ('00000000-0000-0000-0000-000000000019','Health fixture');
                        INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,access_mode)
                            VALUES('00000000-0000-0000-0000-000000000019','telegram','health','public_web');
                        INSERT INTO ingest.collection_run(platform,partition_key,collector_version,started_at,completed_at,status,correlation_id)
                            VALUES('telegram','migration:test','sqlite-bridge/test',now()-interval '1 minute',now(),'succeeded',gen_random_uuid());
                        INSERT INTO analytics.dataset_revision(id,cause,correlation_id) VALUES(19,'migration',gen_random_uuid());
                        INSERT INTO analytics.projection_state(projection_name,dataset_revision_id,status,refreshed_at,row_count)
                            SELECT name,19,'ready',now(),0 FROM (VALUES ('publication_latest'),('publication_hourly'),
                                ('institution_daily_metrics'),('institution_monthly_metrics'),('institution_period_metrics'),('comparison'),
                                ('publication_history'),('publication_content'),('legacy_exports')) names(name);
                        """);
                    assertThat(source.snapshot().toString()).doesNotContain("migration:test");
                    mvc.perform(get("/api/v1/health/legacy")).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"))
                            .andExpect(jsonPath("$.collector_fresh").value(false)).andExpect(jsonPath("$.channels").value(1));
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isServiceUnavailable());
                    try(var checkpoint=seed.prepareStatement("INSERT INTO ops_and_admin.operational_checkpoint(checkpoint_key,scope_type,value) VALUES(?, 'system',?::jsonb)")) {
                        for(var entry:Map.of("poll_last_completed_at",Instant.now().minusSeconds(60).toString(),
                                "poll_last_duration_seconds","0","poll_last_error_count","0","poll_last_channel_count","1",
                                "telegram_web_last_error","token=never-public /private/secret", "unknown_session_key","secret-unknown-value").entrySet()) {
                            checkpoint.setString(1,entry.getKey());checkpoint.setString(2,json.writeValueAsString(entry.getValue()));checkpoint.addBatch();
                        } checkpoint.executeBatch();
                    }
                    String safe=json.writeValueAsString(source.snapshot());
                    assertThat(safe).contains("upstream_error").doesNotContain("never-public","/private/secret","secret-unknown-value","unknown_session_key");
                    statement.execute("UPDATE ops_and_admin.operational_checkpoint SET value='{\"present\":false,\"length\":0,\"sha256\":null}'::jsonb WHERE checkpoint_key='telegram_web_last_error'");
                    mvc.perform(get("/api/v1/health/legacy")).andExpect(jsonPath("$.integrations.telegram.comments_last_error").isEmpty());
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isOk()).andExpect(jsonPath("$.datasetRevision").value(19));
                    mvc.perform(get("/api/v1/health/legacy")).andExpect(status().isOk()).andExpect(jsonPath("$.collector_fresh").value(true))
                            .andExpect(jsonPath("$.poll_cycle.duration_seconds").value("0"));
                    assertThat(readiness.status().status().name()).isEqualTo("UP");
                    statement.execute("UPDATE analytics.projection_state SET status='failed' WHERE projection_name='publication_history'");
                    assertThat(readiness.status().status().name()).isEqualTo("DOWN");
                    assertThat(new JdbcDatasetRevisionProvider(jdbc).current().id()).isZero();
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isServiceUnavailable());
                    statement.execute("UPDATE analytics.projection_state SET status='ready'");
                    statement.execute("INSERT INTO analytics.dataset_revision(id,cause,correlation_id) VALUES(20,'migration',gen_random_uuid())");
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.revisionLag").value(1));
                    statement.execute("UPDATE analytics.projection_state SET dataset_revision_id=20");
                    statement.execute("""
                        INSERT INTO ingest.collection_run(platform,partition_key,collector_version,started_at,completed_at,status,correlation_id)
                        VALUES('telegram','controlled','target/test',now()-interval '1 minute',now(),'failed',gen_random_uuid())
                        """);
                    mvc.perform(get("/api/v1/health/legacy")).andExpect(status().isOk()).andExpect(jsonPath("$.collector_fresh").value(false))
                            .andExpect(jsonPath("$.poll_cycle.completed_at").isNotEmpty());
                    statement.execute("UPDATE ingest.collection_run SET status='succeeded' WHERE collector_version='target/test'");
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isOk());
                    statement.execute("UPDATE ingest.collection_run SET started_at=now()+interval '1 day',completed_at=now()+interval '1 day' WHERE collector_version='target/test'");
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isServiceUnavailable());
                    statement.execute("UPDATE ingest.collection_run SET started_at=now()-interval '1 day',completed_at=now()-interval '1 day' WHERE collector_version='target/test'");
                    mvc.perform(get("/api/v1/health/freshness")).andExpect(status().isServiceUnavailable());
                }
                var failed=MockMvcBuilders.standaloneSetup(new LegacyHealthController(new LegacyHealthService(
                        () -> {throw new IllegalStateException("password=never-public /private/secret");},"public_web",60,
                        "unknown","missing","missing","missing",false,false))).build();
                failed.perform(get("/api/v1/health/legacy")).andExpect(status().isServiceUnavailable())
                        .andExpect(content().json("{\"status\":\"DOWN\"}")).andExpect(header().string("Cache-Control","no-store"));
                try(var locker=DriverManager.getConnection(url,owner,password)) {
                    locker.setAutoCommit(false);locker.createStatement().execute("LOCK TABLE ops_and_admin.operational_checkpoint IN ACCESS EXCLUSIVE MODE");
                    long lockStarted=System.nanoTime();
                    mvc.perform(get("/api/v1/health/legacy")).andExpect(status().isServiceUnavailable())
                            .andExpect(content().json("{\"status\":\"DOWN\"}"));
                    assertThat((System.nanoTime()-lockStarted)/1e9).isBetween(2.5,5.0);
                    locker.rollback();
                }
            } finally {control.createStatement().execute("DROP DATABASE "+database+" WITH (FORCE)");}
        }
        String output=System.getenv("MRANKED_HEALTH_TEST_REPORT_PATH");
        if(output!=null)Files.writeString(Path.of(output),new JsonMapper().writerWithDefaultPrettyPrinter().writeValueAsString(Map.of(
                "status","pass","database",database,"ownedDatabaseRemoved",true,"productionAcceptance",false,
                "checks",java.util.List.of("restricted-api-role","sanitized-allowlist","migration-runs-not-freshness","legacy-null-zero-types",
                        "all-nine-projection-states","revision-lag","failed-collector","future-clock","stale-collector","secret-free-503","real-lock-jdbc-timeout"),
                "durationSeconds",(System.nanoTime()-started)/1e9))+"\n");
    }
}
