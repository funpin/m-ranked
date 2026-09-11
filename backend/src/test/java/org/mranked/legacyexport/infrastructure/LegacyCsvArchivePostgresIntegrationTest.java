package org.mranked.legacyexport.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.mranked.testing.FinalSchemaInstaller;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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

/** Actual fenced DROP and private derived restore, followed by real MVC CSV bytes. */
@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class LegacyCsvArchivePostgresIntegrationTest {
    @TempDir Path output;
    @ParameterizedTest @ValueSource(strings={"source","native"})
    void wholeHistoryCsvSurvivesActualPartitionRemoval(String mode) throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");URI uri=URI.create(initial.substring(5));
        assertThat(uri.getHost()).isIn("127.0.0.1","localhost","[::1]");assertThat(uri.getPath()).endsWith("_it");
        String name="mranked_csv_archive_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+name,null,null);
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                FinalSchemaInstaller.install(url, owner, password);
                var process=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.legacy_csv_fixture",
                    "--output",output.toString()).directory(root.toFile()).redirectErrorStream(true).redirectOutput(output.resolve("producer.log").toFile());
                process.environment().put("MRANKED_LEGACY_CSV_OLD_FIXTURE","1");
                process.environment().put("MRANKED_LEGACY_CSV_DSN",new URI("postgresql",owner+":"+password,uri.getHost(),uri.getPort(),"/"+name,null,null).toString());
                run(process);
                if(mode.equals("native")){process.command().add("--native");run(process);process.command().remove("--native");}
                var source=new DriverManagerDataSource(url,"api_read",System.getenv("MRANKED_QUERY_TEST_PASSWORD"));
                String manifest=mode.equals("native")?"native-manifest.json":"manifest.json";
                verifyBytes(source,manifest);
                process.command().set(2,"migration.integration.legacy_csv_archive_fixture");run(process);
                verifyBytes(source,manifest);
                assertThat(JdbcClient.create(source).sql("SELECT has_table_privilege(current_user,'analytics.legacy_csv_snapshot_fact','SELECT')").query(Boolean.class).single()).isFalse();
                var proof=new tools.jackson.databind.json.JsonMapper().readTree(Files.readString(output.resolve("archive-fixture.json")));
                assertThat(proof.path("objects").size()).isPositive();
                Path evidence=Path.of(System.getProperty("mranked.build.directory","target"),"legacy-csv-archive-"+mode+".json");
                var report=new java.util.LinkedHashMap<String,Object>();report.put("status","pass");report.put("mode",mode);report.put("archive",proof);
                report.put("byteCases",mode.equals("native")?10:14);report.put("readerFactsSelect",false);
                Files.writeString(evidence,new tools.jackson.databind.json.JsonMapper().writeValueAsString(report));
            } finally {control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)");}
        }
    }
    private void run(ProcessBuilder process) throws Exception {
        var child=process.start();assertThat(child.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        assertThat(child.exitValue()).withFailMessage(Files.readString(output.resolve("producer.log"))).isZero();
    }
    private static LegacyCsvService proxy(LegacyCsvService target,javax.sql.DataSource source) {
        var factory=new ProxyFactory(target);
        factory.addAdvice(new TransactionInterceptor(new DataSourceTransactionManager(source),new AnnotationTransactionAttributeSource()));
        return (LegacyCsvService)factory.getProxy();
    }
    private void verifyBytes(javax.sql.DataSource source,String manifest) throws Exception {
        var target=new LegacyCsvService(new JdbcLegacyCsvRows(source),new JdbcDatasetRevisionProvider(JdbcClient.create(source)));
        try {
            var mvc=MockMvcBuilders.standaloneSetup(new LegacyCsvController(proxy(target,source))).build();
            var cases=new tools.jackson.databind.json.JsonMapper().readTree(Files.readString(output.resolve(manifest))).path("cases");
            for(var item:cases) {
                var request=mvc.perform(get("/api/v1/legacy-exports/"+item.path("kind").asString()+".csv").param("platform",item.path("platform").asString())).andReturn();
                assertThat(request.getResponse().getStatus()).withFailMessage("%s: %s",item.path("file").asString(),request.getResponse().getContentAsString()).isEqualTo(200);
                var response=mvc.perform(asyncDispatch(request)).andReturn().getResponse();
                assertThat(response.getContentAsByteArray()).as(item.path("file").asString()).isEqualTo(Files.readAllBytes(output.resolve(item.path("file").asString())));
                assertThat(response.getHeader("Content-Disposition")).isEqualTo(item.path("disposition").asString());
                assertThat(response.getHeader("Content-Type")).isEqualTo(item.path("contentType").asString());
            }
        } finally {target.close();}
    }
}
