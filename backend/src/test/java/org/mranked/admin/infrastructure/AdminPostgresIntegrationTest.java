package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.mranked.admin.application.SetPlatformAccountEnabledCommand;
import org.mranked.admin.application.SetPlatformAccountEnabledOutcome;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

@EnabledIfEnvironmentVariable(named = "MRANKED_ADMIN_TEST_POSTGRES_URL", matches = ".+")
class AdminPostgresIntegrationTest {
    @Test
    void runReadsAndAccountMutationHonorGrantsAuditRevisionAndRollback() {
        String url = requiredEnvironment("MRANKED_ADMIN_TEST_POSTGRES_URL");
        DriverManagerDataSource ownerDataSource = dataSource(
                url,
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_USERNAME"),
                requiredEnvironment("MRANKED_ADMIN_TEST_OWNER_PASSWORD")
        );
        DriverManagerDataSource adminDataSource = dataSource(
                url,
                "api_write_admin",
                requiredEnvironment("MRANKED_ADMIN_TEST_PASSWORD")
        );
        JdbcClient owner = JdbcClient.create(ownerDataSource);
        JdbcClient admin = JdbcClient.create(adminDataSource);
        JdbcAdminQueryRepository queries = new JdbcAdminQueryRepository(admin);
        JdbcAdminCommandRepository commands = new JdbcAdminCommandRepository(
                admin,
                new TransactionTemplate(new DataSourceTransactionManager(adminDataSource))
        );

        UUID institutionId = UUID.randomUUID();
        UUID accountId = UUID.randomUUID();
        UUID runId = UUID.randomUUID();
        UUID initialCorrelation = UUID.randomUUID();
        UUID updateCorrelation = UUID.randomUUID();
        UUID replayCorrelation = UUID.randomUUID();
        UUID conflictCorrelation = UUID.randomUUID();
        UUID failedRebuildCorrelation = UUID.randomUUID();
        UUID restoreCorrelation = UUID.randomUUID();
        List<UUID> ownedCorrelations = List.of(
                initialCorrelation,
                updateCorrelation,
                replayCorrelation,
                conflictCorrelation,
                failedRebuildCorrelation,
                restoreCorrelation
        );
        String actor = "admin-it-" + UUID.randomUUID();
        long previousLatestRevision = owner.sql(
                        "SELECT coalesce(max(id), 0) FROM analytics.dataset_revision"
                )
                .query(Long.class)
                .single();
        boolean executeRevoked = false;

        try {
            owner.sql("""
                INSERT INTO catalog.institution (id, canonical_name, short_name)
                VALUES (:id, :name, 'AIT')
                """)
                .param("id", institutionId)
                .param("name", "Admin integration " + institutionId)
                .update();
            owner.sql("""
                    INSERT INTO catalog.platform_account (
                        id, institution_id, platform, canonical_external_id,
                        current_title, current_url, access_mode, enabled
                    )
                    VALUES (
                        :id, :institutionId, 'telegram', :externalId,
                        'Admin integration', 'https://t.me/admin_integration', 'public_web', true
                    )
                    """)
                    .param("id", accountId)
                    .param("institutionId", institutionId)
                    .param("externalId", "admin-it-" + accountId)
                    .update();
            owner.sql("""
                    INSERT INTO ingest.collection_run (
                        id, platform, partition_key, collector_version, scheduled_at,
                        started_at, completed_at, status, account_count, error_count, correlation_id
                    )
                    VALUES (
                        :id, 'telegram', :partitionKey, 'admin-it', :scheduledAt,
                        :startedAt, :completedAt, 'partial', 1, 1, :correlationId
                    )
                    """)
                    .param("id", runId)
                    .param("partitionKey", "admin-it-" + runId)
                    .param("scheduledAt", OffsetDateTime.parse("2026-09-03T09:59:00Z"))
                    .param("startedAt", OffsetDateTime.parse("2026-09-03T10:00:00Z"))
                    .param("completedAt", OffsetDateTime.parse("2026-09-03T10:01:00Z"))
                    .param("correlationId", initialCorrelation)
                    .update();
            owner.sql("""
                    INSERT INTO ingest.collection_account_result (
                        collection_run_id, platform_account_id, started_at, completed_at,
                        status, discovered_count, snapshot_count, sanitized_error_code
                    )
                    VALUES (
                        :runId, :accountId, :startedAt, :completedAt,
                        'failed', 2, 1, 'upstream_timeout'
                    )
                    """)
                    .param("runId", runId)
                    .param("accountId", accountId)
                    .param("startedAt", OffsetDateTime.parse("2026-09-03T10:00:00Z"))
                    .param("completedAt", OffsetDateTime.parse("2026-09-03T10:01:00Z"))
                    .update();
            long initialRevision = owner.sql("""
                    INSERT INTO analytics.dataset_revision (cause, correlation_id)
                    VALUES ('migration', :correlationId)
                    RETURNING id
                    """)
                    .param("correlationId", initialCorrelation)
                    .query(Long.class)
                    .single();
            owner.sql("SELECT analytics.rebuild_core_projections(:revision)")
                    .param("revision", initialRevision)
                    .query((row, rowNumber) -> row.getString(1))
                    .single();

            assertThat(queries.findCollectionJobs("telegram", "partial", 10))
                    .anySatisfy(job -> {
                        assertThat(job.jobId()).isEqualTo(runId);
                        assertThat(job.errorCount()).isEqualTo(1);
                    });
            assertThat(queries.findCollectionJob(runId, 10)).get()
                    .satisfies(job -> assertThat(job.accountResults())
                            .singleElement()
                            .satisfies(result -> assertThat(result.sanitizedErrorCode())
                                    .isEqualTo("upstream_timeout")));
            assertThat(queries.findPlatformAccount(accountId)).get()
                    .satisfies(account -> {
                        assertThat(account.platform()).isEqualTo("telegram");
                        assertThat(account.enabled()).isTrue();
                        assertThat(account.rowVersion()).isZero();
                        assertThat(account.updatedAt()).isNotNull();
                    });
            assertThat(queries.findPlatformAccount(UUID.randomUUID())).isEmpty();

            var updated = commands.setPlatformAccountEnabled(new SetPlatformAccountEnabledCommand(
                    accountId, false, 0, actor, updateCorrelation
            ));
            assertThat(updated.outcome()).isEqualTo(SetPlatformAccountEnabledOutcome.UPDATED);
            assertThat(updated.account().enabled()).isFalse();
            assertThat(updated.account().rowVersion()).isEqualTo(1);
            assertThat(queries.findPlatformAccount(accountId)).get()
                    .satisfies(account -> {
                        assertThat(account.enabled()).isFalse();
                        assertThat(account.rowVersion()).isEqualTo(1);
                    });
            assertThat(updated.datasetRevision()).isGreaterThan(initialRevision);
            assertThat(admin.sql("""
                    SELECT count(*)
                      FROM analytics.projection_state
                     WHERE dataset_revision_id = :revision
                       AND status = 'ready'
                       AND error_code IS NULL
                    """)
                    .param("revision", updated.datasetRevision())
                    .query(Integer.class)
                    .single()).isEqualTo(6);
            assertThat(admin.sql("""
                    SELECT count(*)
                      FROM ops_and_admin.outbox_event
                     WHERE dataset_revision_id = :revision
                       AND event_type = 'platform_account.enabled_changed'
                    """)
                    .param("revision", updated.datasetRevision())
                    .query(Integer.class)
                    .single()).isEqualTo(1);
            assertThat(owner.sql("""
                    SELECT count(*)
                      FROM ops_and_admin.audit_log
                     WHERE correlation_id = :correlationId
                       AND outcome = 'succeeded'
                       AND (SELECT count(*) FROM jsonb_object_keys(before_state)) = 2
                       AND (SELECT count(*) FROM jsonb_object_keys(after_state)) = 2
                       AND jsonb_exists(before_state, 'enabled')
                       AND jsonb_exists(before_state, 'rowVersion')
                       AND jsonb_exists(after_state, 'enabled')
                       AND jsonb_exists(after_state, 'rowVersion')
                    """)
                    .param("correlationId", updateCorrelation)
                    .query(Integer.class)
                    .single()).isEqualTo(1);

            var replay = commands.setPlatformAccountEnabled(new SetPlatformAccountEnabledCommand(
                    accountId, false, 0, actor, replayCorrelation
            ));
            assertThat(replay.outcome()).isEqualTo(SetPlatformAccountEnabledOutcome.IDEMPOTENT);
            assertThat(replay.datasetRevision()).isNull();

            var conflict = commands.setPlatformAccountEnabled(new SetPlatformAccountEnabledCommand(
                    accountId, true, 0, actor, conflictCorrelation
            ));
            assertThat(conflict.outcome()).isEqualTo(SetPlatformAccountEnabledOutcome.VERSION_CONFLICT);
            assertThat(owner.sql("""
                    SELECT count(*) FROM ops_and_admin.audit_log
                     WHERE correlation_id IN (:replayCorrelation, :conflictCorrelation)
                       AND outcome IN ('idempotent', 'version_conflict')
                    """)
                    .param("replayCorrelation", replayCorrelation)
                    .param("conflictCorrelation", conflictCorrelation)
                    .query(Integer.class)
                    .single()).isEqualTo(2);

            executeRevoked = true;
            owner.sql("REVOKE EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint) FROM api_write_admin")
                    .update();
            assertThatThrownBy(() -> commands.setPlatformAccountEnabled(
                    new SetPlatformAccountEnabledCommand(
                            accountId, true, 1, actor, failedRebuildCorrelation
                    )
            )).isInstanceOf(DataAccessException.class);
            assertThat(admin.sql("""
                    SELECT enabled, row_version
                      FROM catalog.platform_account
                     WHERE id = :accountId
                    """)
                    .param("accountId", accountId)
                    .query((row, rowNumber) -> row.getBoolean("enabled") + ":" + row.getLong("row_version"))
                    .single()).isEqualTo("false:1");
            assertThat(owner.sql("""
                    SELECT count(*) FROM analytics.dataset_revision
                     WHERE correlation_id = :correlationId
                    """)
                    .param("correlationId", failedRebuildCorrelation)
                    .query(Integer.class)
                    .single()).isZero();

            owner.sql("""
                    GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
                    TO api_write_admin
                    """).update();
            executeRevoked = false;

            var restored = commands.setPlatformAccountEnabled(new SetPlatformAccountEnabledCommand(
                    accountId, true, 1, actor, restoreCorrelation
            ));
            assertThat(restored.outcome()).isEqualTo(SetPlatformAccountEnabledOutcome.UPDATED);
            assertThat(restored.account().enabled()).isTrue();
            assertThat(restored.account().rowVersion()).isEqualTo(2);
        } finally {
            try {
                if (executeRevoked) {
                    owner.sql("""
                            GRANT EXECUTE ON FUNCTION analytics.rebuild_core_projections(bigint)
                            TO api_write_admin
                            """).update();
                }
            } finally {
                cleanupOwnedFixture(
                        ownerDataSource,
                        institutionId,
                        accountId,
                        runId,
                        ownedCorrelations
                );
            }
        }

        assertThat(owner.sql("""
                SELECT count(*)
                  FROM analytics.dataset_revision
                 WHERE correlation_id IN (:correlationIds)
                """)
                .param("correlationIds", ownedCorrelations)
                .query(Integer.class)
                .single()).isZero();
        assertThat(owner.sql("SELECT count(*) FROM catalog.institution WHERE id = :id")
                .param("id", institutionId)
                .query(Integer.class)
                .single()).isZero();
        assertThat(owner.sql("SELECT count(*) FROM catalog.platform_account WHERE id = :id")
                .param("id", accountId)
                .query(Integer.class)
                .single()).isZero();
        assertThat(owner.sql("SELECT count(*) FROM ingest.collection_run WHERE id = :id")
                .param("id", runId)
                .query(Integer.class)
                .single()).isZero();
        assertThat(owner.sql("SELECT coalesce(max(id), 0) FROM analytics.dataset_revision")
                .query(Long.class)
                .single()).isEqualTo(previousLatestRevision);
        assertThat(owner.sql("""
                SELECT has_function_privilege(
                    'api_write_admin',
                    'analytics.rebuild_core_projections(bigint)',
                    'EXECUTE'
                )
                """)
                .query(Boolean.class)
                .single()).isTrue();
    }

    private static void cleanupOwnedFixture(
            DriverManagerDataSource ownerDataSource,
            UUID institutionId,
            UUID accountId,
            UUID runId,
            List<UUID> ownedCorrelations
    ) {
        TransactionTemplate cleanupTransaction = new TransactionTemplate(
                new DataSourceTransactionManager(ownerDataSource)
        );
        cleanupTransaction.executeWithoutResult(status -> {
            JdbcClient owner = JdbcClient.create(ownerDataSource);
            owner.sql("LOCK TABLE analytics.dataset_revision IN SHARE ROW EXCLUSIVE MODE")
                    .update();
            boolean restoreProjections = owner.sql("""
                    SELECT count(*) > 0
                      FROM analytics.projection_state
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .query(Boolean.class)
                    .single();

            owner.sql("""
                    DELETE FROM ops_and_admin.audit_log
                     WHERE correlation_id IN (:correlationIds)
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("""
                    DELETE FROM ops_and_admin.outbox_event
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.anomaly_review
                     WHERE anomaly_event_id IN (
                         SELECT id
                           FROM analytics.anomaly_event
                          WHERE dataset_revision_id IN (
                              SELECT id
                                FROM analytics.dataset_revision
                               WHERE correlation_id IN (:correlationIds)
                          )
                            OR institution_id = :institutionId
                            OR platform_account_id = :accountId
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .param("institutionId", institutionId)
                    .param("accountId", accountId)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.anomaly_event
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                        OR institution_id = :institutionId
                        OR platform_account_id = :accountId
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .param("institutionId", institutionId)
                    .param("accountId", accountId)
                    .update();
            owner.sql("""
                    DELETE FROM rating.rating_result
                     WHERE institution_id = :institutionId
                        OR rating_run_id IN (
                            SELECT id
                              FROM rating.rating_run
                             WHERE dataset_revision_id IN (
                                 SELECT id
                                   FROM analytics.dataset_revision
                                  WHERE correlation_id IN (:correlationIds)
                             )
                        )
                    """)
                    .param("institutionId", institutionId)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("""
                    DELETE FROM rating.rating_run
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("DELETE FROM rating.population_observation WHERE institution_id = :institutionId")
                    .param("institutionId", institutionId)
                    .update();
            owner.sql("DELETE FROM rating.official_rating_observation WHERE institution_id = :institutionId")
                    .param("institutionId", institutionId)
                    .update();

            owner.sql("""
                    DELETE FROM analytics.comparison_publication_hourly
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                        OR institution_id = :institutionId
                        OR platform_account_id = :accountId
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .param("institutionId", institutionId)
                    .param("accountId", accountId)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.comparison_metric_point
                     WHERE institution_id = :institutionId
                        OR cohort_id IN (
                            SELECT id
                              FROM analytics.comparison_cohort
                             WHERE dataset_revision_id IN (
                                 SELECT id
                                   FROM analytics.dataset_revision
                                  WHERE correlation_id IN (:correlationIds)
                             )
                        )
                    """)
                    .param("institutionId", institutionId)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.comparison_cohort_member
                     WHERE institution_id = :institutionId
                        OR cohort_id IN (
                            SELECT id
                              FROM analytics.comparison_cohort
                             WHERE dataset_revision_id IN (
                                 SELECT id
                                   FROM analytics.dataset_revision
                                  WHERE correlation_id IN (:correlationIds)
                             )
                        )
                    """)
                    .param("institutionId", institutionId)
                    .param("correlationIds", ownedCorrelations)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.comparison_cohort
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();

            deleteOwnedProjectionRows(
                    owner,
                    "analytics.legacy_overview_account",
                    "account_id = :accountId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.legacy_overview_card",
                    "institution_id = :institutionId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.institution_metric_aggregate",
                    "institution_id = :institutionId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.publication_latest",
                    "institution_id = :institutionId OR platform_account_id = :accountId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.publication_hourly",
                    "institution_id = :institutionId OR platform_account_id = :accountId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.institution_daily_metrics",
                    "institution_id = :institutionId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.institution_monthly_metrics",
                    "institution_id = :institutionId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            deleteOwnedProjectionRows(
                    owner,
                    "analytics.institution_period_metrics",
                    "institution_id = :institutionId",
                    institutionId,
                    accountId,
                    ownedCorrelations
            );
            owner.sql("""
                    DELETE FROM analytics.projection_state
                     WHERE dataset_revision_id IN (
                         SELECT id
                           FROM analytics.dataset_revision
                          WHERE correlation_id IN (:correlationIds)
                     )
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();

            owner.sql("DELETE FROM ingest.collection_run WHERE id = :runId")
                    .param("runId", runId)
                    .update();
            owner.sql("DELETE FROM catalog.platform_account WHERE id = :accountId")
                    .param("accountId", accountId)
                    .update();
            owner.sql("DELETE FROM catalog.institution WHERE id = :institutionId")
                    .param("institutionId", institutionId)
                    .update();
            owner.sql("""
                    DELETE FROM analytics.dataset_revision
                     WHERE correlation_id IN (:correlationIds)
                    """)
                    .param("correlationIds", ownedCorrelations)
                    .update();

            long remainingLatestRevision = owner.sql(
                            "SELECT coalesce(max(id), 0) FROM analytics.dataset_revision"
                    )
                    .query(Long.class)
                    .single();
            if (restoreProjections && remainingLatestRevision > 0) {
                owner.sql("SELECT analytics.rebuild_core_projections(:revision)")
                        .param("revision", remainingLatestRevision)
                        .query((row, rowNumber) -> row.getString(1))
                        .single();
            }
        });
    }

    private static void deleteOwnedProjectionRows(
            JdbcClient owner,
            String table,
            String fixturePredicate,
            UUID institutionId,
            UUID accountId,
            List<UUID> ownedCorrelations
    ) {
        owner.sql("""
                DELETE FROM %s
                 WHERE dataset_revision_id IN (
                     SELECT id
                       FROM analytics.dataset_revision
                      WHERE correlation_id IN (:correlationIds)
                 )
                    OR (%s)
                """.formatted(table, fixturePredicate))
                .param("correlationIds", ownedCorrelations)
                .param("institutionId", institutionId)
                .param("accountId", accountId)
                .update();
    }

    private static DriverManagerDataSource dataSource(String url, String username, String password) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(url, username, password);
        dataSource.setDriverClassName("org.postgresql.Driver");
        return dataSource;
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " must be set for the integration test");
        }
        return value;
    }
}
