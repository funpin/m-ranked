package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

/** Independent original Python formulas against an actual current Flyway installation. */
@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class LegacyPeriodOraclePostgresIntegrationTest {
    @TempDir Path output;
    @ParameterizedTest @ValueSource(booleans={false,true})
    void firstAgeInsideEachWindowMatchesActualLegacyAcrossPlatformsAndPeriods(boolean upgrade) throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");URI uri=URI.create(initial.substring(5));
        assertThat(uri.getHost()).isIn("127.0.0.1","localhost","[::1]");assertThat(uri.getPath()).endsWith("_it");
        String name="mranked_period_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+name,null,null);
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                var installation=Flyway.configure().dataSource(url,owner,password).initSql("SET ROLE migration_owner")
                    .defaultSchema("flyway").locations("filesystem:"+root.resolve("backend/src/main/resources/db/migration"))
                    .cleanDisabled(true);
                if(upgrade)installation.target("20");installation.load().migrate();
                var process=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.legacy_period_oracle",
                    "--output",output.toString()).directory(root.toFile()).redirectErrorStream(true)
                    .redirectOutput(output.resolve("oracle.log").toFile());
                if(upgrade)process.command().add("--prepare-only");
                process.environment().put("MRANKED_LEGACY_CSV_DSN",new URI("postgresql",owner+":"+password,
                    uri.getHost(),uri.getPort(),"/"+name,null,null).toString());
                var oracle=process.start();assertThat(oracle.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
                assertThat(oracle.exitValue()).withFailMessage(Files.readString(output.resolve("oracle.log"))).isZero();
                if(upgrade) {
                    long previous;
                    try(var connection=DriverManager.getConnection(url,owner,password);var statement=connection.createStatement()) {
                        var row=statement.executeQuery("SELECT dataset_revision_id,total_views FROM analytics.legacy_overview_card WHERE platform='vk' AND period_key='7d' AND legacy_id=1");
                        assertThat(row.next()).isTrue();previous=row.getLong(1);assertThat(row.getLong(2)).isEqualTo(1000);
                    }
                    Flyway.configure().dataSource(url,owner,password).initSql("SET ROLE migration_owner")
                        .defaultSchema("flyway").locations("filesystem:"+root.resolve("backend/src/main/resources/db/migration"))
                        .cleanDisabled(true).load().migrate();
                    try(var connection=DriverManager.getConnection(url,owner,password);var statement=connection.createStatement()) {
                        var row=statement.executeQuery("SELECT dataset_revision_id,total_views,as_of FROM analytics.legacy_overview_card WHERE platform='vk' AND period_key='7d' AND legacy_id=1");
                        assertThat(row.next()).isTrue();assertThat(row.getLong(1)).isGreaterThan(previous);assertThat(row.getObject(2)).isNull();
                        assertThat(row.getObject(3,java.time.OffsetDateTime.class).toInstant()).isEqualTo(java.time.Instant.parse("2026-08-01T12:00:00Z"));
                    }
                    process.command().remove("--prepare-only");process.command().add("--verify-existing");
                    oracle=process.start();assertThat(oracle.waitFor(120,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
                    assertThat(oracle.exitValue()).withFailMessage(Files.readString(output.resolve("oracle.log"))).isZero();
                }
                var json=new tools.jackson.databind.json.JsonMapper().readTree(Files.readString(output.resolve("period-oracle.json")));
                assertThat(json.path("cardCases").asInt()).isEqualTo(84);assertThat(json.path("metricCases").asInt()).isEqualTo(672);
                Files.copy(output.resolve("period-oracle.json"),Path.of(System.getProperty("mranked.build.directory","target"),upgrade?"period-oracle-upgrade.json":"period-oracle.json"),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            } finally {control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)");}
        }
    }
}
