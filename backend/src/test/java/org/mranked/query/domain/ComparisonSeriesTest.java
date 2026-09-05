package org.mranked.query.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.mranked.catalog.domain.InstitutionIdentity;

class ComparisonSeriesTest {
    private static final InstitutionIdentity INSTITUTION = new InstitutionIdentity(
            UUID.fromString("10000000-0000-4000-8000-000000000001"),
            1,
            "Test University",
            "TU"
    );

    @Test
    void primaryAndEngagementCohortsAndPointsRemainIndependent() {
        var primary = new ArrayList<>(List.of(point(0, "10")));
        var engagement = new ArrayList<>(List.of(point(1, "12.5")));

        var series = new ComparisonSeries(
                UUID.fromString("20000000-0000-4000-8000-000000000001"),
                ComparisonSelectionType.CHANNELS,
                9,
                "Test channel",
                INSTITUTION,
                3,
                2,
                primary,
                engagement
        );
        primary.clear();
        engagement.clear();

        assertThat(series.primaryCohortSize()).isEqualTo(3);
        assertThat(series.engagementCohortSize()).isEqualTo(2);
        assertThat(series.points()).extracting(ComparisonPoint::hourOffset).containsExactly(0);
        assertThat(series.engagementPoints())
                .extracting(ComparisonPoint::hourOffset)
                .containsExactly(1);
    }

    @Test
    void negativeCompanionCohortSizeIsRejected() {
        assertThatThrownBy(() -> new ComparisonSeries(
                UUID.randomUUID(), ComparisonSelectionType.INSTITUTIONS, 1,
                "Test", INSTITUTION, 0, -1, List.of(), List.of()
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("cohort sizes");
    }

    private static ComparisonPoint point(int hour, String value) {
        return new ComparisonPoint(
                hour, new BigDecimal(value), 1, BigDecimal.ONE, "exact"
        );
    }
}
