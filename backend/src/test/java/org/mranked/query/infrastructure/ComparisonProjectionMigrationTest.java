package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class ComparisonProjectionMigrationTest {
    private static String migration() throws IOException {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        return Files.readString(backend.resolve(
                "src/main/resources/db/migration/"
                        + "V6__comparison_valid_observation_hourly_projection.sql"
        ));
    }

    @Test
    void sameHourNullSnapshotCannotHideTheEarlierValidObservation() throws IOException {
        assertThat(migration())
                .contains("snapshot.views_count IS NOT NULL")
                .contains("snapshot.reactions_count IS NOT NULL")
                .contains("snapshot.comments_count IS NOT NULL")
                .contains("snapshot.shares_count IS NOT NULL")
                .contains("ratio.value IS NOT NULL")
                .contains("snapshot.collected_at <= revision_as_of")
                .contains("ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC")
                .contains("LEFT JOIN LATERAL")
                .doesNotContain("ORDER BY snapshot.age_seconds ASC");
    }

    @Test
    void ratiosAreCalculatedPerSnapshotWithLegacyPlatformCapabilities() throws IOException {
        assertThat(migration())
                .contains("WHEN target.platform = 'telegram'")
                .contains("snapshot.reactions_count::numeric * 100::numeric")
                .contains("WHEN target.platform IN ('vk', 'rutube')")
                .contains("AND snapshot.shares_count IS NULL THEN NULL")
                .contains("+ coalesce(snapshot.shares_count, 0)::numeric")
                .contains(") * 100::numeric / snapshot.views_count::numeric")
                .contains("snapshot.views_count IS NULL OR snapshot.views_count <= 0")
                .doesNotContain("migration.legacy_entity_map");
    }

    @Test
    void v6KeepsThePublisherBoundaryAndLeastPrivilegeReadModel() throws IOException {
        assertThat(migration())
                .contains("RENAME TO rebuild_core_projections_v5")
                .contains("REVOKE ALL ON FUNCTION analytics.rebuild_core_projections_v5(bigint)")
                .contains("GRANT SELECT ON analytics.comparison_publication_hourly TO api_read")
                .contains("GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)")
                .contains("'comparison_semantics_version', 2");
    }
}
