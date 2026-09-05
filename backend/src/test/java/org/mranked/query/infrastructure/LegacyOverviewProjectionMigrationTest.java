package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class LegacyOverviewProjectionMigrationTest {
    private static String migration() throws Exception {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        return Files.readString(backend.resolve(
                "src/main/resources/db/migration/V8__legacy_overview_projection.sql"
        ));
    }

    @Test
    void overviewIsMaterializedByThePublisherAndKeepsSixCoreStates() throws Exception {
        assertThat(migration())
                .contains("CREATE TABLE analytics.legacy_overview_card")
                .contains("CREATE TABLE analytics.legacy_overview_account")
                .contains("RENAME TO rebuild_core_projections_v6")
                .contains("base_result := analytics.rebuild_core_projections_v6")
                .contains("'legacy_overview_semantics_version', 1")
                .doesNotContain("INSERT INTO analytics.projection_state")
                .doesNotContain("UPDATE analytics.projection_state");
    }

    @Test
    void accountAndActivityFactsCannotLeakPastTheSelectedRevision() throws Exception {
        assertThat(migration())
                .contains("snapshot.observed_at <= revision_as_of")
                .contains("snapshot.collected_at <= revision_as_of")
                .contains("snapshot.quality <> 'invalid'")
                .contains("publication.created_at <= revision_as_of")
                .contains("result.completed_at > revision_as_of")
                .contains("THEN 'running'::ingest.run_status")
                .contains("snapshot.observed_at > activity_window.window_start")
                .contains("snapshot.observed_at <= activity_window.window_end")
                .contains("NOT snapshot.synthetic");
    }

    @Test
    void publicRoleReadsOnlyTheMaterializedOverview() throws Exception {
        assertThat(migration())
                .contains("GRANT SELECT ON")
                .contains("analytics.legacy_overview_card")
                .contains("analytics.legacy_overview_account")
                .contains("TO api_read, migration_bridge, maintenance")
                .doesNotContain("GRANT SELECT ON ingest.publication_metric_snapshot TO api_read");
    }
}
