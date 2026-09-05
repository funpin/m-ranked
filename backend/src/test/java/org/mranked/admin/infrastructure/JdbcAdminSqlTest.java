package org.mranked.admin.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JdbcAdminSqlTest {
    @Test
    void jobQueriesAreBoundedAndNeverTouchRawEvidence() {
        assertThat(JdbcAdminQueryRepository.COLLECTION_JOBS_SQL)
                .contains("ingest.collection_run")
                .contains("ORDER BY run.started_at DESC, run.id DESC")
                .contains("LIMIT :limit")
                .doesNotContain("raw_payload")
                .doesNotContain("metric_snapshot");
        assertThat(JdbcAdminQueryRepository.ACCOUNT_RESULTS_SQL)
                .contains("ingest.collection_account_result")
                .contains("sanitized_error_code")
                .contains("LIMIT :fetchLimit")
                .doesNotContain("raw_payload");
        assertThat(JdbcAdminQueryRepository.PLATFORM_ACCOUNT_SQL)
                .contains("catalog.platform_account")
                .contains("WHERE account.id = :accountId")
                .contains("account.enabled")
                .contains("account.row_version")
                .contains("account.updated_at")
                .doesNotContain("canonical_external_id")
                .doesNotContain("current_url")
                .doesNotContain("current_username")
                .doesNotContain("raw_payload");
    }

    @Test
    void enableCommandLocksAndUsesOptimisticUpdate() {
        assertThat(JdbcAdminCommandRepository.LOCK_ACCOUNT_SQL)
                .contains("FOR UPDATE");
        assertThat(JdbcAdminCommandRepository.UPDATE_ACCOUNT_SQL)
                .contains("row_version = row_version + 1")
                .contains("row_version = :expectedRowVersion")
                .contains("transaction_timestamp()");
    }

    @Test
    void successfulCommandPublishesConfigurationRevisionAndSanitizedAudit() {
        assertThat(JdbcAdminCommandRepository.INSERT_REVISION_SQL)
                .contains("'configuration'")
                .contains(":correlationId");
        assertThat(JdbcAdminCommandRepository.REBUILD_PROJECTIONS_SQL)
                .contains("analytics.rebuild_core_projections(:datasetRevision)");
        assertThat(JdbcAdminCommandRepository.INSERT_OUTBOX_SQL)
                .contains("platform_account.enabled_changed")
                .contains("jsonb_build_object")
                .doesNotContain("password")
                .doesNotContain("payload bytea");
        assertThat(JdbcAdminCommandRepository.INSERT_STATE_AUDIT_SQL)
                .contains("ops_and_admin.audit_log")
                .contains("before_state")
                .contains("after_state")
                .contains("'enabled'")
                .contains("'rowVersion'")
                .doesNotContain("canonical_external_id")
                .doesNotContain("current_username")
                .doesNotContain("current_url")
                .doesNotContain("raw_payload");
    }
}
