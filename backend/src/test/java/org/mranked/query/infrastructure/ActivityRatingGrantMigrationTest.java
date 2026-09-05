package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class ActivityRatingGrantMigrationTest {
    @Test
    void apiReadGetsOnlyTheSourceColumnsNeededByTheActivityReadModel() throws Exception {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        String migration = Files.readString(backend.resolve(
                "src/main/resources/db/migration/V7__activity_rating_read_grants.sql"
        ));

        assertThat(migration)
                .contains("ON ingest.account_metric_snapshot TO api_read")
                .contains("subscriber_count", "observed_at", "collected_at", "quality")
                .contains("ON ingest.publication_identity TO api_read")
                .contains("external_id", "public_url", "role")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("source_fingerprint")
                .doesNotContain("collection_run_id")
                .doesNotContain("raw_payload");
    }
}
