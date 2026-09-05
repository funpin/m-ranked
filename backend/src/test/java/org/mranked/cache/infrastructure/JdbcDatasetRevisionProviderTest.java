package org.mranked.cache.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JdbcDatasetRevisionProviderTest {
    @Test
    void selectsTheNewestRevisionWithAllSixCoreProjectionsReady() {
        assertThat(JdbcDatasetRevisionProvider.CURRENT_REVISION_SQL)
                .contains("analytics.dataset_revision")
                .contains("analytics.projection_state")
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
                .contains("HAVING count(state.projection_name) = 6");
    }
}
