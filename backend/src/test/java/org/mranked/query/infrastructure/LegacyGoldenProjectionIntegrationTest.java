package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import org.mranked.testing.FinalSchemaInstaller;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Historical SQL semantic fixtures. Actual Python formulas are checked by LegacyPeriodOraclePostgresIntegrationTest. */
@EnabledIfEnvironmentVariable(named="MRANKED_GOLDEN_TEST_POSTGRES_URL",matches=".+")
class LegacyGoldenProjectionIntegrationTest {
    private static final Path ROOT=Path.of(System.getProperty("basedir")).toAbsolutePath().getParent();
    @BeforeAll static void installFinalSchema() throws Exception {
        FinalSchemaInstaller.install(
                System.getenv("MRANKED_GOLDEN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
    }
    @Test void legacyActivityWindowAndOverviewGoldenValuesSurviveLatestMigration() throws Exception {run("period-activity-golden.sql");}
    @Test void fixedCohortMembershipMissingPointsAndSameSnapshotEngagementMatchLegacy() throws Exception {run("comparison-golden.sql");}
    private static void run(String filename) throws Exception {
        String original=Files.readString(ROOT.resolve("migration/schema").resolve(filename));
        assertThat(original).contains("RAISE EXCEPTION", "ROLLBACK;");
        // The original psql variable is unused: the oracle resolves its own unique revision by correlation ID.
        String sql=original.replaceAll("(?m)^\\\\gset[^\\n]*$",";")
                .replaceAll("(?m)^\\\\[^\\n]*$","");
        // V12/V14/V17 add history, public text and CSV state.
        sql=sql.replace("(SELECT count(*) FROM analytics.projection_state) <> 6",
                "(SELECT count(*) FROM analytics.projection_state) <> 9")
                .replace("WHERE dataset_revision_id = golden_revision_id AND status = 'ready') <> 6",
                        "WHERE dataset_revision_id = golden_revision_id AND status = 'ready') <> 9");
        // V21 fixes the historical fixture's false history_complete assumption:
        // both VK single observations are one hour old, outside the real legacy
        // default six-minute first-window-age baseline. All other assertions remain.
        if(filename.equals("period-activity-golden.sql")) {
            assertThat(sql).containsOnlyOnce("AND value = 7 AND sample_size = 1 AND coverage = 0.5");
            sql=sql.replace("AND value = 7 AND sample_size = 1 AND coverage = 0.5",
                    "AND value IS NULL AND sample_size = 0 AND coverage = 0");
            // V23 separates channel and institutional ranks. Preserve the
            // original rank=7 assertion by supplying its own channel fact,
            // instead of restoring the incorrect institutional inheritance.
            String revisionAnchor="INSERT INTO analytics.dataset_revision (";
            assertThat(sql).containsOnlyOnce(revisionAnchor);
            sql=sql.replace(revisionAnchor,"""
                INSERT INTO rating.official_account_rating_observation
                    (platform_account_id,period,rank,score,source_url,source_hash,fetched_at)
                VALUES ('55555555-5555-4555-8555-555555555511','2026',7,91.5,
                    'https://example.test/rating/telegram',repeat('a',64),'2026-09-03T11:40:00Z');
                """+revisionAnchor);
        }
        try(var connection=DriverManager.getConnection(System.getenv("MRANKED_GOLDEN_TEST_POSTGRES_URL"),
                System.getenv("MRANKED_ADMIN_TEST_OWNER_USERNAME"),System.getenv("MRANKED_ADMIN_TEST_OWNER_PASSWORD"));
                var statement=connection.createStatement()) {
            statement.setQueryTimeout(120);
            statement.execute(sql);
        }
    }
}
