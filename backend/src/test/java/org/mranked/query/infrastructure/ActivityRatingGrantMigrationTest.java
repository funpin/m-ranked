package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class ActivityRatingGrantMigrationTest {
    @Test
    void apiReadGetsOnlyTheSourceColumnsNeededByTheActivityReadModel() throws Exception {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        String schema = Files.readString(
                backend.resolve("src/main/resources/db/final-schema.sql")
        );

        assertThat(schema)
                .contains("GRANT SELECT(external_id) ON TABLE ingest.publication_identity TO api_read;")
                .contains("GRANT SELECT(public_url) ON TABLE ingest.publication_identity TO api_read;")
                .contains("GRANT SELECT(role) ON TABLE ingest.publication_identity TO api_read;")
                .doesNotContain("GRANT SELECT ON TABLE ingest.account_metric_snapshot TO api_read;")
                .doesNotContain("GRANT SELECT ON TABLE ingest.publication_metric_snapshot TO api_read;");
    }
}
