package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Types;
import java.time.OffsetDateTime;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;
import org.mranked.query.domain.ActivityRatingQuery;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class ActivityRatingPostgresIntegrationTest {
    private static final OffsetDateTime AS_OF = OffsetDateTime.parse("2026-09-03T12:00:00Z");

    @Test
    void legacyActivityMetricsSortingAliasesAndTopPostsMatchOnRealPostgres() throws Exception {
        String url = requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL");
        String username = requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME");
        String password = requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD");
        try (Connection connection = DriverManager.getConnection(url, username, password)) {
            connection.setAutoCommit(false);
            try {
                JdbcClient fixture = JdbcClient.create(new SingleConnectionDataSource(connection, true));
                // The shared disposable database can contain other rehearsal fixtures. Hide them
                // only inside this transaction so ordering assertions stay deterministic; rollback
                // restores every pre-existing account unchanged.
                fixture.sql("UPDATE catalog.platform_account SET enabled = false").update();
                long seed = Math.floorMod(UUID.randomUUID().getLeastSignificantBits(), 900_000_000L)
                        + 8_000_000_000L;
                long revision = insertRevision(fixture);

                UUID tgInstitution = UUID.randomUUID();
                UUID tgAccount = UUID.randomUUID();
                UUID emptyTgInstitution = UUID.randomUUID();
                UUID emptyTgAccount = UUID.randomUUID();
                UUID tgRun = insertRun(fixture, Platform.TELEGRAM);
                insertInstitution(fixture, tgInstitution, seed + 1, "Telegram University", "TGU");
                insertInstitution(fixture, emptyTgInstitution, seed + 2, "Empty University", "EU");
                insertAccount(fixture, tgAccount, tgInstitution, Platform.TELEGRAM,
                        seed + 11, "channels", "alpha", "Alpha channel");
                insertAccount(fixture, emptyTgAccount, emptyTgInstitution, Platform.TELEGRAM,
                        seed + 12, "channels", "zero", "Zero channel");
                insertSubscriber(fixture, tgAccount, tgRun, 100L, "tg-alpha");
                UUID tgPost = insertPublication(fixture, revision, tgAccount, tgInstitution,
                        Platform.TELEGRAM, seed + 101, "posts", "101", false,
                        200L, 10L, null, null, 101, 101, "{}");
                insertPublication(fixture, revision, tgAccount, tgInstitution,
                        Platform.TELEGRAM, seed + 102, "posts", "102", true,
                        300L, 999L, null, null, 102, 99, "{}");

                UUID vkInstitution = UUID.randomUUID();
                UUID vkAccount = UUID.randomUUID();
                UUID nullRateInstitution = UUID.randomUUID();
                UUID nullRateAccount = UUID.randomUUID();
                UUID vkRun = insertRun(fixture, Platform.VK);
                insertInstitution(fixture, vkInstitution, seed + 3, "VK University", "VKU");
                insertInstitution(fixture, nullRateInstitution, seed + 4, "Zero Views", "ZV");
                insertAccount(fixture, vkAccount, vkInstitution, Platform.VK,
                        seed + 13, "platform_accounts", "vk-alpha", "VK alpha");
                insertAccount(fixture, nullRateAccount, nullRateInstitution, Platform.VK,
                        seed + 14, "platform_accounts", "vk-zero", "VK zero");
                insertSubscriber(fixture, vkAccount, vkRun, 100L, "vk-alpha");
                insertPublication(fixture, revision, vkAccount, vkInstitution,
                        Platform.VK, seed + 201, "platform_posts", "wall-201", false,
                        100L, 10L, 2L, 3L, 201, 201,
                        "{\"legacy_is_joint\":true,\"legacy_additional_author_count\":2}");
                insertPublication(fixture, revision, vkAccount, vkInstitution,
                        Platform.VK, seed + 202, "platform_posts", "wall-202", false,
                        100L, null, null, null, 202, null,
                        "{\"joint_post\":true,\"additional_author_count\":3}");
                insertPublication(fixture, revision, nullRateAccount, nullRateInstitution,
                        Platform.VK, seed + 203, "platform_posts", "wall-203", false,
                        0L, 5L, null, 1L, 203, 203, "{}");

                UUID rutubeInstitution = UUID.randomUUID();
                UUID rutubeAccount = UUID.randomUUID();
                insertInstitution(fixture, rutubeInstitution, seed + 5, "Rutube University", "RTU");
                insertAccount(fixture, rutubeAccount, rutubeInstitution, Platform.RUTUBE,
                        seed + 15, "platform_accounts", "rutube-alpha", "Rutube alpha");
                insertPublication(fixture, revision, rutubeAccount, rutubeInstitution,
                        Platform.RUTUBE, seed + 301, "platform_posts", "video-301", false,
                        400L, null, null, null, 301, null, "{}");

                JdbcProjectionQueryRepository repository = new JdbcProjectionQueryRepository(fixture);
                var telegram = repository.findActivityRating(query(
                        Platform.TELEGRAM, "engagement", "desc", "reactions", "desc"
                ), 1, revision);
                assertThat(telegram.entities()).singleElement().satisfies(row -> {
                    assertThat(row.legacyId()).isEqualTo(seed + 11);
                    assertThat(row.publicationCount()).isEqualTo(2);
                    assertThat(row.averageReactions()).isEqualByComparingTo("5");
                    assertThat(row.totalReactions()).isEqualTo(10);
                    assertThat(row.engagementRate()).isEqualByComparingTo("5");
                    assertThat(row.subscriberCount()).isEqualTo(100);
                });
                assertThat(telegram.entitiesTruncated()).isTrue();
                assertThat(telegram.publications()).hasSize(2);
                assertThat(telegram.publications().getFirst().publicationId()).isEqualTo(tgPost);
                assertThat(telegram.publications().getFirst().subscriberShare())
                        .isEqualByComparingTo("10");
                assertThat(telegram.publications().getFirst().viewShare())
                        .isEqualByComparingTo("5");
                assertThat(telegram.publications().getLast().reactions()).isNull();
                assertThat(telegram.publications().getLast().deletedAt()).isNotNull();

                var telegramAscending = repository.findActivityRating(query(
                        Platform.TELEGRAM, "engagement", "asc", "reactions", "asc"
                ), 10, revision);
                assertThat(telegramAscending.entities()).extracting(row -> row.legacyId())
                        .containsExactly(seed + 12, seed + 11);

                var vk = repository.findActivityRating(query(
                        Platform.VK, "engagement", "asc", "view_share", "asc"
                ), 10, revision);
                assertThat(vk.entities()).hasSize(2);
                assertThat(vk.entities().getFirst().legacyId()).isEqualTo(seed + 3);
                assertThat(vk.entities().getFirst()).satisfies(row -> {
                    assertThat(row.publicationCount()).isEqualTo(2);
                    assertThat(row.averageReactions()).isEqualByComparingTo("10");
                    assertThat(row.averageViews()).isEqualByComparingTo("100");
                    assertThat(row.totalReactions()).isEqualTo(10);
                    assertThat(row.totalViews()).isEqualTo(200);
                    assertThat(row.totalComments()).isEqualTo(2);
                    assertThat(row.totalShares()).isEqualTo(3);
                    assertThat(row.totalInteractions()).isEqualTo(15);
                    assertThat(row.engagementRate()).isEqualByComparingTo("7.5");
                });
                assertThat(vk.entities().getLast().engagementRate()).isNull();
                assertThat(vk.publications()).hasSize(3);
                assertThat(vk.publications().getFirst().viewShare()).isEqualByComparingTo("15");
                assertThat(vk.publications().get(1).viewShare()).isNull();
                assertThat(vk.publications().getLast().viewShare()).isNull();
                assertThat(vk.publications().getFirst().joint()).isTrue();
                assertThat(vk.publications().getFirst().additionalAuthorCount()).isEqualTo(2);
                assertThat(vk.publications().get(1).joint()).isTrue();
                assertThat(vk.publications().get(1).additionalAuthorCount()).isEqualTo(3);

                var rutube = repository.findActivityRating(query(
                        Platform.RUTUBE, "views", "desc", "views", "desc"
                ), 10, revision);
                assertThat(rutube.entities()).singleElement().satisfies(row -> {
                    assertThat(row.averageViews()).isEqualByComparingTo("400");
                    assertThat(row.totalViews()).isEqualTo(400);
                    assertThat(row.publicationCount()).isEqualTo(1);
                });
                assertThat(rutube.publications()).singleElement()
                        .satisfies(row -> assertThat(row.views()).isEqualTo(400));
            } finally {
                connection.rollback();
            }
        }
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "MRANKED_QUERY_TEST_PASSWORD", matches = ".+")
    void apiReadCanExecuteRatingWithoutReceivingPublicationSnapshotAccess() {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL"),
                "api_read",
                requiredEnvironment("MRANKED_QUERY_TEST_PASSWORD")
        );
        dataSource.setDriverClassName("org.postgresql.Driver");
        JdbcClient apiRead = JdbcClient.create(dataSource);
        long revision = apiRead.sql(
                        "SELECT coalesce(max(id), 0)::bigint FROM analytics.dataset_revision"
                )
                .query(Long.class)
                .single();
        JdbcProjectionQueryRepository repository = new JdbcProjectionQueryRepository(apiRead);

        assertThat(repository.findActivityRating(query(
                Platform.TELEGRAM, "engagement", "desc", "view_share", "desc"
        ), 10, revision)).isNotNull();
        assertThat(repository.findActivityRating(query(
                Platform.VK, "engagement", "desc", "view_share", "desc"
        ), 10, revision)).isNotNull();
        assertThatThrownBy(() -> apiRead.sql(
                "SELECT count(*) FROM ingest.publication_metric_snapshot"
        ).query(Long.class).single()).isInstanceOf(DataAccessException.class);
    }

    private static ActivityRatingQuery query(
            Platform platform,
            String entitySort,
            String entityDirection,
            String postSort,
            String postDirection
    ) {
        return ActivityRatingQuery.normalized(
                platform, PeriodKey.ONE_DAY,
                entitySort, entityDirection, postSort, postDirection
        );
    }

    private static long insertRevision(JdbcClient jdbc) {
        return jdbc.sql("""
                INSERT INTO analytics.dataset_revision (
                    committed_at, cause, correlation_id, metadata
                ) VALUES (:asOf, 'migration', :correlationId, '{"rating_it":true}'::jsonb)
                RETURNING id
                """)
                .param("asOf", AS_OF)
                .param("correlationId", UUID.randomUUID())
                .query(Long.class)
                .single();
    }

    private static UUID insertRun(JdbcClient jdbc, Platform platform) {
        UUID runId = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO ingest.collection_run (
                    id, platform, partition_key, collector_version, started_at,
                    completed_at, status, account_count, error_count, correlation_id
                ) VALUES (
                    :id, CAST(:platform AS catalog.platform_code), :partitionKey, 'rating-it',
                    :startedAt, :completedAt, 'succeeded', 1, 0, :correlationId
                )
                """)
                .param("id", runId)
                .param("platform", platform.databaseValue())
                .param("partitionKey", "rating-it-" + runId)
                .param("startedAt", AS_OF.minusMinutes(20))
                .param("completedAt", AS_OF.minusMinutes(10))
                .param("correlationId", UUID.randomUUID())
                .update();
        return runId;
    }

    private static void insertInstitution(
            JdbcClient jdbc, UUID id, long legacyId, String name, String shortName
    ) {
        jdbc.sql("""
                INSERT INTO catalog.institution (id, canonical_name, short_name)
                VALUES (:id, :name, :shortName)
                """)
                .param("id", id).param("name", name).param("shortName", shortName).update();
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES ('institutions', :legacyId, :id, '/institutions/' || :legacyId)
                """)
                .param("legacyId", legacyId).param("id", id).update();
    }

    private static void insertAccount(
            JdbcClient jdbc,
            UUID id,
            UUID institutionId,
            Platform platform,
            long legacyId,
            String aliasType,
            String username,
            String title
    ) {
        jdbc.sql("""
                INSERT INTO catalog.platform_account (
                    id, institution_id, platform, canonical_external_id,
                    current_username, current_title, current_url, access_mode, enabled
                ) VALUES (
                    :id, :institutionId, CAST(:platform AS catalog.platform_code), :externalId,
                    :username, :title, :url, 'public_web', true
                )
                """)
                .param("id", id).param("institutionId", institutionId)
                .param("platform", platform.databaseValue()).param("externalId", "it-" + id)
                .param("username", username).param("title", title)
                .param("url", "https://example.test/" + username).update();
        String routePrefix = "channels".equals(aliasType) ? "/channels/" : "/platform-accounts/";
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES (:aliasType, :legacyId, :id, :route)
                """)
                .param("aliasType", aliasType).param("legacyId", legacyId).param("id", id)
                .param("route", routePrefix + legacyId).update();
    }

    private static void insertSubscriber(
            JdbcClient jdbc, UUID accountId, UUID runId, Long count, String fingerprint
    ) {
        jdbc.sql("""
                INSERT INTO ingest.account_metric_snapshot (
                    platform_account_id, collection_run_id, observed_at, subscriber_count,
                    quality, source_fingerprint, collected_at, created_at
                ) VALUES (
                    :accountId, :runId, :observedAt, :count, 'exact', :fingerprint,
                    :collectedAt, :createdAt
                )
                """)
                .param("accountId", accountId).param("runId", runId)
                .param("observedAt", AS_OF.minusMinutes(5))
                .param("count", count, Types.BIGINT).param("fingerprint", fingerprint)
                .param("collectedAt", AS_OF.minusMinutes(4))
                .param("createdAt", AS_OF.minusMinutes(4)).update();
    }

    private static UUID insertPublication(
            JdbcClient jdbc,
            long revision,
            UUID accountId,
            UUID institutionId,
            Platform platform,
            long legacyId,
            String aliasType,
            String externalId,
            boolean deleted,
            Long views,
            Long reactions,
            Long comments,
            Long shares,
            long latestRef,
            Integer reactionRef,
            String qualityFlags
    ) {
        UUID publicationId = UUID.randomUUID();
        OffsetDateTime publishedAt = AS_OF.minusHours(2);
        jdbc.sql("""
                INSERT INTO ingest.publication (
                    id, primary_account_id, published_at, discovered_at, publication_type,
                    is_repost, history_completeness, quality_flags, deleted_at, created_at
                ) VALUES (
                    :id, :accountId, :publishedAt, :discoveredAt, 'post', false, 'complete',
                    CAST(:qualityFlags AS jsonb), :deletedAt, :createdAt
                )
                """)
                .param("id", publicationId).param("accountId", accountId)
                .param("publishedAt", publishedAt).param("discoveredAt", publishedAt.plusMinutes(1))
                .param("qualityFlags", qualityFlags)
                .param("deletedAt", deleted ? AS_OF.minusMinutes(1) : null, Types.TIMESTAMP_WITH_TIMEZONE)
                .param("createdAt", publishedAt.plusMinutes(1)).update();
        jdbc.sql("""
                INSERT INTO ingest.publication_identity (
                    publication_id, platform_account_id, external_id, role, public_url
                ) VALUES (:publicationId, :accountId, :externalId, 'primary', :url)
                """)
                .param("publicationId", publicationId).param("accountId", accountId)
                .param("externalId", externalId)
                .param("url", "https://example.test/publication/" + externalId).update();
        String routePrefix = "posts".equals(aliasType) ? "/posts/" : "/platform-posts/";
        jdbc.sql("""
                INSERT INTO catalog.legacy_entity_alias (
                    entity_type, legacy_id, target_uuid, legacy_route
                ) VALUES (:aliasType, :legacyId, :publicationId, :route)
                """)
                .param("aliasType", aliasType).param("legacyId", legacyId)
                .param("publicationId", publicationId).param("route", routePrefix + legacyId)
                .update();
        String refs = refs(latestRef, views == null ? null : latestRef, reactionRef,
                comments == null ? null : latestRef, shares == null ? null : latestRef);
        jdbc.sql("""
                INSERT INTO analytics.publication_latest (
                    publication_id, institution_id, platform_account_id, platform, observed_at,
                    views_count, views_observed_at, views_quality,
                    reactions_count, reactions_observed_at, reactions_quality,
                    comments_count, comments_observed_at, comments_quality,
                    shares_count, shares_observed_at, shares_quality,
                    quality, interval_uncertain, synthetic, history_completeness,
                    source_snapshot_refs, dataset_revision_id, refreshed_at
                ) VALUES (
                    :publicationId, :institutionId, :accountId,
                    CAST(:platform AS catalog.platform_code), :observedAt,
                    :views, CASE WHEN CAST(:views AS bigint) IS NULL THEN NULL ELSE :observedAt END,
                    CASE WHEN CAST(:views AS bigint) IS NULL THEN NULL ELSE 'exact'::ingest.observation_quality END,
                    :reactions, CASE WHEN CAST(:reactions AS bigint) IS NULL THEN NULL ELSE :observedAt END,
                    CASE WHEN CAST(:reactions AS bigint) IS NULL THEN NULL ELSE 'exact'::ingest.observation_quality END,
                    :comments, CASE WHEN CAST(:comments AS bigint) IS NULL THEN NULL ELSE :observedAt END,
                    CASE WHEN CAST(:comments AS bigint) IS NULL THEN NULL ELSE 'exact'::ingest.observation_quality END,
                    :shares, CASE WHEN CAST(:shares AS bigint) IS NULL THEN NULL ELSE :observedAt END,
                    CASE WHEN CAST(:shares AS bigint) IS NULL THEN NULL ELSE 'exact'::ingest.observation_quality END,
                    'exact', false, false, 'complete', CAST(:refs AS jsonb), :revision, :observedAt
                )
                """)
                .param("publicationId", publicationId).param("institutionId", institutionId)
                .param("accountId", accountId).param("platform", platform.databaseValue())
                .param("observedAt", AS_OF.minusMinutes(2))
                .param("views", views, Types.BIGINT)
                .param("reactions", reactions, Types.BIGINT)
                .param("comments", comments, Types.BIGINT)
                .param("shares", shares, Types.BIGINT)
                .param("refs", refs).param("revision", revision).update();
        return publicationId;
    }

    private static String refs(
            long latest, Long views, Integer reactions, Long comments, Long shares
    ) {
        StringBuilder json = new StringBuilder("{\"latest\":").append(latest);
        if (views != null) json.append(",\"views\":").append(views);
        if (reactions != null) json.append(",\"reactions\":").append(reactions);
        if (comments != null) json.append(",\"comments\":").append(comments);
        if (shares != null) json.append(",\"shares\":").append(shares);
        return json.append('}').toString();
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
