package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.DriverManager;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mranked.testing.FinalSchemaInstaller;

/** CI provides disposable databases; this test installs the single final schema. */
@EnabledIfSystemProperty(named = "mranked.integration.required", matches = "true")
class MigrationInstallationTest {
    @Test
    void cleanInstallationCreatesFinalContract() throws Exception {
        String first = required("MRANKED_MIGRATION_TEST_URL");
        String second = required("MRANKED_SECOND_SCHEMA_TEST_URL");
        String user = required("MRANKED_MIGRATION_TEST_USER");
        String password = required("MRANKED_MIGRATION_TEST_PASSWORD");
        assertThat(first).isNotEqualTo(second);
        assertEmpty(first, user, password);
        assertEmpty(second, user, password);
        FinalSchemaInstaller.install(first, user, password);
        FinalSchemaInstaller.install(second, user, password);
        assertFinalContract(first, user, password);
        assertFinalContract(second, user, password);
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "MRANKED_REHEARSAL_INSTALL_URL", matches = ".+")
    void installAdditionalDisposableRehearsalDatabase() throws Exception {
        String url = required("MRANKED_REHEARSAL_INSTALL_URL");
        String user = required("MRANKED_MIGRATION_TEST_USER");
        String password = required("MRANKED_MIGRATION_TEST_PASSWORD");
        assertEmpty(url, user, password);
        FinalSchemaInstaller.install(url, user, password);
        assertFinalContract(url, user, password);
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "MRANKED_INTEGRITY_INSTALL_URL", matches = ".+")
    void migrateDisposableIntegrityDatabase() throws Exception {
        String url = required("MRANKED_INTEGRITY_INSTALL_URL");
        assertThat(url).matches(
                "jdbc:postgresql://(?:127\\.0\\.0\\.1|localhost):[0-9]+/mranked_observations_it_[a-z0-9]+_it");
        String user = required("MRANKED_MIGRATION_TEST_USER");
        String password = required("MRANKED_MIGRATION_TEST_PASSWORD");
        assertEmpty(url, user, password);
        FinalSchemaInstaller.install(url, user, password);
        assertFinalContract(url, user, password);
    }

    private static void assertFinalContract(String url, String user, String password)
            throws Exception {
        try (var connection = DriverManager.getConnection(url, user, password);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("""
                     SELECT contract_id,
                            to_regnamespace('flyway') IS NULL,
                            to_regnamespace('migration') IS NULL
                       FROM ops_and_admin.schema_contract
                     """)) {
            assertThat(rows.next()).isTrue();
            assertThat(rows.getString(1)).isEqualTo(FinalSchemaInstaller.CONTRACT);
            assertThat(rows.getBoolean(2)).isTrue();
            assertThat(rows.getBoolean(3)).isTrue();
            assertThat(rows.next()).isFalse();
        }
    }

    private static void assertEmpty(String url, String user, String password) throws Exception {
        try (var connection = DriverManager.getConnection(url, user, password);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("""
                     SELECT count(*)
                       FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname IN ('catalog', 'ingest', 'analytics', 'ops_and_admin')
                        AND c.relkind IN ('r', 'p')
                     """)) {
            rows.next();
            assertThat(rows.getLong(1))
                    .as("installation test requires an empty disposable database")
                    .isZero();
        }
    }

    static String required(String key) {
        String value = System.getenv(key);
        assertThat(value).as("required integration environment %s", key).isNotBlank();
        return value;
    }
}
