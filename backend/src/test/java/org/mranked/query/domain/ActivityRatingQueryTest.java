package org.mranked.query.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.mranked.analytics.domain.PeriodKey;
import org.mranked.analytics.domain.Platform;

class ActivityRatingQueryTest {
    @Test
    void normalizesTelegramSortsWithLegacyFallbacks() {
        ActivityRatingQuery query = ActivityRatingQuery.normalized(
                Platform.TELEGRAM, PeriodKey.THIRTY_DAYS,
                "not-a-sort", "sideways", "not-a-sort", "sideways"
        );

        assertThat(query.channelSort()).isEqualTo("engagement");
        assertThat(query.channelDirection()).isEqualTo("desc");
        assertThat(query.postSort()).isEqualTo("reactions");
        assertThat(query.postDirection()).isEqualTo("desc");
        assertThat(query.entityType()).isEqualTo("channels");
        assertThat(query.publicationLegacyType()).isEqualTo("posts");
    }

    @Test
    void preservesVkAndRutubePlatformSpecificSorts() {
        assertThat(ActivityRatingQuery.normalized(
                Platform.VK, PeriodKey.ONE_DAY,
                "views", "asc", "shares", "asc"
        )).extracting(
                ActivityRatingQuery::channelSort,
                ActivityRatingQuery::channelDirection,
                ActivityRatingQuery::postSort,
                ActivityRatingQuery::postDirection
        ).containsExactly("views", "asc", "shares", "asc");

        ActivityRatingQuery rutube = ActivityRatingQuery.normalized(
                Platform.RUTUBE, PeriodKey.SEVEN_DAYS,
                "average", "desc", "shares", "asc"
        );
        assertThat(rutube.postSort()).isEqualTo("view_share");
        assertThat(rutube.postDirection()).isEqualTo("asc");
        assertThat(rutube.entityType()).isEqualTo("institutions");
    }

    @Test
    void rejectsPlatformsWhoseLegacyRatingIsPending() {
        assertThatThrownBy(() -> ActivityRatingQuery.normalized(
                Platform.MAX, PeriodKey.ONE_DAY,
                "engagement", "desc", "view_share", "desc"
        )).isInstanceOf(IllegalArgumentException.class);
    }
}
