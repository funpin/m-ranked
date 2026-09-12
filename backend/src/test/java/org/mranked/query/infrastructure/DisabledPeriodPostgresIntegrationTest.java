package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.mranked.testing.FinalSchemaInstaller;
import org.mranked.cache.application.*;
import org.mranked.cache.infrastructure.*;
import org.mranked.query.application.PublicQueryService;
import org.mranked.query.application.CursorCodec;
import org.mranked.query.web.PublicQueryController;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/** Original Python bytes/NULL values versus actual projection and public institution HTTP DTO. */
@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class DisabledPeriodPostgresIntegrationTest {
    @TempDir Path output;
    @Test
    void retainedDisabledPlatformHistorySurvivesFinalSchema() throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");URI uri=URI.create(initial.substring(5));
        assertThat(uri.getHost()).isIn("127.0.0.1","localhost","[::1]");assertThat(uri.getPath()).endsWith("_it");
        String name="mranked_disabled_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+name,null,null);
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                FinalSchemaInstaller.install(url, owner, password);
                var process=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.disabled_period_oracle",
                    "--output",output.toString()).directory(root.toFile()).redirectErrorStream(true).redirectOutput(output.resolve("oracle.log").toFile());
                process.environment().put("MRANKED_LEGACY_CSV_DSN",new URI("postgresql",owner+":"+password,
                    uri.getHost(),uri.getPort(),"/"+name,null,null).toString());
                run(process);
                var admin=JdbcClient.create(new DriverManagerDataSource(url,owner,password));
                process.command().add("--verify");run(process);
                var json=new tools.jackson.databind.json.JsonMapper();
                var proof=json.readTree(Files.readString(output.resolve("disabled-period-oracle.json")));
                assertThat(proof.path("cases").size()).isEqualTo(288);
                var jdbc=JdbcClient.create(new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD")));
                var revisions=new JdbcDatasetRevisionProvider(jdbc);
                var service=new PublicQueryService(new JdbcProjectionQueryRepository(jdbc),revisions,new CursorCodec());
                var cache=new PublicDtoCache(revisions,new PublicCacheKeyFactory(),
                    com.github.benmanes.caffeine.cache.Caffeine.newBuilder().maximumSize(100).<String,String>build(),
                    new DisabledPublicCacheStore(),json,java.time.Duration.ofMinutes(1));
                var mvc=MockMvcBuilders.standaloneSetup(new PublicQueryController(service,cache,new ETagFactory())).build();
                int httpValues=0;
                for(var item:proof.path("cases")) {
                    var key=item.path("key");String metric=key.get(3).asString();
                    if(!metric.equals("views")&&!metric.equals("reactions"))continue;
                    var response=mvc.perform(get("/api/v1/institutions/"+key.get(2).asLong()).param("platform",key.get(0).asString())
                        .param("period",key.get(1).asString())).andReturn().getResponse();
                    assertThat(response.getStatus()).isEqualTo(200);
                    String field=(key.get(4).asString().equals("sum")?"total":"median")+(metric.equals("views")?"Views":"Reactions");
                    var actual=json.readTree(response.getContentAsString()).path("metrics").path(field);
                    if(item.path("value").isNull())assertThat(actual.isNull()).isTrue();
                    else assertThat(actual.decimalValue()).isEqualByComparingTo(new java.math.BigDecimal(item.path("value").asString()));
                    httpValues++;
                }
                assertThat(httpValues).isEqualTo(144);
                Files.copy(output.resolve("disabled-period-oracle.json"),Path.of(System.getProperty("mranked.build.directory","target"),
                    "disabled-period-final.json"),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            } finally {control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)");}
        }
    }
    private void run(ProcessBuilder process) throws Exception {
        var child=process.start();assertThat(child.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        assertThat(child.exitValue()).withFailMessage(Files.readString(output.resolve("oracle.log"))).isZero();
    }
}
