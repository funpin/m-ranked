package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

class ProjectionSchemaContractTest {
    private static String schema;

    @BeforeAll
    static void readFinalSchema() throws IOException {
        Path backend = Path.of(System.getProperty("basedir")).toAbsolutePath().normalize();
        schema = Files.readString(backend.resolve("src/main/resources/db/final-schema.sql"))
                .replace("timestamp with time zone", "timestamptz");
    }

    @Test
    void revisionAndAliasColumnsMatchTheJdbcAdapters() {
        assertThat(table("analytics.dataset_revision"))
                .contains("id bigint", "committed_at timestamptz");
        assertThat(table("analytics.projection_state"))
                .contains(
                        "projection_name text",
                        "dataset_revision_id bigint",
                        "status analytics.projection_status"
                );
        assertThat(table("catalog.legacy_entity_alias"))
                .contains("entity_type text", "legacy_id bigint", "target_uuid uuid");
        assertThat(table("catalog.institution"))
                .contains("id uuid", "canonical_name text", "short_name text");
    }

    @Test
    void periodProjectionColumnsAndAllPlatformNullabilityMatchTheQueries() {
        assertThat(table("analytics.institution_period_metrics"))
                .contains(
                        "institution_id uuid",
                        "platform catalog.platform_code,",
                        "period_key text",
                        "metric_key analytics.metric_key",
                        "aggregation analytics.aggregation_code",
                        "value numeric",
                        "sample_size integer",
                        "coverage numeric",
                        "quality ingest.observation_quality",
                        "as_of timestamptz",
                        "dataset_revision_id bigint"
                )
                .doesNotContain("platform catalog.platform_code NOT NULL");
    }

    @Test
    void publicationProjectionPreservesIndependentMetricFreshness() {
        assertThat(table("analytics.publication_latest"))
                .contains(
                        "publication_id uuid",
                        "institution_id uuid",
                        "platform catalog.platform_code",
                        "observed_at timestamptz",
                        "views_count bigint",
                        "views_observed_at timestamptz",
                        "views_quality ingest.observation_quality",
                        "reactions_count bigint",
                        "reactions_observed_at timestamptz",
                        "reactions_quality ingest.observation_quality",
                        "comments_count bigint",
                        "comments_observed_at timestamptz",
                        "comments_quality ingest.observation_quality",
                        "shares_count bigint",
                        "shares_observed_at timestamptz",
                        "shares_quality ingest.observation_quality",
                        "dataset_revision_id bigint"
                );
        assertThat(table("ingest.publication"))
                .contains("id uuid", "published_at timestamptz", "publication_type text", "deleted_at timestamptz");
    }

    @Test
    void publicLegacyUuidMappingKeepsTheMigrationSchemaOutOfApiRead() {
        assertThat(schema)
                .doesNotContain("migration.")
                .contains(
                        "GRANT SELECT ON TABLE catalog.legacy_entity_alias TO api_read;",
                        "GRANT SELECT ON TABLE catalog.platform_account TO api_read;",
                        "GRANT SELECT ON TABLE analytics.publication_hourly TO api_read;",
                        "GRANT SELECT ON TABLE analytics.comparison_cohort_member TO api_read;"
        );
        assertThat(JdbcProjectionQueryRepository.INSTITUTION_COMPARISON_SQL)
                .contains("catalog.legacy_entity_alias")
                .doesNotContain("migration.");
        assertThat(JdbcProjectionQueryRepository.CHANNEL_COMPARISON_SQL)
                .contains("catalog.legacy_entity_alias")
                .contains("analytics.comparison_publication_hourly")
                .contains("analytics.comparison_cohort_member")
                .doesNotContain("migration.");
    }

    private static String table(String qualifiedName) {
        String marker = "CREATE TABLE " + qualifiedName + " (";
        int start = schema.indexOf(marker);
        assertThat(start).as("table %s exists", qualifiedName).isGreaterThanOrEqualTo(0);
        int end = schema.indexOf("\n);", start);
        assertThat(end).as("table %s has a closing delimiter", qualifiedName).isGreaterThan(start);
        return schema.substring(start, end);
    }
}
