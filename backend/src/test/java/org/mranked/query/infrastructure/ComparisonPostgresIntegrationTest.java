package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Types;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.domain.ComparisonSelection;
import org.mranked.query.domain.ComparisonSelectionType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class ComparisonPostgresIntegrationTest {
    private static final OffsetDateTime AS_OF = OffsetDateTime.parse("2026-09-03T12:00:00Z");

    @Test
    void metricSpecificCohortsAndHalfMediansExecuteOnRealPostgres() throws Exception {
        try (Connection connection = DriverManager.getConnection(
                requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD")
        )) {
            connection.setAutoCommit(false);
            try {
                JdbcClient jdbc = JdbcClient.create(new SingleConnectionDataSource(connection, true));
                jdbc.sql("DELETE FROM analytics.comparison_publication_hourly").update();
                jdbc.sql("DELETE FROM analytics.comparison_cohort").update();
                jdbc.sql("DELETE FROM analytics.projection_state").update();

                long seed = Math.floorMod(UUID.randomUUID().getLeastSignificantBits(), 700_000_000L)
                        + 9_100_000_000L;
                long revision = insertRevision(jdbc);
                UUID institutionId = insertInstitution(jdbc, seed + 1);
                UUID accountId = insertAccount(jdbc, institutionId, seed + 11);
                UUID first = insertPublication(jdbc, accountId);
                UUID second = insertPublication(jdbc, accountId);
                UUID viewsOnly = insertPublication(jdbc, accountId);
                UUID cohortId = UUID.randomUUID();

                jdbc.sql("""
                        INSERT INTO analytics.comparison_cohort (
                            id, platform, horizon_seconds, as_of, filter_definition,
                            sample_size, dataset_revision_id, created_at
                        ) VALUES (
                            :id, 'telegram', 86400, :asOf,
                            '{"fixed_cohort":true,"include_partial":false,"required_start_hour":0,"required_end_hour":24}',
                            3, :revision, :asOf
                        )
                        """)
                        .param("id", cohortId).param("asOf", AS_OF)
                        .param("revision", revision).update();
                for (UUID publicationId : List.of(first, second, viewsOnly)) {
                    jdbc.sql("""
                            INSERT INTO analytics.comparison_cohort_member (
                                cohort_id, publication_id, institution_id
                            ) VALUES (:cohortId, :publicationId, :institutionId)
                            """)
                            .param("cohortId", cohortId).param("publicationId", publicationId)
                            .param("institutionId", institutionId).update();
                }
                insertPoint(jdbc, revision, first, institutionId, accountId, 0, 0L, 0L, null);
                insertPoint(jdbc, revision, first, institutionId, accountId, 1, 100L, 10L, "10");
                insertPoint(jdbc, revision, first, institutionId, accountId, 24, 200L, 20L, "10");
                insertPoint(jdbc, revision, second, institutionId, accountId, 0, 0L, 0L, null);
                insertPoint(jdbc, revision, second, institutionId, accountId, 1, 200L, 11L, "5.5");
                insertPoint(jdbc, revision, second, institutionId, accountId, 24, 400L, 21L, "5.25");
                insertPoint(jdbc, revision, viewsOnly, institutionId, accountId, 0, 0L, null, null);
                insertPoint(jdbc, revision, viewsOnly, institutionId, accountId, 1, 50L, null, null);
                insertPoint(jdbc, revision, viewsOnly, institutionId, accountId, 24, 100L, null, null);
                jdbc.sql("""
                        INSERT INTO analytics.projection_state (
                            projection_name, dataset_revision_id, status,
                            refreshed_at, row_count
                        ) VALUES ('comparison', :revision, 'ready', :asOf, 9)
                        """)
                        .param("revision", revision).param("asOf", AS_OF).update();

                JdbcProjectionQueryRepository repository = new JdbcProjectionQueryRepository(jdbc);
                var result = repository.findComparison(
                        Platform.TELEGRAM, 24, false, "reactions", "median", 1,
                        new ComparisonSelection(
                                ComparisonSelectionType.CHANNELS, List.of(seed + 11)
                        ),
                        revision
                );

                assertThat(result).isPresent();
                assertThat(result.orElseThrow()).satisfies(view -> {
                    assertThat(view.cohortId()).isEqualTo(cohortId);
                    assertThat(view.cohortSampleSize()).isEqualTo(3);
                    assertThat(view.series()).singleElement().satisfies(series -> {
                        assertThat(series.selectionId()).isEqualTo(accountId);
                        assertThat(series.selectionLegacyId()).isEqualTo(seed + 11);
                        assertThat(series.primaryCohortSize()).isEqualTo(2);
                        assertThat(series.engagementCohortSize()).isEqualTo(2);
                        assertThat(series.points()).extracting(point -> point.hourOffset())
                                .containsExactly(0, 1, 24);
                        assertThat(series.points().get(1).value()).isEqualByComparingTo("10.5");
                        assertThat(series.points().get(2).value()).isEqualByComparingTo("20.5");
                        assertThat(series.engagementPoints().getFirst().value()).isNull();
                        assertThat(series.engagementPoints().get(1).value())
                                .isEqualByComparingTo("7.75");
                        assertThat(series.engagementPoints().get(2).value())
                                .isEqualByComparingTo("7.625");
                    });
                });
            } finally {
                connection.rollback();
            }
        }
    }

    private static long insertRevision(JdbcClient jdbc) {
        return jdbc.sql("""
                INSERT INTO analytics.dataset_revision (
                    committed_at, cause, correlation_id, metadata
                ) VALUES (:asOf, 'analytics', :correlationId, '{"comparison_it":true}')
                RETURNING id
                """)
                .param("asOf", AS_OF).param("correlationId", UUID.randomUUID())
                .query(Long.class).single();
    }

    private static UUID insertInstitution(JdbcClient jdbc, long legacyId) {
        UUID id = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO catalog.institution (id, canonical_name, short_name)
                VALUES (:id, 'Comparison integration university', 'Comparison IT')
                """).param("id", id).update();
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES ('institutions', :legacyId, :id, :route)
                """)
                .param("legacyId", legacyId).param("id", id)
                .param("route", "/institutions/" + legacyId).update();
        return id;
    }

    private static UUID insertAccount(JdbcClient jdbc, UUID institutionId, long legacyId) {
        UUID id = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO catalog.platform_account (
                    id, institution_id, platform, canonical_external_id,
                    current_username, current_title, current_url, access_mode, enabled
                ) VALUES (
                    :id, :institutionId, 'telegram', :externalId,
                    'comparison_it', 'Comparison channel',
                    'https://t.me/comparison_it', 'public_web', true
                )
                """)
                .param("id", id).param("institutionId", institutionId)
                .param("externalId", "comparison-it-" + id).update();
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES ('channels', :legacyId, :id, :route)
                """)
                .param("legacyId", legacyId).param("id", id)
                .param("route", "/channels/" + legacyId).update();
        return id;
    }

    private static UUID insertPublication(JdbcClient jdbc, UUID accountId) {
        UUID id = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO ingest.publication (
                    id, primary_account_id, published_at, discovered_at,
                    publication_type, history_completeness,
                    synthetic_baseline_allowed, created_at
                ) VALUES (
                    :id, :accountId, :publishedAt, :publishedAt,
                    'post', 'complete', true, :publishedAt
                )
                """)
                .param("id", id).param("accountId", accountId)
                .param("publishedAt", AS_OF.minusDays(2)).update();
        return id;
    }

    private static void insertPoint(
            JdbcClient jdbc,
            long revision,
            UUID publicationId,
            UUID institutionId,
            UUID accountId,
            int hour,
            Long views,
            Long reactions,
            String engagement
    ) {
        jdbc.sql("""
                INSERT INTO analytics.comparison_publication_hourly (
                    publication_id, hour_offset, institution_id,
                    platform_account_id, platform,
                    views_count, views_quality, reactions_count, reactions_quality,
                    engagement_percent, engagement_quality, dataset_revision_id
                ) VALUES (
                    :publicationId, :hour, :institutionId, :accountId, 'telegram',
                    :views,
                    CASE WHEN CAST(:views AS bigint) IS NULL THEN NULL
                         ELSE 'exact'::ingest.observation_quality END,
                    :reactions,
                    CASE WHEN CAST(:reactions AS bigint) IS NULL THEN NULL
                         ELSE 'exact'::ingest.observation_quality END,
                    CAST(:engagement AS numeric),
                    CASE WHEN CAST(:engagement AS numeric) IS NULL THEN NULL
                         ELSE 'exact'::ingest.observation_quality END,
                    :revision
                )
                """)
                .param("publicationId", publicationId).param("hour", hour)
                .param("institutionId", institutionId).param("accountId", accountId)
                .param("views", views, Types.BIGINT)
                .param("reactions", reactions, Types.BIGINT)
                .param("engagement", engagement, Types.NUMERIC)
                .param("revision", revision).update();
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
