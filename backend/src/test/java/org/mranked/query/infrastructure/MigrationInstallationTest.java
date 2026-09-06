package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.sql.DriverManager;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/** CI provides two freshly created disposable databases; this test never drops a database. */
@EnabledIfSystemProperty(named = "mranked.integration.required", matches = "true")
class MigrationInstallationTest {
    @Test
    void cleanInstallationAndFrozenV8UpgradeHaveTheSameManifest() throws Exception {
        String clean = required("MRANKED_MIGRATION_TEST_URL");
        String upgrade = required("MRANKED_MIGRATION_UPGRADE_TEST_URL");
        String user = required("MRANKED_MIGRATION_TEST_USER");
        String password = required("MRANKED_MIGRATION_TEST_PASSWORD");
        assertThat(clean).isNotEqualTo(upgrade);
        assertEmpty(clean, user, password);
        assertEmpty(upgrade, user, password);
        Flyway.configure().dataSource(upgrade, user, password).defaultSchema("flyway")
                .locations("classpath:db/migration").target("8").cleanDisabled(true).load().migrate();
        seedPublishedV8(upgrade, user, password);
        // The deployed import fix is V30. Exercise the actual V29 boundary as
        // well as the original V8 upgrade path, with retained publication facts.
        Flyway.configure().dataSource(upgrade, user, password).defaultSchema("flyway")
                .locations("classpath:db/migration").target("29").cleanDisabled(true).load().migrate();
        try (var connection = DriverManager.getConnection(upgrade, user, password);
             var statement = connection.createStatement()) {
            statement.execute("""
                INSERT INTO ingest.publication(primary_account_id,published_at,discovered_at,
                    publication_type,history_completeness,synthetic_baseline_allowed)
                SELECT id,now(),now(),'v29-retained','forced_incomplete',false
                FROM catalog.platform_account WHERE canonical_external_id='upgrade-fixture'
                """);
            assertThatThrownBy(() -> statement.execute(
                    "UPDATE ingest.publication SET synthetic_baseline_allowed=true WHERE publication_type='v29-retained'"))
                    .isInstanceOf(java.sql.SQLException.class)
                    .satisfies(error -> assertThat(((java.sql.SQLException) error).getSQLState()).isEqualTo("23514"));
        }
        var cleanFlyway = flyway(clean, user, password);
        var upgradeFlyway = flyway(upgrade, user, password);
        cleanFlyway.migrate();
        upgradeFlyway.migrate();
        cleanFlyway.validate();
        upgradeFlyway.validate();
        try (var connection = DriverManager.getConnection(upgrade, user, password);
             var statement = connection.createStatement()) {
            try (var rows = statement.executeQuery("""
                    SELECT history_completeness::text,synthetic_baseline_allowed
                    FROM ingest.publication WHERE publication_type='v29-retained'
                    """)) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getString(1)).isEqualTo("forced_incomplete");
                assertThat(rows.getBoolean(2)).as("upgrade must not infer an old baseline").isFalse();
                assertThat(rows.next()).isFalse();
            }
            assertThat(statement.executeUpdate("""
                    UPDATE ingest.publication SET synthetic_baseline_allowed=true
                    WHERE publication_type='v29-retained'
                    """)).as("V30 permits the independently retained legacy baseline").isEqualTo(1);
            assertThatThrownBy(() -> statement.execute("""
                    UPDATE ingest.publication SET history_completeness='incomplete'
                    WHERE publication_type='v29-retained'
                    """))
                    .isInstanceOf(java.sql.SQLException.class)
                    .satisfies(error -> assertThat(((java.sql.SQLException) error).getSQLState()).isEqualTo("23514"));
        }
        try (var connection = DriverManager.getConnection(upgrade,user,password);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("SELECT value,quality::text FROM analytics.account_latest")) {
            assertThat(rows.next()).isTrue();
            assertThat(rows.getLong(1)).isEqualTo(123);
            assertThat(rows.getString(2)).isEqualTo("exact");
        }
        assertThat(java.util.Arrays.stream(cleanFlyway.info().applied()).map(info ->
                info.getVersion() + ":" + info.getScript() + ":" + info.getChecksum()).toList())
                .containsExactlyElementsOf(java.util.Arrays.stream(upgradeFlyway.info().applied()).map(info ->
                        info.getVersion() + ":" + info.getScript() + ":" + info.getChecksum()).toList());
    }

    @Test
    @org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable(named = "MRANKED_REHEARSAL_INSTALL_URL", matches = ".+")
    void installAdditionalDisposableRehearsalDatabase() throws Exception {
        String url = required("MRANKED_REHEARSAL_INSTALL_URL");
        String user = required("MRANKED_MIGRATION_TEST_USER");
        String password = required("MRANKED_MIGRATION_TEST_PASSWORD");
        assertEmpty(url, user, password);
        var migration = flyway(url, user, password);
        migration.migrate();
        migration.validate();
    }

    @Test
    @org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable(named = "MRANKED_REHEARSAL_UPGRADE_URL", matches = ".+")
    void upgradeExistingDisposableRehearsalDatabase() {
        String url=required("MRANKED_REHEARSAL_UPGRADE_URL");
        assertThat(url).matches("jdbc:postgresql://(?:127\\.0\\.0\\.1|localhost):[0-9]+/[a-z0-9_]+_it");
        var migration=flyway(url,required("MRANKED_MIGRATION_TEST_USER"),required("MRANKED_MIGRATION_TEST_PASSWORD"));
        assertThat(migration.info().applied()).isNotEmpty();
        // migrate validates every applied checksum while accepting pending
        // additive files; a standalone pre-validate rejects those pending files.
        migration.migrate();migration.validate();
        assertThat(migration.info().pending()).isEmpty();
    }

    @Test
    @org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable(named="MRANKED_INTEGRITY_INSTALL_URL",matches=".+")
    void migrateDisposableIntegrityDatabase() {
        String url=required("MRANKED_INTEGRITY_INSTALL_URL");
        assertThat(url).matches("jdbc:postgresql://(?:127\\.0\\.0\\.1|localhost):[0-9]+/mranked_observations_it_[a-z0-9]+_it");
        var configuration=Flyway.configure().dataSource(url,required("MRANKED_MIGRATION_TEST_USER"),required("MRANKED_MIGRATION_TEST_PASSWORD"))
            .initSql("SET ROLE migration_owner").defaultSchema("flyway").locations("classpath:db/migration").cleanDisabled(true);
        String target=required("MRANKED_INTEGRITY_INSTALL_TARGET");
        assertThat(target).isIn("8","latest");
        if(target.equals("8")) configuration.target("8");
        var migration=configuration.load();migration.migrate();migration.validate();
    }

    private static void seedPublishedV8(String url,String user,String password) throws Exception {
        try(var connection=DriverManager.getConnection(url,user,password);var statement=connection.createStatement()) {
            statement.execute("""
                DO $seed$
                DECLARE institution uuid:=gen_random_uuid(); account uuid:=gen_random_uuid(); run uuid:=gen_random_uuid(); revision bigint;
                BEGIN
                    INSERT INTO catalog.institution(id,canonical_name) VALUES (institution,'V8 upgrade fixture');
                    INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                        VALUES(account,institution,'vk','upgrade-fixture','public_web');
                    INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
                        VALUES(run,'vk','upgrade','integration',now(),'succeeded',gen_random_uuid());
                    INSERT INTO ingest.account_metric_snapshot(platform_account_id,collection_run_id,observed_at,subscriber_count,
                        quality,source_fingerprint,collected_at) VALUES(account,run,now(),123,'exact','upgrade',now());
                    INSERT INTO analytics.dataset_revision(committed_at,cause,correlation_id)
                        VALUES(now()+interval '1 second','migration',gen_random_uuid()) RETURNING id INTO revision;
                    PERFORM analytics.rebuild_core_projections(revision);
                END
                $seed$;
                """);
        }
    }

    private static Flyway flyway(String url, String user, String password) {
        return Flyway.configure().dataSource(url, user, password).defaultSchema("flyway")
                .locations("classpath:db/migration").cleanDisabled(true).load();
    }

    private static void assertEmpty(String url, String user, String password) throws Exception {
        try (var connection = DriverManager.getConnection(url, user, password);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('catalog','ingest','analytics','flyway') AND c.relkind IN ('r','p')")) {
            rows.next();
            assertThat(rows.getLong(1)).as("installation test requires an empty disposable database").isZero();
        }
    }

    static String required(String key) {
        String value = System.getenv(key);
        assertThat(value).as("required integration environment %s", key).isNotBlank();
        return value;
    }
}
