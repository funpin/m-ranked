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
import org.mranked.query.domain.OverviewQuery;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class OverviewPostgresIntegrationTest {
    private static final OffsetDateTime AS_OF = OffsetDateTime.parse("2026-09-03T12:00:00Z");

    @Test
    void globalSortCursorSearchAndNestedAccountsExecuteOnRealPostgres() throws Exception {
        try (Connection connection = DriverManager.getConnection(
                requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD")
        )) {
            connection.setAutoCommit(false);
            try {
                JdbcClient jdbc = JdbcClient.create(new SingleConnectionDataSource(connection, true));
                jdbc.sql("DELETE FROM analytics.legacy_overview_card").update();
                jdbc.sql("DELETE FROM analytics.legacy_overview_account").update();

                long seed = Math.floorMod(UUID.randomUUID().getLeastSignificantBits(), 800_000_000L)
                        + 8_800_000_000L;
                long revision = jdbc.sql("""
                        INSERT INTO analytics.dataset_revision (
                            committed_at, cause, correlation_id, metadata
                        ) VALUES (:asOf, 'analytics', :correlationId, '{"overview_it":true}')
                        RETURNING id
                        """)
                        .param("asOf", AS_OF)
                        .param("correlationId", UUID.randomUUID())
                        .query(Long.class).single();

                UUID alpha = insertInstitution(jdbc, seed + 1, "Альфа университет", "Альфа");
                UUID beta = insertInstitution(jdbc, seed + 2, "Бета университет", "Бета");
                UUID fir = insertInstitution(jdbc, seed + 3, "Ёлка университет", "Ёлка");
                UUID missing = insertInstitution(jdbc, seed + 4, "Нет рейтинга", "Нет рейтинга");
                UUID alphaAccount = insertAccount(jdbc, alpha, "alpha-overview-" + seed);

                insertCard(jdbc, revision, alpha, seed + 1, "Альфа университет", "альфа университет", 2, 4, 2);
                insertCard(jdbc, revision, beta, seed + 2, "Бета университет", "бета университет", 10, 1, 1);
                insertCard(jdbc, revision, fir, seed + 3, "Ёлка университет", "елка университет", 5, 0, 0);
                insertCard(jdbc, revision, missing, seed + 4, "Нет рейтинга", "нет рейтинга", null, 0, 0);
                insertTelegramCard(jdbc, revision, alpha, alphaAccount, seed + 1, seed + 11);
                insertOverviewAccount(jdbc, revision, "all", alpha, alphaAccount, seed + 11);
                insertOverviewAccount(jdbc, revision, "telegram", alphaAccount, alphaAccount, seed + 11);

                JdbcProjectionQueryRepository repository = new JdbcProjectionQueryRepository(jdbc);
                OverviewQuery descending = OverviewQuery.normalized(
                        Platform.ALL, PeriodKey.ONE_DAY, "", "m_rating", "desc"
                );
                var firstPage = repository.findOverview(descending, 2, null, revision);
                assertThat(firstPage).extracting(card -> card.institution().legacyId())
                        .containsExactly(seed + 2, seed + 3);

                var secondPage = repository.findOverview(
                        descending, 3, firstPage.getLast().entityId(), revision
                );
                assertThat(secondPage).extracting(card -> card.institution().legacyId())
                        .containsExactly(seed + 1, seed + 4);
                assertThat(secondPage.getFirst()).satisfies(card -> {
                    assertThat(card.accountCount()).isEqualTo(4);
                    assertThat(card.reactions().total()).isNull();
                    assertThat(card.accounts()).singleElement().satisfies(account -> {
                        assertThat(account.id()).isEqualTo(alphaAccount);
                        assertThat(account.legacyId()).isEqualTo(seed + 11);
                        assertThat(account.subscriberCount()).isEqualTo(125);
                    });
                });

                OverviewQuery ascending = OverviewQuery.normalized(
                        Platform.ALL, PeriodKey.ONE_DAY, "", "m_rating", "asc"
                );
                assertThat(repository.findOverview(ascending, 10, null, revision))
                        .extracting(card -> card.institution().legacyId())
                        .containsExactly(seed + 1, seed + 3, seed + 2, seed + 4);

                OverviewQuery normalizedSearch = OverviewQuery.normalized(
                        Platform.ALL, PeriodKey.ONE_DAY, "  ЁЛКА  ", "name", "asc"
                );
                assertThat(repository.findOverview(normalizedSearch, 10, null, revision))
                        .singleElement()
                        .satisfies(card -> assertThat(card.institution().legacyId())
                                .isEqualTo(seed + 3));

                OverviewQuery telegram = OverviewQuery.normalized(
                        Platform.TELEGRAM, PeriodKey.ONE_DAY, "", "reactions", "desc"
                );
                assertThat(repository.findOverview(telegram, 10, null, revision))
                        .singleElement().satisfies(card -> {
                            assertThat(card.entityId()).isEqualTo(alphaAccount);
                            assertThat(card.legacyId()).isEqualTo(seed + 11);
                            assertThat(card.reactions().total()).isEqualByComparingTo("10");
                            assertThat(card.reactions().median()).isEqualByComparingTo("10");
                        });

                UUID foreignCursor = UUID.randomUUID();
                assertThat(repository.findOverview(descending, 10, foreignCursor, revision))
                        .isEmpty();
            } finally {
                connection.rollback();
            }
        }
    }

    private static UUID insertInstitution(
            JdbcClient jdbc, long legacyId, String name, String shortName
    ) {
        UUID id = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO catalog.institution (id, canonical_name, short_name)
                VALUES (:id, :name, :shortName)
                """)
                .param("id", id).param("name", name).param("shortName", shortName).update();
        return id;
    }

    private static UUID insertAccount(JdbcClient jdbc, UUID institutionId, String externalId) {
        UUID id = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO catalog.platform_account (
                    id, institution_id, platform, canonical_external_id,
                    current_username, current_title, current_url, access_mode, enabled
                ) VALUES (
                    :id, :institutionId, 'telegram', :externalId,
                    'alpha', 'Alpha account', 'https://example.test/alpha', 'public_web', true
                )
                """)
                .param("id", id).param("institutionId", institutionId)
                .param("externalId", externalId).update();
        return id;
    }

    private static void insertCard(
            JdbcClient jdbc,
            long revision,
            UUID institutionId,
            long legacyId,
            String name,
            String searchText,
            Integer rank,
            int accountCount,
            int connectedCount
    ) {
        jdbc.sql("""
                INSERT INTO analytics.legacy_overview_card (
                    dataset_revision_id, platform, period_key, entity_type, entity_id,
                    legacy_id, legacy_route, institution_id, institution_legacy_id,
                    canonical_name, short_name, sort_name, search_text,
                    account_count, enabled_account_count, connected_platform_count,
                    status_code, rating_rank, as_of
                ) VALUES (
                    :revision, 'all', '1d', 'institutions', :institutionId,
                    :legacyId, :route, :institutionId, :legacyId,
                    :name, :name, :searchText, :searchText,
                    :accountCount, :accountCount, :connectedCount,
                    CASE WHEN :accountCount = 0 THEN 'no_account' ELSE 'connected' END,
                    :rank, :asOf
                )
                """)
                .param("revision", revision).param("institutionId", institutionId)
                .param("legacyId", legacyId).param("route", "/institutions/" + legacyId)
                .param("name", name).param("searchText", searchText)
                .param("accountCount", accountCount).param("connectedCount", connectedCount)
                .param("rank", rank, java.sql.Types.INTEGER)
                .param("asOf", AS_OF).update();
    }

    private static void insertTelegramCard(
            JdbcClient jdbc,
            long revision,
            UUID institutionId,
            UUID accountId,
            long institutionLegacyId,
            long channelLegacyId
    ) {
        jdbc.sql("""
                INSERT INTO analytics.legacy_overview_card (
                    dataset_revision_id, platform, period_key, entity_type, entity_id,
                    legacy_id, legacy_route, institution_id, institution_legacy_id,
                    canonical_name, short_name, sort_name, search_text,
                    account_count, enabled_account_count, connected_platform_count,
                    subscriber_count, status_code, total_publication_count,
                    activity_publication_count, new_publication_count,
                    total_reactions, median_reactions, as_of
                ) VALUES (
                    :revision, 'telegram', '1d', 'channels', :accountId,
                    :channelLegacyId, :route, :institutionId, :institutionLegacyId,
                    'Альфа университет', 'Альфа', 'альфа', 'альфа университет',
                    1, 1, 1, 125, 'polling', 1, 1, 1, 10, 10, :asOf
                )
                """)
                .param("revision", revision).param("accountId", accountId)
                .param("channelLegacyId", channelLegacyId)
                .param("route", "/channels/" + channelLegacyId)
                .param("institutionId", institutionId)
                .param("institutionLegacyId", institutionLegacyId)
                .param("asOf", AS_OF).update();
    }

    private static void insertOverviewAccount(
            JdbcClient jdbc,
            long revision,
            String platform,
            UUID entityId,
            UUID accountId,
            long legacyId
    ) {
        jdbc.sql("""
                INSERT INTO analytics.legacy_overview_account (
                    dataset_revision_id, platform, entity_id, position, account_id,
                    legacy_id, legacy_route, account_platform, canonical_external_id,
                    username, title, url, access_mode, enabled, subscriber_count
                ) VALUES (
                    :revision, CAST(:platform AS analytics.platform_scope), :entityId, 1, :accountId,
                    :legacyId, :route, 'telegram', :externalId,
                    'alpha', 'Alpha account', 'https://example.test/alpha',
                    'public_web', true, 125
                )
                """)
                .param("revision", revision).param("platform", platform)
                .param("entityId", entityId)
                .param("accountId", accountId).param("legacyId", legacyId)
                .param("route", "/channels/" + legacyId)
                .param("externalId", "overview-account-" + accountId).update();
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
