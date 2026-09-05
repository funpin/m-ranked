package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JdbcReadinessProbeTest {
    @Test
    void requiresAllSixCoreStatesAtTheLatestCommittedRevision() {
        assertThat(JdbcReadinessProbe.LATEST_CORE_READINESS_SQL)
                .contains("ORDER BY revision.id DESC")
                .contains("LIMIT 1")
                .contains("('publication_latest')")
                .contains("('publication_hourly')")
                .contains("('institution_daily_metrics')")
                .contains("('institution_monthly_metrics')")
                .contains("('institution_period_metrics')")
                .contains("('comparison')")
                .contains("state.dataset_revision_id = revision.id")
                .contains("state.status = 'ready'")
                .contains("count(state.projection_name) AS ready_count");
    }
}
