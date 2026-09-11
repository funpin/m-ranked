package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class LegacyOverviewProjectionMigrationTest {
    private static String schema() throws Exception {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        return Files.readString(backend.resolve("src/main/resources/db/final-schema.sql"));
    }

    @Test
    void overviewIsMaterializedByThePublisherAndKeepsSixCoreStates() throws Exception {
        assertThat(schema())
                .contains("CREATE TABLE analytics.legacy_overview_card")
                .contains("CREATE TABLE analytics.legacy_overview_account")
                .contains("'legacy_overview_semantics_version', 1")
                .contains("analytics.rebuild_core_projections_v9");
    }

    @Test
    void accountAndActivityFactsCannotLeakPastTheSelectedRevision() throws Exception {
        assertThat(schema())
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
        assertThat(schema())
                .contains("GRANT SELECT ON TABLE analytics.legacy_overview_card TO api_read;")
                .contains("GRANT SELECT ON TABLE analytics.legacy_overview_account TO api_read;")
                .doesNotContain("GRANT SELECT ON ingest.publication_metric_snapshot TO api_read");
    }
}
