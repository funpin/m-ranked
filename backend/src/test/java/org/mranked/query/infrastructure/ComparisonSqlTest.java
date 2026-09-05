package org.mranked.query.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ComparisonSqlTest {
    @Test
    void institutionCurveUsesSeparateMetricAndRatioFixedCohorts() {
        assertThat(ComparisonSql.INSTITUTIONS)
                .contains("analytics.comparison_cohort_member")
                .contains("analytics.comparison_publication_hourly")
                .contains("hourly.dataset_revision_id = cohort.dataset_revision_id")
                .contains("primary_members AS")
                .contains("engagement_members AS")
                .contains("hourly.hour_offset = hourly.primary_start_hour")
                .contains("hourly.hour_offset = hourly.engagement_start_hour")
                .contains("hourly.hour_offset = hourly.horizon_hour")
                .contains("percentile_cont(0.5) WITHIN GROUP (ORDER BY hourly.engagement_value)")
                .contains("hourly.engagement_percent")
                .doesNotContain("analytics.comparison_metric_point")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("migration.");
    }

    @Test
    void repositoryConsumesTheRevisionPinnedPrecomputedSameSnapshotRatio() {
        assertThat(ComparisonSql.INSTITUTIONS)
                .contains("prepared.dataset_revision_id = cohort.dataset_revision_id")
                .contains("hourly.engagement_percent")
                .contains("hourly.engagement_quality::text")
                .doesNotContain("supported_interactions")
                .doesNotContain("views_count <= 0");
    }

    @Test
    void telegramRatioStartsAtHourOneAndSelectionRemainsBoundedAndOrdered() {
        assertThat(ComparisonSql.CHANNELS)
                .contains("greatest(cohort.required_start_hour, 1) AS engagement_start_hour")
                .contains("LIMIT :institutionLimit")
                .contains("jsonb_array_elements_text")
                .contains("WITH ORDINALITY")
                .contains("channel_alias.entity_type = 'channels'")
                .contains("JOIN selected_channels selected")
                .contains("primary_members AS")
                .contains("engagement_members AS")
                .contains("percentile_cont(0.5) WITHIN GROUP (ORDER BY hourly.engagement_value)")
                .contains("ORDER BY selected.selection_order, hour.hour_offset")
                .doesNotContain("analytics.comparison_metric_point")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("migration.");
    }

    @Test
    void requestTimeQueryNeverScansOrReconstructsRawObservations() {
        assertThat(ComparisonSql.CHANNELS)
                .contains("analytics.comparison_publication_hourly")
                .doesNotContain("publication_metric_snapshot")
                .doesNotContain("snapshot_entity_hourly")
                .doesNotContain("numbered_entity_hourly");
    }
}
