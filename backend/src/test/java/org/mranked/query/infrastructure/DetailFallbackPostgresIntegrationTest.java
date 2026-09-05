package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Connection;
import java.sql.DriverManager;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.catalog.domain.LegacyEntityType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class DetailFallbackPostgresIntegrationTest {
    private static final OffsetDateTime AS_OF = OffsetDateTime.parse("2026-09-03T12:00:00Z");

    @Test
    void existingEntitiesRemainVisibleWithoutPeriodMetricsOrAcceptedLatest() throws Exception {
        try (Connection connection = DriverManager.getConnection(
                requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD")
        )) {
            connection.setAutoCommit(false);
            try {
                JdbcClient jdbc = JdbcClient.create(new SingleConnectionDataSource(connection, true));
                long seed = Math.floorMod(UUID.randomUUID().getLeastSignificantBits(), 800_000_000L)
                        + 8_900_000_000L;
                long revision = insertRevision(jdbc);
                UUID institutionId = UUID.randomUUID();
                UUID accountId = UUID.randomUUID();
                UUID publicationId = UUID.randomUUID();

                insertInstitution(jdbc, institutionId, seed);
                insertAccount(jdbc, accountId, institutionId);
                insertPublication(jdbc, publicationId, accountId, seed + 1);

                JdbcProjectionQueryRepository repository = new JdbcProjectionQueryRepository(jdbc);

                assertThat(repository.findInstitution(
                        seed, Platform.VK, PeriodKey.SEVEN_DAYS, revision
                )).hasValueSatisfying(view -> {
                    assertThat(view.institution().id()).isEqualTo(institutionId);
                    assertThat(view.platform()).isEqualTo(Platform.VK);
                    assertThat(view.period()).isEqualTo(PeriodKey.SEVEN_DAYS);
                    assertThat(view.metrics().totalReactions()).isNull();
                    assertThat(view.metrics().totalViews()).isNull();
                    assertThat(view.metrics().medianReactions()).isNull();
                    assertThat(view.metrics().medianViews()).isNull();
                    assertThat(view.metrics().sampleSize()).isZero();
                    assertThat(view.metrics().coverage()).isNull();
                    assertThat(view.metrics().quality()).isNull();
                    assertThat(view.metrics().asOf()).isNull();
                    assertThat(view.metrics().datasetRevision()).isEqualTo(revision);
                });

                assertThat(repository.findPublication(
                        seed + 1, LegacyEntityType.PLATFORM_POSTS, revision
                )).hasValueSatisfying(view -> {
                    assertThat(view.publication().id()).isEqualTo(publicationId);
                    assertThat(view.publication().institutionId()).isEqualTo(institutionId);
                    assertThat(view.platform()).isEqualTo(Platform.VK);
                    assertThat(view.views().value()).isNull();
                    assertThat(view.views().observedAt()).isNull();
                    assertThat(view.views().quality()).isNull();
                    assertThat(view.reactions().value()).isNull();
                    assertThat(view.comments().value()).isNull();
                    assertThat(view.shares().value()).isNull();
                    assertThat(view.quality()).isNull();
                    assertThat(view.intervalUncertain()).isFalse();
                    assertThat(view.synthetic()).isFalse();
                    assertThat(view.historyCompleteness()).isEqualTo("incomplete");
                    assertThat(view.observedAt()).isNull();
                    assertThat(view.datasetRevision()).isEqualTo(revision);
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
                ) VALUES (:asOf, 'migration', :correlationId, '{"detail_fallback_it":true}')
                RETURNING id
                """)
                .param("asOf", AS_OF)
                .param("correlationId", UUID.randomUUID())
                .query(Long.class)
                .single();
    }

    private static void insertInstitution(JdbcClient jdbc, UUID id, long legacyId) {
        jdbc.sql("""
                INSERT INTO catalog.institution (id, canonical_name, short_name)
                VALUES (:id, 'Detail fallback university', 'DFU')
                """)
                .param("id", id)
                .update();
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES ('institutions', :legacyId, :id, '/institutions/' || :legacyId)
                """)
                .param("legacyId", legacyId)
                .param("id", id)
                .update();
    }

    private static void insertAccount(JdbcClient jdbc, UUID id, UUID institutionId) {
        jdbc.sql("""
                INSERT INTO catalog.platform_account (
                    id, institution_id, platform, canonical_external_id,
                    access_mode, enabled
                ) VALUES (:id, :institutionId, 'vk', :externalId, 'public_web', true)
                """)
                .param("id", id)
                .param("institutionId", institutionId)
                .param("externalId", "detail-fallback-" + id)
                .update();
    }

    private static void insertPublication(
            JdbcClient jdbc,
            UUID id,
            UUID accountId,
            long legacyId
    ) {
        jdbc.sql("""
                INSERT INTO ingest.publication (
                    id, primary_account_id, published_at, discovered_at,
                    publication_type, history_completeness
                ) VALUES (
                    :id, :accountId, :publishedAt, :discoveredAt, 'post', 'incomplete'
                )
                """)
                .param("id", id)
                .param("accountId", accountId)
                .param("publishedAt", AS_OF.minusHours(2))
                .param("discoveredAt", AS_OF.minusHours(1))
                .update();
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES ('platform_posts', :legacyId, :id, '/platform-posts/' || :legacyId)
                """)
                .param("legacyId", legacyId)
                .param("id", id)
                .update();
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
