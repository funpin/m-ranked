package org.mranked.query.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;

class OverviewQueryTest {
    @Test
    void normalizesLegacyDefaultsBeforeCachingOrSql() {
        OverviewQuery all = OverviewQuery.normalized(
                Platform.ALL, PeriodKey.ONE_DAY, "  вуз  ", "unknown", "sideways"
        );
        OverviewQuery telegram = OverviewQuery.normalized(
                Platform.TELEGRAM, PeriodKey.ONE_DAY, null, null, null
        );

        assertThat(all.search()).isEqualTo("вуз");
        assertThat(all.sort()).isEqualTo("m_rating");
        assertThat(all.direction()).isEqualTo("desc");
        assertThat(telegram.search()).isEmpty();
        assertThat(telegram.sort()).isEqualTo("median_reactions");
        assertThat(telegram.direction()).isEqualTo("desc");
    }

    @Test
    void keepsOnlyPlatformSpecificSortKeysAndNameDefaultsAscending() {
        assertThat(OverviewQuery.normalized(
                Platform.ALL, PeriodKey.SEVEN_DAYS, "", "name", null
        ).direction()).isEqualTo("asc");
        assertThat(OverviewQuery.normalized(
                Platform.VK, PeriodKey.SEVEN_DAYS, "", "subscribers", "asc"
        )).extracting(OverviewQuery::sort, OverviewQuery::direction)
                .containsExactly("subscribers", "asc");
        assertThat(OverviewQuery.normalized(
                Platform.ALL, PeriodKey.SEVEN_DAYS, "", "subscribers", "asc"
        ).sort()).isEqualTo("m_rating");
        assertThat(OverviewQuery.normalized(
                Platform.RUTUBE, PeriodKey.SEVEN_DAYS, "", "coverage", "asc"
        ).sort()).isEqualTo("median_reactions");
    }

    @Test
    void rejectsBypassingNormalization() {
        assertThatThrownBy(() -> new OverviewQuery(
                Platform.TELEGRAM, PeriodKey.ONE_DAY, "", "coverage", "desc"
        )).isInstanceOf(IllegalArgumentException.class);
    }
}
