package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;
import org.mranked.testing.FinalSchemaInstaller;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

/** Original endpoint formulas must reject actual projection tampering before any rebuild. */
@EnabledIfEnvironmentVariable(named="MRANKED_EXPORT_TEST_ADMIN_URL",matches=".+")
class ProjectionReconciliationPostgresIntegrationTest {
    @TempDir Path output;
    @Test void independentEndpointOracleDetectsDerivedValuesAndMembershipTampering() throws Exception {
        String initial=System.getenv("MRANKED_EXPORT_TEST_ADMIN_URL");URI uri=URI.create(initial.substring(5));
        assertThat(uri.getHost()).isIn("127.0.0.1","localhost","[::1]");assertThat(uri.getPath()).endsWith("_it");
        String name="mranked_projection_"+UUID.randomUUID().toString().replace("-","")+"_it";
        String url="jdbc:"+new URI(uri.getScheme(),null,uri.getHost(),uri.getPort(),"/"+name,null,null);
        String owner=System.getenv("MRANKED_EXPORT_TEST_ADMIN_USERNAME"),password=System.getenv("MRANKED_EXPORT_TEST_ADMIN_PASSWORD");
        Path root=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
        try(var control=DriverManager.getConnection(initial,owner,password)) {
            control.createStatement().execute("CREATE DATABASE "+name+" OWNER migration_owner");
            try {
                FinalSchemaInstaller.install(url, owner, password);
                var process=new ProcessBuilder(org.mranked.testing.IntegrationRuntime.python(root),"-m","migration.integration.projection_oracle_fixture",
                    "--output",output.toString()).directory(root.toFile()).redirectErrorStream(true)
                    .redirectOutput(output.resolve("oracle.log").toFile());
                process.environment().put("MRANKED_LEGACY_CSV_DSN",new URI("postgresql",owner+":"+password,
                    uri.getHost(),uri.getPort(),"/"+name,null,null).toString());
                var oracle=process.start();assertThat(oracle.waitFor(180,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
                assertThat(oracle.exitValue()).withFailMessage(Files.readString(output.resolve("oracle.log"))).isZero();
                var json=new tools.jackson.databind.json.JsonMapper().readTree(Files.readString(output.resolve("projection-oracle.json")));
                assertThat(json.path("status").asString()).isEqualTo("pass");
                assertThat(json.path("tamperDetectedWithoutRebuild").size()).isEqualTo(4);
                Files.copy(output.resolve("projection-oracle.json"),Path.of(System.getProperty("mranked.build.directory","target"),"projection-oracle.json"),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            } finally {control.createStatement().execute("DROP DATABASE "+name+" WITH (FORCE)");}
        }
    }
}
