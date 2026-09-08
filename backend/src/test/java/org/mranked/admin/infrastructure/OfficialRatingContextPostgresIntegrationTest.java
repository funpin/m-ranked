package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.*;
import java.nio.file.Path;
import java.nio.file.Files;
import java.net.URI;
import java.sql.DriverManager;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mranked.testing.FinalSchemaInstaller;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.json.JsonMapper;

@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class OfficialRatingContextPostgresIntegrationTest {
    @TempDir Path output;
    @Test
    void independentLegacyInstitutionAndChannelRanksAndImportStatusRemainDistinct() throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");var base=URI.create(initial.substring(5));
        assertThat(base.getHost()).isIn("127.0.0.1","localhost");assertThat(base.getPath()).endsWith("_it");
        String name="mranked_official_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:postgresql://"+base.getHost()+":"+base.getPort()+"/"+name;
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                FinalSchemaInstaller.install(url, owner, password);
                Path oracle=output.resolve("oracle.json");
                var builder=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.official_context_fixture",
                    "--database",output.resolve("source.sqlite").toString(),"--oracle",oracle.toString()).directory(root.toFile()).redirectErrorStream(true);
                builder.environment().put("BRIDGE_DATABASE_URL","host="+base.getHost()+" port="+base.getPort()+" dbname="+name+" user=migration_bridge password="+System.getenv("MRANKED_LEGACY_CSV_BRIDGE_PASSWORD"));
                var process=builder.start();String log=new String(process.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
                assertThat(process.waitFor()).as(log).isZero();
                var expected=new JsonMapper().readTree(Files.readString(oracle));
                var source=new DriverManagerDataSource(url,"api_write_admin",System.getenv("MRANKED_ADMIN_TEST_PASSWORD"));
                var jdbc=JdbcClient.create(source);var repository=new JdbcCatalogRepository(jdbc,new TransactionTemplate(new DataSourceTransactionManager(source)));
                var institution=repository.institutions(0,1).getFirst();
                assertThat(institution.officialRatings().get("telegram").rank()).isEqualTo(expected.path("rank").asInt());
                assertThat(institution.officialRatings().get("telegram").score().doubleValue()).isEqualTo(expected.path("score").doubleValue());
                for(var channel:expected.path("channels")) {
                    var rows=jdbc.sql("SELECT DISTINCT card.rating_rank FROM analytics.legacy_overview_card card WHERE card.platform='telegram' AND card.legacy_id=:id")
                        .param("id",channel.path("id").asLong()).query((row,index)->row.getObject(1,Integer.class)).list();
                    assertThat(rows).hasSize(1);Integer rank=rows.getFirst();
                    assertThat(rank).as("channel "+channel.path("id").asLong()).isEqualTo(channel.path("m_rating_tg_rank").isNull()?null:channel.path("m_rating_tg_rank").asInt());
                }
                var status=new JdbcCatalogStatus(jdbc,org.mranked.query.application.ProviderConfiguration.unknown(),output).status();
                assertThat(status.mRating().period()).isEqualTo(expected.path("periodState").isNull()?null:expected.path("periodState").asText());
                assertThat(status.mRating().updatedAt()).isEqualTo(expected.path("updatedState").isNull()?null:expected.path("updatedState").asText());
                assertThat(status.mRating().error()).isEqualTo(expected.path("errorPresent").asBoolean()?"legacy_source_error":null);
                var accounts=repository.institutions(0,200).stream().flatMap(item->item.accounts().stream()).toList();
                for(var original:expected.path("accounts")) {
                    var account=accounts.stream().filter(item->item.legacyId()==original.path("id").asLong()).findFirst().orElseThrow();
                    assertThat(account.legacyAccessMode()).isEqualTo(original.path("accessMode").asText());
                    assertThat(account.lastErrorCode()).isEqualTo(original.path("errorPresent").asBoolean()?"legacy_collection_error":null);
                }
            } finally { control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)"); }
        }
    }
}
